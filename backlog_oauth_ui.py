"""Streamlit上のBacklog OAuthコールバック処理。"""

from pathlib import Path

import streamlit as st

from backlog_oauth import (
    exchange_code,
    fetch_identity,
    load_oauth_settings,
    parse_state,
    save_refresh_token,
)


def handle_backlog_oauth_callback(
    *, login_email: str, spreadsheet_id: str, credentials_path: Path
) -> None:
    """認可コードを更新トークンへ交換し、ログイン本人との一致を検証する。"""

    code = str(st.query_params.get("code", "")).strip()
    state = str(st.query_params.get("state", "")).strip()
    oauth_error = str(st.query_params.get("error", "")).strip()
    if not code and not oauth_error:
        return
    if oauth_error:
        st.error("Backlog連携がキャンセルされたか、認証に失敗しました。")
        st.query_params.clear()
        return
    try:
        settings = load_oauth_settings()
        parsed = parse_state(settings, state)
        if parsed["email"] != login_email.strip().lower():
            raise ValueError("Backlog連携を開始したログインユーザーと一致しません。")
        token = exchange_code(settings, parsed["space_id"], code)
        identity = fetch_identity(parsed["space_id"], token["access_token"])
        if identity.mail_address != login_email.strip().lower():
            raise ValueError(
                "フォームのログインメールとBacklog登録メールが一致しません。"
            )
        save_refresh_token(
            spreadsheet_id, credentials_path, settings, login_email,
            parsed["space_id"], identity, token["refresh_token"],
        )
        st.query_params.clear()
        st.success(f"Backlog連携が完了しました：{identity.name}")
    except Exception as error:
        st.query_params.clear()
        st.error(f"Backlog連携を完了できませんでした：{error}")
