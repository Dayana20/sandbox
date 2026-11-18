from calendar_contract import CalendarService, Event
from fastapi import APIRouter, Body, Depends
from issue_tracker_contract import Issue, IssueProvider
from pydantic import BaseModel

from app.api.responses import error_responses
from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.integrations.calendar import get_calendar_service
from app.integrations.issue_tracker import get_issue_provider
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from app.workflows.meeting import build_event_request, run_meeting_workflow


router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


class MeetingResponse(BaseModel):
    event: Event
    document: FileResource
    issue: Issue


@router.post(
    "/meeting",
    status_code=201,
    responses=error_responses(400, 403, 404, 409, 502, 503),
)
def create_meeting(
    title: str | None = Body(None),
    start: str | None = Body(None),
    end: str | None = Body(None),
    storage: DocumentStorage = Depends(get_document_storage),
    calendar: CalendarService = Depends(get_calendar_service),
    issues: IssueProvider = Depends(get_issue_provider),
) -> MeetingResponse:
    '''
    Create a calendar event, save a notes document for it in storage, and
    open a follow-up issue.

    The calendar and issue tracker implementations come from CALENDAR_IMPL
    and TRACKER_IMPL. If a step fails, earlier steps are undone and the error
    says which step failed and whether anything was left behind.
    '''
    if title is None or start is None or end is None:
        raise InvalidRequestError("title, start and end are required")

    # Validated before any provider is called.
    request = build_event_request(title, start, end)

    result = run_meeting_workflow(request, calendar, storage, issues)
    return MeetingResponse(
        event=result.event,
        document=result.document,
        issue=result.issue,
    )
