import uuid
from collections.abc import Callable, Mapping
from typing import TypeVar

from calendar_contract import (
    CalendarError,
    CalendarService,
    CreateEvent,
    ErrorCode,
    Event,
    ReplaceEvent,
)

from app.core.config import settings
from app.errors import (
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageNotConfiguredError,
)

T = TypeVar("T")


class InMemoryCalendarService:
    def __init__(
        self,
        failures: Mapping[str, Exception] | None = None,
    ) -> None:
        self.events: dict[str, Event] = {}
        self._failures = dict(failures or {})

    def create(self, request: CreateEvent) -> Event:
        self._raise_injected_failure("create")
        event = Event(
            id=uuid.uuid4().hex,
            title=request.title,
            start=request.start,
            end=request.end,
        )
        self.events[event.id] = event
        return event

    def get(self, event_id: str) -> Event:
        self._raise_injected_failure("get")
        try:
            return self.events[event_id]
        except KeyError as error:
            raise CalendarError(
                ErrorCode.NOT_FOUND,
                "Event not found.",
                retryable=False,
            ) from error

    def replace(self, event_id: str, request: ReplaceEvent) -> Event:
        self._raise_injected_failure("replace")
        if event_id not in self.events:
            raise CalendarError(
                ErrorCode.NOT_FOUND,
                "Event not found.",
                retryable=False,
            )

        event = Event(
            id=event_id,
            title=request.title,
            start=request.start,
            end=request.end,
        )
        self.events[event.id] = event
        return event

    def delete(self, event_id: str) -> None:
        self._raise_injected_failure("delete")
        try:
            del self.events[event_id]
        except KeyError as error:
            raise CalendarError(
                ErrorCode.NOT_FOUND,
                "Event not found.",
                retryable=False,
            ) from error

    def _raise_injected_failure(self, method: str) -> None:
        failure = self._failures.get(method)
        if failure is not None:
            raise failure


class _MappedCalendarService:
    def __init__(self, service: CalendarService) -> None:
        self._service = service

    def create(self, request: CreateEvent) -> Event:
        return self._call("create", lambda: self._service.create(request))

    def get(self, event_id: str) -> Event:
        return self._call("get", lambda: self._service.get(event_id))

    def replace(self, event_id: str, request: ReplaceEvent) -> Event:
        return self._call(
            "replace",
            lambda: self._service.replace(event_id, request),
        )

    def delete(self, event_id: str) -> None:
        self._call("delete", lambda: self._service.delete(event_id))

    @staticmethod
    def _call(step: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except CalendarError as error:
            message = f"Calendar {step} failed"
            if error.code is ErrorCode.INVALID_INPUT:
                raise InvalidRequestError(message) from error
            if error.code is ErrorCode.NOT_FOUND:
                raise FileNotFoundError(message) from error
            if error.code is ErrorCode.ACCESS_DENIED:
                raise PermissionDeniedError(message) from error
            if error.code is ErrorCode.PROVIDER_UNAVAILABLE:
                raise ProviderUnavailableError(message) from error
            raise ProviderError(message) from error
        except Exception as error:
            raise ProviderError(f"Calendar {step} failed") from error


def get_calendar_service() -> CalendarService:
    if settings.calendar_impl == "fake":
        service: CalendarService = InMemoryCalendarService()
    elif settings.calendar_impl == "team5":
        token_file = settings.team5_token_file
        if token_file is None or not token_file.strip():
            raise StorageNotConfiguredError(
                "TEAM5_TOKEN_FILE is required when CALENDAR_IMPL=team5"
            )

        from team5_calendar import create_calendar_service

        try:
            service = create_calendar_service(token_file=token_file)
        except Exception as error:
            raise ProviderError("Calendar initialization failed") from error
    else:
        raise StorageNotConfiguredError("CALENDAR_IMPL must be 'fake' or 'team5'")

    return _MappedCalendarService(service)
