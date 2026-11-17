import uuid
from collections.abc import Callable, Mapping
from typing import TypeVar

from issue_tracker_contract import (
    ErrorCode,
    Issue,
    IssueProvider,
    IssueUpdate,
    ServiceError,
)

from app.core.config import settings
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    StorageNotConfiguredError,
)

T = TypeVar("T")


class InMemoryIssueProvider:
    def __init__(
        self,
        failures: Mapping[str, Exception] | None = None,
    ) -> None:
        self.issues: dict[str, Issue] = {}
        self._failures = dict(failures or {})

    def get_issue(self, issue_id: str, *, fresh: bool = False) -> Issue:
        self._raise_injected_failure("get_issue")
        try:
            return self.issues[issue_id]
        except KeyError as error:
            raise ServiceError(
                ErrorCode.NOT_FOUND,
                "Issue not found.",
                provider_involved=False,
            ) from error

    def update_issue(self, issue_id: str, changes: IssueUpdate) -> Issue:
        self._raise_injected_failure("update_issue")
        existing = self._get_existing(issue_id)
        issue = Issue(
            id=existing.id,
            title=changes.title if changes.title is not None else existing.title,
        )
        self.issues[issue.id] = issue
        return issue

    def delete_issue(self, issue_id: str) -> None:
        self._raise_injected_failure("delete_issue")
        try:
            del self.issues[issue_id]
        except KeyError as error:
            raise ServiceError(
                ErrorCode.NOT_FOUND,
                "Issue not found.",
                provider_involved=False,
            ) from error

    def create_issue(self, title: str) -> Issue:
        self._raise_injected_failure("create_issue")
        issue = Issue(id=uuid.uuid4().hex, title=title)
        self.issues[issue.id] = issue
        return issue

    def list_issues(self, *, limit: int) -> list[Issue]:
        self._raise_injected_failure("list_issues")
        return list(reversed(self.issues.values()))[:limit]

    def _get_existing(self, issue_id: str) -> Issue:
        try:
            return self.issues[issue_id]
        except KeyError as error:
            raise ServiceError(
                ErrorCode.NOT_FOUND,
                "Issue not found.",
                provider_involved=False,
            ) from error

    def _raise_injected_failure(self, method: str) -> None:
        failure = self._failures.get(method)
        if failure is not None:
            raise failure


class _MappedIssueProvider:
    def __init__(self, provider: IssueProvider) -> None:
        self._provider = provider

    def get_issue(self, issue_id: str, *, fresh: bool = False) -> Issue:
        return self._call(
            "get_issue",
            lambda: self._provider.get_issue(issue_id, fresh=fresh),
        )

    def update_issue(self, issue_id: str, changes: IssueUpdate) -> Issue:
        return self._call(
            "update_issue",
            lambda: self._provider.update_issue(issue_id, changes),
        )

    def delete_issue(self, issue_id: str) -> None:
        self._call("delete_issue", lambda: self._provider.delete_issue(issue_id))

    def create_issue(self, title: str) -> Issue:
        return self._call("create_issue", lambda: self._provider.create_issue(title))

    def list_issues(self, *, limit: int) -> list[Issue]:
        return self._call(
            "list_issues",
            lambda: self._provider.list_issues(limit=limit),
        )

    @staticmethod
    def _call(step: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except ServiceError as error:
            message = f"Issue tracker {step} failed"
            if error.code is ErrorCode.INVALID_INPUT:
                raise InvalidRequestError(message) from error
            if error.code is ErrorCode.NOT_FOUND:
                raise FileNotFoundError(message) from error
            if error.code is ErrorCode.ACCESS_DENIED:
                raise PermissionDeniedError(message) from error
            if error.code is ErrorCode.SERVICE_NOT_CONFIGURED:
                raise StorageNotConfiguredError(message) from error
            if error.code in (
                ErrorCode.PRECONDITION_FAILED,
                ErrorCode.REQUEST_IN_PROGRESS,
            ):
                raise FileConflictError(message) from error
            if error.code is ErrorCode.IDEMPOTENCY_KEY_REUSED:
                raise InvalidRequestError(message) from error
            raise ProviderError(message) from error
        except Exception as error:
            raise ProviderError(f"Issue tracker {step} failed") from error


def get_issue_provider() -> IssueProvider:
    if settings.tracker_impl == "fake":
        provider: IssueProvider = InMemoryIssueProvider()
    elif settings.tracker_impl == "team4":
        trello_settings = {
            "TRELLO_API_KEY": settings.trello_api_key,
            "TRELLO_TOKEN": settings.trello_token,
            "TRELLO_LIST_ID": settings.trello_list_id,
        }
        missing_settings = [
            name
            for name, value in trello_settings.items()
            if value is None or not value.strip()
        ]
        if missing_settings:
            raise StorageNotConfiguredError(
                "Required when TRACKER_IMPL=team4: " + ", ".join(missing_settings)
            )

        from team_4_issue_tracker_trello import TrelloIssueProvider

        try:
            provider = TrelloIssueProvider()
        except Exception as error:
            raise ProviderError("Issue tracker initialization failed") from error
    else:
        raise StorageNotConfiguredError("TRACKER_IMPL must be 'fake' or 'team4'")

    return _MappedIssueProvider(provider)
