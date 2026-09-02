"""Authentication guard for the cloud-facing Streamlit app."""

from __future__ import annotations

import os
from dataclasses import dataclass
import streamlit as st


_LOGIN_PENDING_KEY = "_auth_login_pending"


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    name: str


def _queue_auth0_login() -> None:
    """Queue one login redirect for the next Streamlit rerun."""
    st.session_state[_LOGIN_PENDING_KEY] = True


def require_authenticated_user() -> AuthenticatedUser:
    if os.getenv("APP_AUTH_BYPASS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return AuthenticatedUser(
            email=os.getenv("APP_AUTH_BYPASS_EMAIL", "local-admin@example.invalid"),
            name="ローカル管理者",
        )
    if not st.user.is_logged_in:
        st.title("ふるさと納税業務支援")
        st.write("登録済みのメールアドレスと、ご自身で設定したパスワードでログインしてください。")
        st.info(
            "ログイン画面は1つだけ開いてください。"
            "ログイン中は「戻る」・画面の更新・別タブでのログインを行わないでください。",
            icon=":material/info:",
        )

        # The callback runs at the start of the following rerun. A boolean
        # queue makes repeated clicks idempotent and starts one redirect only.
        if st.session_state.pop(_LOGIN_PENDING_KEY, False):
            with st.spinner("ログイン画面を開いています…"):
                st.login("auth0")
            st.stop()

        st.button(
            "ログインを開始（1回だけ押してください）",
            type="primary",
            icon=":material/login:",
            width="stretch",
            on_click=_queue_auth0_login,
        )
        with st.expander("ログインエラーが表示された場合"):
            st.markdown(
                "1. Auth0のエラー画面を閉じる\n"
                "2. フォームとログインの余分なタブを閉じる\n"
                "3. フォームを1タブだけで開き直す\n"
                "4. 上のログインボタンを1回だけ押す"
            )
        st.stop()
    email = str(st.user.get("email", "")).strip().lower()
    if not email:
        st.error("ログイン情報からメールアドレスを確認できませんでした。")
        st.stop()
    return AuthenticatedUser(email=email, name=str(st.user.get("name", "")).strip() or email)


def render_user_menu(user: AuthenticatedUser) -> None:
    with st.container(horizontal=True, horizontal_alignment="right"):
        st.caption(f"ログイン中：{user.email}")
        if st.button("ログアウト", icon=":material/logout:", key="cloud_logout"):
            st.logout()
