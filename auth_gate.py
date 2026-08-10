"""Authentication guard for the cloud-facing Streamlit app."""

from __future__ import annotations

import os
from dataclasses import dataclass
import streamlit as st


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    name: str


def require_authenticated_user() -> AuthenticatedUser:
    if os.getenv("APP_AUTH_BYPASS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return AuthenticatedUser(
            email=os.getenv("APP_AUTH_BYPASS_EMAIL", "local-admin@example.invalid"),
            name="ローカル管理者",
        )
    if not st.user.is_logged_in:
        st.title("ふるさと納税業務支援")
        st.write("登録済みのメールアドレスと、ご自身で設定したパスワードでログインしてください。")
        if st.button("メールアドレスでログイン", type="primary", icon=":material/login:", width="stretch"):
            st.login("auth0")
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
