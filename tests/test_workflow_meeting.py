import logging

import pytest
from calendar_contract import CalendarError
from calendar_contract import ErrorCode as CalendarCode
from fastapi.testclient import TestClient
from issue_tracker_contract import ErrorCode as IssueCode
from issue_tracker_contract import ServiceError

from app.core.config import settings
from app.dependencies import get_document_storage
from app.errors import PermissionDeniedError
from app.integrations.calendar import (
    InMemoryCalendarService,
    _MappedCalendarService,
    get_calendar_service,
)
from app.integrations.issue_tracker import (
    InMemoryIssueProvider,
    _MappedIssueProvider,
    get_issue_provider,
)
from app.main import app
from tests.fakes import FakeDocumentStorage


client = TestClient(app)

MEETING = {
    "title": "Design review",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
}


class Services:
    """The three fakes behind the route, reachable from each test."""

    def __init__(self, calendar_failures=None, issue_failures=None):
        self.calendar = InMemoryCalendarService(calendar_failures)
        self.issues = InMemoryIssueProvider(issue_failures)
        self.storage = FakeDocumentStorage()

    def install(self):
        # The real adapters' error mapping wraps the fakes, as in production.
        app.dependency_overrides[get_calendar_service] = lambda: _MappedCalendarService(self.calendar)
        app.dependency_overrides[get_issue_provider] = lambda: _MappedIssueProvider(self.issues)
        app.dependency_overrides[get_document_storage] = lambda: self.storage
        return self

    def nothing_created(self):
        return not self.calendar.events and not self.issues.issues and not self.storage.files


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def post(body=MEETING):
    return client.post("/workflows/meeting", json=body)


def calendar_error(code):
    return CalendarError(code, "provider said no", retryable=False)


def issue_error(code):
    return ServiceError(code, "provider said no", provider_involved=True)


# --- success across all three verticals -------------------------------------


def test_meeting_creates_event_document_and_issue():
    services = Services().install()

    response = post()

    assert response.status_code == 201
    body = response.json()
    event_id = body["event"]["id"]
    assert body["event"]["title"] == "Design review"
    assert body["document"]["path"] == f"/meetings/{event_id}.md"
    assert body["issue"]["title"] == "Follow up: Design review"

    assert event_id in services.calendar.events
    assert body["issue"]["id"] in services.issues.issues
    notes = services.storage.download(f"/meetings/{event_id}.md").decode()
    assert "# Design review" in notes and event_id in notes


def test_longest_allowed_title_fits_the_issue_title_limit():
    services = Services().install()

    response = post({**MEETING, "title": "x" * 245})

    assert response.status_code == 201
    assert len(response.json()["issue"]["title"]) == 256
    assert services.issues.issues


# --- bad input never reaches a provider -------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"start": MEETING["start"], "end": MEETING["end"]},
        {**MEETING, "title": "   "},
        {**MEETING, "title": "x" * 246},
        {**MEETING, "start": "2026-11-20T15:00:00"},
        {**MEETING, "end": "2026-11-20T14:00:00-05:00"},
    ],
    ids=["missing title", "blank title", "title too long", "no offset", "end before start"],
)
def test_bad_input_is_400_and_creates_nothing(body):
    services = Services().install()

    response = post(body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert services.nothing_created()


# --- a dependency fails: earlier steps are undone ---------------------------


def test_calendar_unavailable_is_503_and_creates_nothing():
    services = Services(calendar_failures={"create": calendar_error(CalendarCode.PROVIDER_UNAVAILABLE)}).install()

    response = post()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert services.nothing_created()


def test_storage_failure_undoes_the_event():
    services = Services().install()

    def refuse(path, content):
        raise PermissionDeniedError("No write permission")

    services.storage.upload = refuse

    response = post()

    assert response.status_code == 403
    assert "earlier steps were undone" in response.json()["error"]["message"]
    assert services.nothing_created()


def test_issue_tracker_refusal_undoes_event_and_document():
    services = Services(issue_failures={"create_issue": issue_error(IssueCode.ACCESS_DENIED)}).install()

    response = post()

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "permission_denied"
    assert error["message"].startswith("Issue tracker create_issue failed")
    assert "earlier steps were undone" in error["message"]
    assert services.nothing_created()


def test_unknown_issue_outcome_is_reported_as_unknown():
    services = Services(issue_failures={"create_issue": issue_error(IssueCode.PROVIDER_ERROR)}).install()

    response = post()

    assert response.status_code == 502
    assert "this step may have completed" in response.json()["error"]["message"]
    assert not services.calendar.events and not services.storage.files


def test_failed_undo_is_named_in_the_error():
    services = Services(
        calendar_failures={"delete": calendar_error(CalendarCode.PROVIDER_ERROR)},
        issue_failures={"create_issue": issue_error(IssueCode.ACCESS_DENIED)},
    ).install()

    response = post()

    assert response.status_code == 403
    assert "could not undo: calendar event" in response.json()["error"]["message"]
    assert services.calendar.events  # left behind, and the caller was told
    assert not services.storage.files


# --- implementations are chosen by configuration -----------------------------


def test_fakes_are_selected_by_configuration(monkeypatch):
    monkeypatch.setattr(settings, "calendar_impl", "fake")
    monkeypatch.setattr(settings, "tracker_impl", "fake")
    app.dependency_overrides[get_document_storage] = FakeDocumentStorage

    response = post()

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("setting", "value"),
    [("calendar_impl", "team5"), ("tracker_impl", "team4")],
)
def test_real_implementation_without_credentials_is_503_before_any_step(monkeypatch, setting, value):
    monkeypatch.setattr(settings, "calendar_impl", "fake")
    monkeypatch.setattr(settings, "tracker_impl", "fake")
    monkeypatch.setattr(settings, setting, value)
    monkeypatch.setattr(settings, "team5_token_file", None)
    monkeypatch.setattr(settings, "trello_api_key", None)
    storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: storage

    response = post()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"
    assert not storage.files


def test_unknown_implementation_name_is_503(monkeypatch):
    monkeypatch.setattr(settings, "calendar_impl", "outlook")
    app.dependency_overrides[get_document_storage] = FakeDocumentStorage

    response = post()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"


# --- logging ----------------------------------------------------------------


def test_failure_log_has_no_title(caplog):
    Services(issue_failures={"create_issue": issue_error(IssueCode.ACCESS_DENIED)}).install()

    with caplog.at_level(logging.INFO):
        post({**MEETING, "title": "Secret acquisition talks"})

    assert "request_failed operation=create_meeting" in caplog.text
    assert "Secret acquisition" not in caplog.text
