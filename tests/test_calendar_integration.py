from unittest.mock import Mock

import pytest
from calendar_contract import CalendarError, CreateEvent, ErrorCode

from app.core.config import Settings, settings
from app.errors import (
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageNotConfiguredError,
)
from app.integrations.calendar import (
    InMemoryCalendarService,
    _MappedCalendarService,
    get_calendar_service,
)


def test_settings_default_calendar_implementation(monkeypatch):
    monkeypatch.delenv("CALENDAR_IMPL", raising=False)

    assert Settings().calendar_impl == "fake"


def test_factory_returns_fake_by_default(monkeypatch):
    monkeypatch.setattr(settings, "calendar_impl", "fake")

    service = get_calendar_service()
    event = service.create(
        CreateEvent(
            title="Team 5 calendar fake",
            start="2030-01-01T10:00:00Z",
            end="2030-01-01T11:00:00Z",
        )
    )

    assert service.get(event.id) == event


def test_factory_selects_team5_service(monkeypatch):
    implementation = InMemoryCalendarService()
    create_service = Mock(return_value=implementation)
    monkeypatch.setattr(settings, "calendar_impl", "team5")
    monkeypatch.setattr(settings, "team5_token_file", "/tmp/team5-token.json")
    monkeypatch.setattr(
        "team5_calendar.create_calendar_service",
        create_service,
    )

    service = get_calendar_service()

    create_service.assert_called_once_with(token_file="/tmp/team5-token.json")
    assert service.create(
        CreateEvent(
            title="Team 5 calendar fake",
            start="2030-01-01T10:00:00Z",
            end="2030-01-01T11:00:00Z",
        )
    ).id


def test_factory_rejects_unknown_implementation(monkeypatch):
    monkeypatch.setattr(settings, "calendar_impl", "unknown")

    with pytest.raises(StorageNotConfiguredError, match="CALENDAR_IMPL"):
        get_calendar_service()


def test_factory_requires_team5_token_file(monkeypatch):
    monkeypatch.setattr(settings, "calendar_impl", "team5")
    monkeypatch.setattr(settings, "team5_token_file", None)

    with pytest.raises(StorageNotConfiguredError, match="TEAM5_TOKEN_FILE"):
        get_calendar_service()


@pytest.mark.parametrize(
    ("error_code", "application_error"),
    [
        (ErrorCode.INVALID_INPUT, InvalidRequestError),
        (ErrorCode.NOT_FOUND, FileNotFoundError),
        (ErrorCode.ACCESS_DENIED, PermissionDeniedError),
        (ErrorCode.PROVIDER_ERROR, ProviderError),
        (ErrorCode.PROVIDER_UNAVAILABLE, ProviderUnavailableError),
    ],
)
def test_contract_errors_map_to_application_errors(error_code, application_error):
    failure = CalendarError(
        error_code,
        "Calendar contract failure.",
        retryable=False,
    )
    service = InMemoryCalendarService(failures={"get": failure})
    mapped_service = _MappedCalendarService(service)

    with pytest.raises(application_error, match="Calendar get failed") as exc_info:
        mapped_service.get("event-id")

    assert exc_info.value.__cause__ is failure


def test_unexpected_error_maps_to_provider_error_with_step_name():
    service = InMemoryCalendarService(
        failures={"create": RuntimeError("provider detail")}
    )
    mapped_service = _MappedCalendarService(service)

    with pytest.raises(ProviderError, match="Calendar create failed") as exc_info:
        mapped_service.create(
            CreateEvent(
                title="Team 5 calendar fake",
                start="2030-01-01T10:00:00Z",
                end="2030-01-01T11:00:00Z",
            )
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value) == "Calendar create failed"


def test_fake_can_inject_failure_for_chosen_method():
    failure = RuntimeError("injected failure")
    service = InMemoryCalendarService(failures={"delete": failure})

    with pytest.raises(RuntimeError, match="injected failure") as exc_info:
        service.delete("event-id")

    assert exc_info.value is failure
