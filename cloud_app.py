"""社内共有クラウド用：商品フォームと運用サマリのみを提供する。"""

from __future__ import annotations

import streamlit as st

from auth_gate import render_user_menu, require_authenticated_user
from operations_dashboard import load_request_dashboard_summary
from request_form import render_backlog_status_sync, render_product_request_tab
from runtime_config import (
    CONFIG_SPREADSHEET_ID,
    PRODUCT_SPREADSHEET_ID,
    google_credentials_path,
)


credentials_path = google_credentials_path()

st.set_page_config(
    page_title="ふるさと納税業務支援",
    page_icon="📋",
    layout="centered",
)

current_user = require_authenticated_user()
render_user_menu(current_user)

st.title("ふるさと納税業務支援")
st.caption("商品登録・修正依頼と運用状況を、共有マスタで一元管理します。")

current_view = st.segmented_control(
    "画面",
    ["商品登録・修正依頼", "運用サマリ"],
    default="商品登録・修正依頼",
    required=True,
    key="cloud_app_view",
    width="stretch",
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
    )
else:
    try:
        summary = load_request_dashboard_summary(
            spreadsheet_id=PRODUCT_SPREADSHEET_ID,
            credentials_path=credentials_path,
        )
        st.subheader("運用サマリ")
        total_column, backlog_column, image_column = st.columns(3)
        total_column.metric("商品修正依頼", f"{summary.total_requests}件")
        backlog_column.metric(
            "Backlog連携済", f"{summary.backlog_linked_requests}件"
        )
        image_column.metric("画像作業あり", f"{summary.image_work_requests}件")
        if not summary.total_requests:
            st.info("商品修正依頼はまだありません。")
        else:
            status_column, municipality_column = st.columns(2)
            with status_column:
                st.write("状態別")
                st.dataframe(
                    [
                        {"状態": status, "件数": count}
                        for status, count in summary.status_rows
                    ],
                    hide_index=True,
                    width="stretch",
                )
            with municipality_column:
                st.write("自治体別")
                st.dataframe(
                    [
                        {"自治体": municipality, "件数": count}
                        for municipality, count in summary.municipality_rows
                    ],
                    hide_index=True,
                    width="stretch",
                )
    except Exception as error:
        st.error("運用サマリを読み込めませんでした。")
        st.exception(error)
