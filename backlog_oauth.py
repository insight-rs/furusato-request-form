"""Backlog OAuth連携と、暗号化した更新トークンの保管。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Callable
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
import gspread
import requests

from backlog_client import BacklogApiError, backlog_base_url
from config_master import ConfigError, normalize


TOKEN_SHEET_NAME = "Backlog OAuth連携"
TOKEN_HEADERS = [
    "ログインメールアドレス", "BacklogスペースID", "BacklogユーザーID",
    "Backlog登録メールアドレス", "暗号化更新トークン", "連携日時", "更新日時",
]


@dataclass(frozen=True)
class BacklogOAuthSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    state_secret: str
    token_encryption_key: str

    @property
    def configured(self) -> bool:
        return all((
            self.client_id, self.client_secret, self.redirect_uri,
            self.state_secret, self.token_encryption_key,
        ))


@dataclass(frozen=True)
class BacklogOAuthIdentity:
    user_id: str
    name: str
    mail_address: str


def load_oauth_settings() -> BacklogOAuthSettings:
    """環境変数またはStreamlit SecretsからOAuth設定を取得する。"""

    def read(name: str) -> str:
        value = normalize(os.environ.get(name))
        if value:
            return value
        try:
            import streamlit as st
            return normalize(st.secrets.get(name, ""))
        except Exception:
            return ""

    return BacklogOAuthSettings(
        client_id=read("BACKLOG_OAUTH_CLIENT_ID"),
        client_secret=read("BACKLOG_OAUTH_CLIENT_SECRET"),
        redirect_uri=read("BACKLOG_OAUTH_REDIRECT_URI"),
        state_secret=read("BACKLOG_OAUTH_STATE_SECRET"),
        token_encryption_key=read("BACKLOG_OAUTH_TOKEN_KEY"),
    )


def create_state(settings: BacklogOAuthSettings, email: str, space_id: str) -> str:
    """改ざん検知できる短期OAuth stateを生成する。"""

    payload = {
        "email": normalize(email).lower(),
        "space_id": normalize(space_id),
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64(signature)}"


def parse_state(
    settings: BacklogOAuthSettings, state: str, max_age_minutes: int = 15
) -> dict[str, str]:
    """OAuth stateを検証し、ログインメールとスペースIDを返す。"""

    try:
        encoded, supplied_signature = state.split(".", 1)
        expected = hmac.new(
            settings.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_unb64(supplied_signature), expected):
            raise ValueError
        payload = json.loads(_unb64(encoded).decode("utf-8"))
        issued_at = datetime.fromtimestamp(int(payload["issued_at"]), timezone.utc)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ConfigError("Backlog連携情報を確認できませんでした。もう一度連携してください。") from error
    if datetime.now(timezone.utc) - issued_at > timedelta(minutes=max_age_minutes):
        raise ConfigError("Backlog連携の有効時間が切れました。もう一度連携してください。")
    return {
        "email": normalize(payload.get("email")).lower(),
        "space_id": normalize(payload.get("space_id")),
    }


def authorization_url(
    settings: BacklogOAuthSettings, space_id: str, login_email: str
) -> str:
    if not settings.configured:
        raise ConfigError("Backlog OAuth設定が未登録です。")
    query = urlencode({
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "state": create_state(settings, login_email, space_id),
    })
    return f"{backlog_base_url(space_id)}/OAuth2AccessRequest.action?{query}"


def exchange_code(
    settings: BacklogOAuthSettings, space_id: str, code: str,
    post: Callable = requests.post,
) -> dict:
    response = post(
        f"{backlog_base_url(space_id)}/api/v2/oauth2/token",
        data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": settings.redirect_uri, "client_id": settings.client_id,
            "client_secret": settings.client_secret,
        },
        timeout=30,
    )
    return _token_response(response)


def refresh_access_token(
    settings: BacklogOAuthSettings, space_id: str, refresh_token: str,
    post: Callable = requests.post,
) -> dict:
    response = post(
        f"{backlog_base_url(space_id)}/api/v2/oauth2/token",
        data={
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": settings.client_id, "client_secret": settings.client_secret,
        },
        timeout=30,
    )
    return _token_response(response)


def fetch_identity(
    space_id: str, access_token: str, get: Callable = requests.get
) -> BacklogOAuthIdentity:
    response = get(
        f"{backlog_base_url(space_id)}/api/v2/users/myself",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=30,
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise BacklogApiError("Backlogのログインユーザーを確認できませんでした。")
    payload = response.json()
    return BacklogOAuthIdentity(
        user_id=normalize(payload.get("id")), name=normalize(payload.get("name")),
        mail_address=normalize(payload.get("mailAddress")).lower(),
    )


def save_refresh_token(
    spreadsheet_id: str, credentials_path: Path, settings: BacklogOAuthSettings,
    login_email: str, space_id: str, identity: BacklogOAuthIdentity,
    refresh_token: str, client_factory: Callable | None = None,
) -> None:
    worksheet = _token_worksheet(spreadsheet_id, credentials_path, client_factory)
    values = worksheet.get_all_values()
    rows = values[1:] if values else []
    login_email = normalize(login_email).lower()
    space_id = normalize(space_id)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    encrypted = Fernet(settings.token_encryption_key.encode("ascii")).encrypt(
        refresh_token.encode("utf-8")
    ).decode("ascii")
    new_row = [login_email, space_id, identity.user_id, identity.mail_address, encrypted, now, now]
    for index, row in enumerate(rows, start=2):
        padded = row + [""] * (len(TOKEN_HEADERS) - len(row))
        if normalize(padded[0]).lower() == login_email and normalize(padded[1]) == space_id:
            new_row[5] = padded[5] or now
            worksheet.update(f"A{index}:G{index}", [new_row], value_input_option="RAW")
            return
    worksheet.append_row(new_row, value_input_option="RAW")


def load_refresh_token(
    spreadsheet_id: str, credentials_path: Path, settings: BacklogOAuthSettings,
    login_email: str, space_id: str, client_factory: Callable | None = None,
) -> str:
    worksheet = _token_worksheet(spreadsheet_id, credentials_path, client_factory)
    for row in worksheet.get_all_records():
        if (
            normalize(row.get("ログインメールアドレス")).lower() == normalize(login_email).lower()
            and normalize(row.get("BacklogスペースID")) == normalize(space_id)
        ):
            try:
                return Fernet(settings.token_encryption_key.encode("ascii")).decrypt(
                    normalize(row.get("暗号化更新トークン")).encode("ascii")
                ).decode("utf-8")
            except (InvalidToken, ValueError) as error:
                raise ConfigError("Backlog連携情報を復号できません。管理者へご連絡ください。") from error
    return ""


def access_token_for_user(
    spreadsheet_id: str, credentials_path: Path, settings: BacklogOAuthSettings,
    login_email: str, space_id: str,
) -> str:
    refresh_token = load_refresh_token(
        spreadsheet_id, credentials_path, settings, login_email, space_id
    )
    if not refresh_token:
        return ""
    token = refresh_access_token(settings, space_id, refresh_token)
    identity = fetch_identity(space_id, token["access_token"])
    if identity.mail_address != normalize(login_email).lower():
        raise ConfigError("フォームとBacklogの登録メールアドレスが一致しません。")
    save_refresh_token(
        spreadsheet_id, credentials_path, settings, login_email, space_id,
        identity, token.get("refresh_token") or refresh_token,
    )
    return token["access_token"]


def _token_worksheet(spreadsheet_id, credentials_path, client_factory):
    factory = client_factory or gspread.service_account
    spreadsheet = factory(filename=str(credentials_path)).open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(TOKEN_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(TOKEN_SHEET_NAME, rows=200, cols=len(TOKEN_HEADERS))
        worksheet.update("A1:G1", [TOKEN_HEADERS], value_input_option="RAW")
    return worksheet


def _token_response(response) -> dict:
    if response.status_code < 200 or response.status_code >= 300:
        raise BacklogApiError("Backlog OAuth認証に失敗しました。もう一度連携してください。")
    payload = response.json()
    if not normalize(payload.get("access_token")) or not normalize(payload.get("refresh_token")):
        raise BacklogApiError("Backlog OAuthトークンを取得できませんでした。")
    return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
