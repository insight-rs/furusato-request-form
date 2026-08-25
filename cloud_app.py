"""社内共有クラウド用：商品フォームと運用サマリのみを提供する。"""

from __future__ import annotations

import importlib
from pathlib import Path

import streamlit as st

from auth_gate import render_user_menu, require_authenticated_user
from backlog_oauth_ui import handle_backlog_oauth_callback
from operations_dashboard import load_request_dashboard_summary
import request_form as request_form_module
from runtime_config import CONFIG_SPREADSHEET_ID, PRODUCT_SPREADSHEET_ID, google_credentials_path


EXPECTED_REQUEST_FORM_RUNTIME_VERSION = "2026-08-25.2"
if getattr(request_form_module, "REQUEST_FORM_RUNTIME_VERSION", "") != EXPECTED_REQUEST_FORM_RUNTIME_VERSION:
    request_form_module = importlib.reload(request_form_module)
render_backlog_status_sync = request_form_module.render_backlog_status_sync
render_product_request_tab = request_form_module.render_product_request_tab


credentials_path = google_credentials_path()
st.set_page_config(page_title="ふるさと納税業務支援", page_icon="📋", layout="centered")
st.markdown(
    """
    <style>
    /* 再実行中も入力画面を薄くしすぎず、エラー表示のように見せない。 */
    .stApp [data-stale="true"] {
        opacity: 0.92 !important;
        transition: opacity 80ms ease-in !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
current_user = require_authenticated_user()
handle_backlog_oauth_callback(
    login_email=current_user.email,
    spreadsheet_id=CONFIG_SPREADSHEET_ID,
    credentials_path=credentials_path,
)
render_user_menu(current_user)

st.title("ふるさと納税業務支援")
st.caption("商品登録・修正依頼と運用状況を、共有マスタで一元管理します。")

manual_path = Path(__file__).parent / "assets" / "ふるさと納税フォーム_操作マニュアル.pptx"
if manual_path.exists():
    with st.container(border=True):
        manual_column, download_column = st.columns([3, 2], vertical_alignment="center")
        manual_column.markdown(
            "**はじめに：操作マニュアル（最新版）**  \n"
            "入力方法、Backlog連携、管理スプレッドシートの運用を画面図解付きで確認できます。"
        )
        download_column.download_button(
            "📘 最新版マニュアルをダウンロード",
            data=manual_path.read_bytes(),
            file_name="ふるさと納税業務支援_運用マニュアル_最新版.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            width="stretch",
            type="primary",
        )

current_view = st.segmented_control(
    "画面", ["商品登録・修正依頼", "運用サマリ"],
    default="商品登録・修正依頼", required=True, key="cloud_app_view", width="stretch",
)
if current_view == "商品登録・修正依頼":
    render_backlog_status_sync(
        config_spreadsheet_id=CONFIG_SPREADSHEET_ID,
        product_spreadsheet_id=PRODUCT_SPREADSHEET_ID,
        credentials_path=credentials_path,
    )
    render_product_request_tab(
        config_spreadsheet_id=CONFIG_SPREADSHEET_ID,
        product_spreadsheet_id=PRODUCT_SPREADSHEET_ID,
        credentials_path=credentials_path,
        login_email=current_user.email,
    )
else:
    try:
        summary = load_request_dashboard_summary(
            spreadsheet_id=PRODUCT_SPREADSHEET_ID, credentials_path=credentials_path
        )
        st.subheader("運用サマリ")
        total_column, backlog_column, image_column = st.columns(3)
        total_column.metric("商品修正依頼", f"{summary.total_requests}件")
        backlog_column.metric("Backlog連携済", f"{summary.backlog_linked_requests}件")
        image_column.metric("画像作業あり", f"{summary.image_work_requests}件")
        if not summary.total_requests:
            st.info("商品修正依頼はまだありません。")
        else:
            st.dataframe(
                [{"状態": status, "件数": count} for status, count in summary.status_rows],
                hide_index=True, width="stretch",
            )
    except Exception as error:
        st.error("運用サマリを読み込めませんでした。")
        st.exception(error)

