from unittest.mock import Mock

import pytest
from issue_tracker_contract import ErrorCode, Issue, IssueUpdate, ServiceError

from app.core.config import settings
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    StorageNotConfiguredError,
)
from app.integrations.issue_tracker import (
    InMemoryIssueProvider,
    _MappedIssueProvider,
    get_issue_provider,
)


def test_factory_returns_fake_by_default(monkeypatch):
    monkeypatch.setattr(settings, "tracker_impl", "fake")

    provider = get_issue_provider()
    issue = provider.create_issue("Issue tracker fake")

    assert provider.get_issue(issue.id) == issue


def test_factory_selects_team4_provider(monkeypatch):
    implementation = InMemoryIssueProvider()
    create_provider = Mock(return_value=implementation)
    monkeypatch.setattr(settings, "tracker_impl", "team4")
    monkeypatch.setattr(settings, "trello_api_key", "test-key")
    monkeypatch.setattr(settings, "trello_token", "test-token")
    monkeypatch.setattr(settings, "trello_list_id", "test-list")
    monkeypatch.setattr(
        "app.integrations.issue_tracker.TrelloIssueProvider",
        create_provider,
    )

    provider = get_issue_provider()

    create_provider.assert_called_once_with()
    assert provider.create_issue("Issue tracker fake").title == "Issue tracker fake"


def test_factory_rejects_unknown_implementation(monkeypatch):
    monkeypatch.setattr(settings, "tracker_impl", "unknown")

    with pytest.raises(StorageNotConfiguredError, match="TRACKER_IMPL"):
        get_issue_provider()


@pytest.mark.parametrize(
    ("setting_name", "setting_value"),
    [
        ("trello_api_key", None),
        ("trello_token", None),
        ("trello_list_id", None),
        ("trello_api_key", " "),
    ],
)
def test_factory_requires_all_trello_settings(
    monkeypatch,
    setting_name,
    setting_value,
):
    monkeypatch.setattr(settings, "tracker_impl", "team4")
    monkeypatch.setattr(settings, "trello_api_key", "test-key")
    monkeypatch.setattr(settings, "trello_token", "test-token")
    monkeypatch.setattr(settings, "trello_list_id", "test-list")
    monkeypatch.setattr(settings, setting_name, setting_value)

    with pytest.raises(StorageNotConfiguredError, match=setting_name.upper()):
        get_issue_provider()


@pytest.mark.parametrize(
    ("error_code", "application_error"),
    [
        (ErrorCode.INVALID_INPUT, InvalidRequestError),
        (ErrorCode.NOT_FOUND, FileNotFoundError),
        (ErrorCode.ACCESS_DENIED, PermissionDeniedError),
        (ErrorCode.SERVICE_NOT_CONFIGURED, StorageNotConfiguredError),
        (ErrorCode.PRECONDITION_FAILED, FileConflictError),
        (ErrorCode.PROVIDER_ERROR, ProviderError),
        (ErrorCode.INTERNAL_ERROR, ProviderError),
        (ErrorCode.IDEMPOTENCY_KEY_REUSED, InvalidRequestError),
        (ErrorCode.REQUEST_IN_PROGRESS, FileConflictError),
    ],
)
def test_contract_errors_map_to_application_errors(error_code, application_error):
    failure = ServiceError(
        error_code,
        "Issue contract failure.",
        provider_involved=True,
    )
    provider = InMemoryIssueProvider(failures={"get_issue": failure})
    mapped_provider = _MappedIssueProvider(provider)

    with pytest.raises(
        application_error,
        match="Issue tracker get_issue failed",
    ) as exc_info:
        mapped_provider.get_issue("test-issue")

    assert exc_info.value.__cause__ is failure


def test_unexpected_error_maps_to_provider_error_with_step_name():
    failure = RuntimeError("provider detail")
    provider = InMemoryIssueProvider(failures={"create_issue": failure})
    mapped_provider = _MappedIssueProvider(provider)

    with pytest.raises(
        ProviderError,
        match="Issue tracker create_issue failed",
    ) as exc_info:
        mapped_provider.create_issue("Issue tracker fake")

    assert exc_info.value.__cause__ is failure
    assert str(exc_info.value) == "Issue tracker create_issue failed"


def test_fake_supports_update_list_and_delete():
    provider = InMemoryIssueProvider()
    created = provider.create_issue("Original issue")

    updated = provider.update_issue(
        created.id,
        IssueUpdate(title="Updated issue"),
    )

    assert updated == Issue(id=created.id, title="Updated issue")
    assert provider.list_issues(limit=10) == [updated]
    provider.delete_issue(updated.id)

    with pytest.raises(ServiceError) as exc_info:
        provider.get_issue(updated.id)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
