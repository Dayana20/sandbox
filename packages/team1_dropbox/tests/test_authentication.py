"""Independent refresh-token configuration tests."""

from unittest.mock import Mock

import pytest
from cloud_storage_api import InvalidRequestError

from team1_dropbox import Team1DropboxStorage
from team1_dropbox.client import create_dropbox_client, create_dropbox_client_from_env


def test_explicit_credentials_create_refresh_token_client(monkeypatch) -> None:
    constructor = Mock()
    monkeypatch.setattr("team1_dropbox.client.dropbox.Dropbox", constructor)

    client = create_dropbox_client(
        app_key="team5-key",
        app_secret="team5-secret",
        refresh_token="team5-refresh",
    )

    constructor.assert_called_once_with(
        oauth2_refresh_token="team5-refresh",
        app_key="team5-key",
        app_secret="team5-secret",
    )
    assert client is constructor.return_value


def test_constructor_accepts_credentials_directly(monkeypatch) -> None:
    constructor = Mock()
    monkeypatch.setattr("team1_dropbox.client.dropbox.Dropbox", constructor)

    Team1DropboxStorage(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
    )

    constructor.assert_called_once()


def test_from_env_uses_only_caller_environment(monkeypatch) -> None:
    constructor = Mock()
    monkeypatch.setattr("team1_dropbox.client.dropbox.Dropbox", constructor)
    environ = {
        "DROPBOX_APP_KEY": "key",
        "DROPBOX_APP_SECRET": "secret",
        "DROPBOX_REFRESH_TOKEN": "refresh",
    }

    storage = Team1DropboxStorage.from_env(environ)

    assert isinstance(storage, Team1DropboxStorage)
    constructor.assert_called_once_with(
        oauth2_refresh_token="refresh",
        app_key="key",
        app_secret="secret",
    )


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"DROPBOX_APP_KEY": "key"},
        {
            "DROPBOX_APP_KEY": "key",
            "DROPBOX_APP_SECRET": "secret",
            "DROPBOX_REFRESH_TOKEN": " ",
        },
    ],
)
def test_missing_environment_credentials_fail_clearly(environ) -> None:
    with pytest.raises(InvalidRequestError, match="DROPBOX_"):
        create_dropbox_client_from_env(environ)


def test_injected_client_needs_no_environment(monkeypatch) -> None:
    constructor = Mock()
    monkeypatch.setattr("team1_dropbox.client.dropbox.Dropbox", constructor)
    injected = Mock()

    storage = Team1DropboxStorage(client=injected)
    storage.check_health()

    constructor.assert_not_called()
    injected.users_get_current_account.assert_called_once_with()


def test_client_and_credentials_are_mutually_exclusive() -> None:
    with pytest.raises(InvalidRequestError, match="either"):
        Team1DropboxStorage(client=Mock(), app_key="key")
