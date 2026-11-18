import logging
from collections.abc import Callable

from calendar_contract import CalendarService, CreateEvent, Event
from issue_tracker_contract import Issue, IssueProvider
from pydantic import ValidationError

from app.errors import InvalidRequestError, ProviderError, StorageError
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from app.validation import validate_path

logger = logging.getLogger(__name__)

ISSUE_PREFIX = "Follow up: "
# Team 4's contract caps issue titles at 256 characters (MAX_TITLE_LENGTH).
# The issue title is ISSUE_PREFIX + title, so the meeting title gets the rest.
MAX_TITLE_LENGTH = 256 - len(ISSUE_PREFIX)


class MeetingResult:
    def __init__(self, event: Event, document: FileResource, issue: Issue):
        self.event = event
        self.document = document
        self.issue = issue


def build_event_request(title: str, start: str, end: str) -> CreateEvent:
    """
        Check the whole request before any provider is called.

        The calendar contract validates the title and the RFC 3339 times when
        CreateEvent is built, so a bad request never creates anything.
    """
    if len(title.strip()) > MAX_TITLE_LENGTH:
        raise InvalidRequestError(
            f"title must be at most {MAX_TITLE_LENGTH} characters"
        )

    try:
        return CreateEvent(title=title, start=start, end=end)
    except (ValidationError, ValueError):
        # No cause: app/main.py reads a cause as "a provider was called".
        raise InvalidRequestError(
            "title, start and end must be a non-empty title and RFC 3339 "
            "times with an offset, with end after start"
        ) from None


def notes_for(event: Event) -> bytes:
    return (
        f"# {event.title}\n\n"
        f"- Start: {event.start}\n"
        f"- End: {event.end}\n"
        f"- Calendar event: {event.id}\n\n"
        "## Notes\n\n"
    ).encode()


def run_meeting_workflow(
    request: CreateEvent,
    calendar: CalendarService,
    storage: DocumentStorage,
    issues: IssueProvider,
) -> MeetingResult:
    """
        Create a calendar event, save its notes document, open a follow-up issue.

        Steps run in that order and only after the previous one succeeded.
        If a step fails, the steps that already succeeded are undone in reverse
        order and the original error is raised. A ProviderError means the
        failed step's own outcome is unknown, so that step is not undone.
        Undo is best effort: an undo that fails is logged and named in the
        error message, so the caller knows what may be left behind.
    """
    undo: list[tuple[str, Callable[[], None]]] = []

    try:
        event = calendar.create(request)
        undo.append(("calendar event", lambda: calendar.delete(event.id)))

        path = validate_path(f"/meetings/{event.id}.md")
        document = storage.upload(path, notes_for(event))
        undo.append(("notes document", lambda: storage.delete(document.path)))

        issue = issues.create_issue(ISSUE_PREFIX + event.title)
    except StorageError as exc:
        left_behind = _undo(undo)
        # Keep the provider exception as the cause, so logging still knows
        # whether a provider was involved.
        raise _with_outcome(exc, left_behind) from exc.__cause__

    return MeetingResult(event, document, issue)


def _undo(undo: list[tuple[str, Callable[[], None]]]) -> list[str]:
    left_behind = []
    for name, action in reversed(undo):
        try:
            action()
        except Exception as exc:
            # Only the step and the error type: never titles, paths or ids.
            logger.warning(
                "workflow_undo_failed step=%s error=%s", name, type(exc).__name__
            )
            left_behind.append(name)
    return left_behind


def _with_outcome(exc: StorageError, left_behind: list[str]) -> StorageError:
    message = str(exc)
    if isinstance(exc, ProviderError):
        message += "; this step may have completed"
    if left_behind:
        message += "; could not undo: " + ", ".join(left_behind)
    else:
        message += "; earlier steps were undone"
    return type(exc)(message)
