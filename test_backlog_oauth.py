from backlog_oauth import (
    BacklogOAuthSettings,
    authorization_url,
    create_state,
    parse_state,
)
from backlog_users import BacklogProjectUser, find_user_by_login_email
from backlog_client import create_issue
from backlog_config import BacklogConfig


def settings():
    return BacklogOAuthSettings(
        client_id="client", client_secret="secret",
        redirect_uri="https://example.streamlit.app/",
        state_secret="state-secret", token_encryption_key="unused-in-state-tests",
    )


def test_oauth_state_keeps_verified_email_and_space():
    state = create_state(settings(), "USER@EXAMPLE.JP", "sample")
    assert parse_state(settings(), state) == {
        "email": "user@example.jp", "space_id": "sample"
    }


def test_authorization_url_targets_the_municipality_space():
    url = authorization_url(settings(), "sample", "user@example.jp")
    assert url.startswith("https://sample.backlog.com/OAuth2AccessRequest.action?")
    assert "client_id=client" in url
    assert "state=" in url


def test_login_email_resolves_backlog_user_for_selected_municipality():
    users = [
        BacklogProjectUser(
            municipality_id="m1", municipality_name="自治体", project_id="P",
            user_id="10", name="担当者", mail_address="backlog@example.jp",
            login_address="login@example.jp",
        )
    ]
    matched = find_user_by_login_email(users, "m1", "LOGIN@example.jp")
    assert matched is not None
    assert matched.user_id == "10"


def test_issue_creation_with_oauth_does_not_put_api_key_in_url():
    config = BacklogConfig(
        municipality_id="m1", municipality_name="自治体", team_name="",
        space_id="sample", project_id="123", api_key="must-not-leak",
        api_key_storage_key="", image_child_issue_type="",
        product_correction_issue_type="", note="",
    )
    calls = []

    def sender(method, url, data):
        calls.append((method, url, data))
        return 201, b'{"id":1,"issueKey":"P-1"}'

    issue = create_issue(
        config, "2", "件名", "詳細", request_sender=sender,
        access_token="oauth-access-token",
    )
    assert issue.issue_key == "P-1"
    assert calls[0][1] == "https://sample.backlog.com/api/v2/issues"
    assert "must-not-leak" not in calls[0][1]
