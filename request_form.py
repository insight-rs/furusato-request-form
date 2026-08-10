"""商品修正依頼タブの画面と、Backlog・商品情報マスタへの保存をまとめる。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
import os
import re
from uuid import uuid4

import pandas as pd
import streamlit as st

from choice_reference import load_choice_categories, load_local_product_standards

from backlog_client import attach_file_to_issue, create_issue, update_issue
from backlog_config import backlog_configs_by_municipality_id, load_backlog_configs
from backlog_custom_fields import (
    build_custom_field_parameters,
    get_applicable_custom_fields,
    load_backlog_custom_fields,
)
from backlog_issue_types import load_backlog_issue_types
from backlog_statuses import load_backlog_statuses
from backlog_users import (
    fetch_backlog_project_teams,
    get_project_users,
    load_backlog_project_users,
)
from form_definitions import (
    RequestFormField,
    find_request_form_field,
    load_request_form_fields,
    selectable_request_form_fields,
)
from policy_master import (
    find_policy_entry,
    load_policy_entries,
    policy_contents,
    policy_types,
)
from product_request_status_sync import sync_product_request_statuses
from product_requests import (
    ProductCorrectionLine,
    ProductReference,
    build_backlog_issue_content,
    build_image_backlog_issue_content,
    create_product_correction_request,
    load_product_references,
    load_saved_product_correction_request,
    save_product_correction_request,
    update_image_request_backlog_child,
    update_product_request_backlog_parent,
)
from revision_export import generate_revision_comparison_workbook
from registration_excel import (
    NOULESS_REFERENCE_FIELDS,
    PRODUCT_SHAPES,
    build_registration_template,
    read_registration_template,
)


REQUEST_UNITS = ("商品単位", "自治体対応", "その他")
WORK_CATEGORIES = ("一般業務", "新規商品登録", "施策", "その他")
DONATION_COLUMN = "（条件付き必須）必要寄付金額"
POINTS_COLUMN = "（条件付き必須）ポイント"
WASTE_FLAG_COLUMN = "（必須）地域の生産者応援の品（訳ありの品）"
WASTE_BRANCH_COLUMNS = (
    "規格外になった理由",
    "（条件付き必須）訳ありの理由",
    "（条件付き必須）訳あり品についての補足テキスト",
)
ALLERGY_PREFIX = "アレルギー："
ALLERGY_NOTE_COLUMN = "アレルギー特記事項"
TOP_FIELD_COLUMNS = ("管理コード",)
TEMPERATURE_COLUMNS = {
    "常温": "（必須）常温配送",
    "冷蔵": "（必須）冷蔵配送",
    "冷凍": "（必須）冷凍配送",
}
TEMPERATURE_CHANGE_OPTION = "温度帯"
ALLERGY_CHANGE_OPTION = "アレルギー情報"
NEW_PRODUCT_REQUIRED_COLUMNS = {
    "管理コード",
    "（必須）お礼の品名", "（必須）発送期日種別", "（必須）カテゴリー",
    "（必須）定期配送対応", "（必須）別送対応", "（必須）包装対応",
    "（必須）のし対応", "（必須）ポイント情報表示有無", "（必須）会員限定",
    "（必須）チョイス限定", "（必須）オンライン決済限定",
    "（必須）配送状況確認可能", "（必須）地域の生産者応援の品（訳ありの品）",
    "（必須）配送業者", "（必須）配達日種別", "（必須）配達日種別必須フラグ",
    "（必須）配達時間指定", "（必須）配達時間指定必須フラグ",
    "（必須）表示有無", "（必須）還元率入力有無",
}
NEW_PRODUCT_AUTO_COLUMNS = {"お礼の品ID", "オリジナルお礼の品ID", "事業者ID"}
NEW_PRODUCT_MEDIA_KEYWORDS = ("画像", "YouTube", "動画")
UPLOAD_DIRECTORY = Path(
    os.environ.get("REQUEST_UPLOAD_DIRECTORY", r"C:\tsv_auto\exports\依頼添付")
)
SHIPPING_DEADLINE_TYPE_COLUMN = "（必須）発送期日種別"
SHIPPING_DEADLINE_COLUMN = "発送期日"
LOCAL_PRODUCT_TYPE_COLUMN = "地場産品類型"
CATEGORY_COLUMN = "（必須）カテゴリー"
PRODUCT_NAME_COLUMN = "（必須）お礼の品名"
MANAGEMENT_CODE_COLUMN = "管理コード"
LINK_CODE_COLUMN = "連携コード"
HIDDEN_FORM_COLUMNS = {
    "お礼の品に関するお問い合わせ先",
    "（必須）包装対応", "（必須）のし対応", "（必須）ポイント情報表示有無",
    "（必須）会員限定", "（必須）チョイス限定", "（必須）配送状況確認可能",
    "（必須）配達日種別", "（必須）配達日種別必須フラグ",
    "（必須）配達時間指定", "（必須）配達時間指定必須フラグ",
    "配達日FROM", "配達日TO", "配達日数指定FROM", "配達日数指定TO",
    "配達不可能な日付", "配達不可能な曜日", "親お礼の品ID",
    "（条件付き必須）バリエーション名", LINK_CODE_COLUMN,
    "（条件付き必須）還元率（%）", "（必須）還元率入力有無", "登録年度", "メモ",
}
STATIC_FIXED_VALUES = {
    "（必須）別送対応": "1",
    "（必須）包装対応": "0",
    "（必須）のし対応": "0",
    "（必須）ポイント情報表示有無": "1",
    "（必須）会員限定": "0",
    "（必須）チョイス限定": "0",
    "（必須）配送状況確認可能": "0",
    "（必須）配達日種別": "0",
    "（必須）配達日種別必須フラグ": "0",
    "（必須）配達時間指定": "1",
    "（必須）配達時間指定必須フラグ": "1",
    "配達日FROM": "", "配達日TO": "", "配達日数指定FROM": "", "配達日数指定TO": "",
    "配達不可能な日付": "", "配達不可能な曜日": "",
    "親お礼の品ID": "", "（条件付き必須）バリエーション名": "",
    "（必須）還元率入力有無": "0", "（条件付き必須）還元率（%）": "", "メモ": "",
}
CORRECTION_TYPES = (
    "複合的な修正",
    "寄附額変更",
    "在庫数変更",
    "表示・非表示切り替え",
    "商品名・キャッチコピー修正",
    "発送期日・納期・受付期間修正",
    "商品説明文・容量変更",
)
CORRECTION_TYPE_COLUMNS = {
    "寄附額変更": {DONATION_COLUMN},
    "在庫数変更": set(),
    "表示・非表示切り替え": {"（必須）表示有無"},
    "商品名・キャッチコピー修正": {PRODUCT_NAME_COLUMN, "キャッチコピー"},
    "発送期日・納期・受付期間修正": {
        SHIPPING_DEADLINE_TYPE_COLUMN, SHIPPING_DEADLINE_COLUMN,
        "申込期日", "受付開始日時", "受付終了日時",
    },
    "商品説明文・容量変更": {"説明", "容量"},
}
BACKLOG_ONLY_PREFIX = "【Backlogのみ】"


@st.cache_data(ttl=600, max_entries=2)
def _load_products(product_spreadsheet_id: str, credentials_path_text: str):
    return load_product_references(
        spreadsheet_id=product_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=2)
def _load_form_fields(config_spreadsheet_id: str, credentials_path_text: str):
    return load_request_form_fields(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=2)
def _load_policies(config_spreadsheet_id: str, credentials_path_text: str):
    return load_policy_entries(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=2)
def _load_backlog_configs(config_spreadsheet_id: str, credentials_path_text: str):
    return load_backlog_configs(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=2)
def _load_backlog_issue_types(config_spreadsheet_id: str, credentials_path_text: str):
    return load_backlog_issue_types(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=2)
def _load_backlog_users(config_spreadsheet_id: str, credentials_path_text: str):
    return load_backlog_project_users(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=600, max_entries=20)
def _load_backlog_teams(config):
    return fetch_backlog_project_teams(config)


@st.cache_data(ttl=600, max_entries=2)
def _load_backlog_custom_fields(config_spreadsheet_id: str, credentials_path_text: str):
    return load_backlog_custom_fields(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


@st.cache_data(ttl=90, max_entries=2)
def _load_backlog_status_values(config_spreadsheet_id: str, credentials_path_text: str):
    return load_backlog_statuses(
        spreadsheet_id=config_spreadsheet_id,
        credentials_path=Path(credentials_path_text),
    )


def _product_label(product) -> str:
    management_code = product.source_values().get("管理コード", "")
    labels = [value for value in (management_code, product.product_name, product.business_name) if value]
    return " | ".join(labels) or "商品名未設定"


def _set_policy_issue_type_default(
    *, key: str, context_key: str, preferred_name: str, available_names: list[str]
) -> None:
    """施策の選択が変わった時だけ、推奨種別を初期値にする。"""

    previous_context = st.session_state.get(f"{key}_context")
    if previous_context == context_key:
        return
    if preferred_name in available_names:
        st.session_state[key] = preferred_name
    elif st.session_state.get(key) not in available_names:
        st.session_state.pop(key, None)
    st.session_state[f"{key}_context"] = context_key


def _is_allergy_item_field(field: RequestFormField) -> bool:
    return field.source_column.startswith(ALLERGY_PREFIX)


def _sort_change_fields(fields: list[RequestFormField]) -> list[RequestFormField]:
    """品番・公開状態を先頭に固定し、アレルギーは専用入力へ分離する。"""

    priority = {column: index for index, column in enumerate(TOP_FIELD_COLUMNS)}
    section_order = {
        "基本情報": 0,
        "商品詳細": 1,
        "配送情報": 2,
        "配達指定": 3,
        "公開・受付設定": 4,
        "管理情報": 5,
    }
    return sorted(
        [
            field for field in fields
            if not _is_allergy_item_field(field)
            and field.source_column != ALLERGY_NOTE_COLUMN
            and field.source_column not in TEMPERATURE_COLUMNS.values()
        ],
        key=lambda field: (
            priority.get(field.source_column, len(priority)),
            section_order.get(_field_section(field), 99),
            field.display_order,
            field.label,
        ),
    )


def _field_visibility(field: RequestFormField, *, is_new_product: bool) -> str:
    if is_new_product:
        return field.new_product_visibility or "対象項目選択肢"
    return field.correction_visibility or field.visibility


def _visible_form_fields(
    fields: list[RequestFormField], *, is_new_product: bool
) -> list[RequestFormField]:
    return [
        field for field in fields
        if field.input_kind != "ファイル"
        and field.source_column not in HIDDEN_FORM_COLUMNS
        and field.source_column != POINTS_COLUMN
        and _field_visibility(field, is_new_product=is_new_product) != "非表示"
        and (
            not is_new_product
            or (
                field.source_column not in NEW_PRODUCT_AUTO_COLUMNS
                and not any(
                    keyword in field.source_column
                    for keyword in NEW_PRODUCT_MEDIA_KEYWORDS
                )
            )
        )
    ]


def _fixed_value_for_column(column: str, management_code: str = "") -> str | None:
    if column == LINK_CODE_COLUMN:
        return management_code
    if column == "登録年度":
        return str(date.today().year)
    return STATIC_FIXED_VALUES.get(column)


def _system_fixed_fields(form_fields: list[RequestFormField]) -> list[RequestFormField]:
    return [
        field for field in form_fields
        if field.source_column in HIDDEN_FORM_COLUMNS
        and (field.source_column in STATIC_FIXED_VALUES or field.source_column in {LINK_CODE_COLUMN, "登録年度"})
    ]


def _field_section(field: RequestFormField) -> str:
    column = field.source_column
    if column in {"管理コード", "（必須）お礼の品名", "サイト表示事業者名"}:
        return "基本情報"
    if column.startswith("アレルギー：") or column == ALLERGY_NOTE_COLUMN:
        return "アレルギー情報"
    if (
        column in TEMPERATURE_COLUMNS.values()
        or "配送" in column or "発送" in column
        or column in {"（必須）定期配送対応", "（必須）別送対応", "（必須）包装対応", "（必須）のし対応"}
    ):
        return "配送情報"
    if column.startswith("配達") or column == "配送不可地域":
        return "配達指定"
    if column in {"（必須）表示有無", "受付開始日時", "受付終了日時"}:
        return "公開・受付設定"
    if column in {"管理コード", "連携コード", "登録年度", "メモ"} or "還元率" in column:
        return "管理情報"
    return "商品詳細"


def _display_field_value(field: RequestFormField, value: object) -> str:
    """保存コードを、フォーム用の日本語表示へ戻す。"""

    text = str(value or "").strip()
    if not text:
        return "（未設定）"
    if field.source_column == CATEGORY_COLUMN:
        by_id = {
            row.category_id: " ＞ ".join(
                part for part in (row.major, row.middle, row.minor) if part
            )
            for row in load_choice_categories()
        }
        return " / ".join(by_id.get(part.strip(), part.strip()) for part in text.split("|"))
    if field.source_column == LOCAL_PRODUCT_TYPE_COLUMN:
        code, separator, reason = text.partition("|")
        return f"{code}（{reason}）" if separator and reason else code
    labels_by_code = {code: label for label, code in field.options()}
    if "," in text:
        return "、".join(
            labels_by_code.get(part.strip(), part.strip())
            for part in text.split(",")
        )
    return labels_by_code.get(text, text)


def _editor_column_name(field: RequestFormField, suffix: str) -> str:
    return f"{field.field_id}__{suffix}"


def _parse_date_value(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _normalize_editor_value(field: RequestFormField, value: object) -> str:
    if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
        return ""
    if field.input_kind == "日付":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        parsed = _parse_date_value(value)
        return parsed.isoformat() if parsed else ""
    text = str(value).strip()
    if field.input_kind == "選択":
        return dict(field.options()).get(text, text)
    return text


def _table_text(value: object) -> str:
    """data_editor の空セル（None/NaN）を文字列 "nan" にしない。"""

    if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
        return ""
    return str(value).strip()


def _is_nonnegative_integer(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", str(value or "").strip()))


def _build_management_code_lines(product, new_code: str) -> list[ProductCorrectionLine]:
    """品番変更に伴う管理コード・連携コード・商品名をまとめて更新する。"""

    source_values = product.source_values()
    old_code = source_values.get(MANAGEMENT_CODE_COLUMN, "")
    lines = [
        ProductCorrectionLine(
            product=product,
            field_name=field_name,
            before_value=source_values.get(field_name, ""),
            after_value=new_code,
            display_name=display_name,
            column_number=product.source_column_number(field_name),
        )
        for field_name, display_name in (
            (MANAGEMENT_CODE_COLUMN, "品番"),
            (LINK_CODE_COLUMN, "連携コード"),
        )
    ]
    base_name = product.product_name
    if old_code and base_name.endswith(f" {old_code}"):
        base_name = base_name[: -(len(old_code) + 1)]
    revised_name = f"{base_name} {new_code}".strip()
    if revised_name != product.product_name:
        lines.append(ProductCorrectionLine(
            product=product,
            field_name=PRODUCT_NAME_COLUMN,
            before_value=product.product_name,
            after_value=revised_name,
            display_name="商品名",
            column_number=product.source_column_number(PRODUCT_NAME_COLUMN),
        ))
    return lines


def _build_product_code_request_line(product) -> ProductCorrectionLine:
    """既存品番を残し、新品番欄は作業者向けの取得指示として表示する。"""
    current_code = product.source_values().get(MANAGEMENT_CODE_COLUMN, "")
    return ProductCorrectionLine(
        product=product,
        field_name=f"{BACKLOG_ONLY_PREFIX}品番取得依頼",
        before_value=current_code,
        after_value="（空欄：品番を取得してください）",
        display_name="品番",
    )


def _field_column_config(field: RequestFormField):
    if field.input_kind == "選択" and field.options():
        return st.column_config.SelectboxColumn(
            f"{field.label}（変更後）",
            options=[""] + [label for label, _ in field.options()],
        )
    if field.input_kind == "日付":
        return st.column_config.DateColumn(
            f"{field.label}（変更後）",
            format="YYYY-MM-DD",
        )
    return st.column_config.TextColumn(f"{field.label}（変更後）")


def _render_product_change_editor(
    products: list,
    fields: list[RequestFormField],
    *,
    editor_key: str,
    initial_values: dict[str, str] | None = None,
) -> pd.DataFrame:
    """商品ごとに、現在値を上・変更後値を下にして入力を受ける。"""

    edited_rows = []
    initial_values = initial_values or {}
    for product_index, product in enumerate(products):
        source_values = product.source_values()
        management_code = source_values.get("管理コード", "") or product.product_id
        with st.container(border=True):
            st.markdown(f"#### 品番：{management_code}")
            st.write(f"商品名：{product.product_name or '未設定'}")
            if product.product_id:
                st.caption("現在値")
                st.dataframe(
                    [
                        {
                            "項目": field.label,
                            "現在値": _display_field_value(
                                field, source_values.get(field.source_column, "")
                            ),
                        }
                        for field in fields
                        if field.source_column not in HIDDEN_FORM_COLUMNS
                    ],
                    hide_index=True,
                    key=f"{editor_key}_before_{product_index}",
                )
                st.caption("変更後値")
            after_by_field = {}
            previous_section = ""
            for field in fields:
                if field.source_column in HIDDEN_FORM_COLUMNS:
                    continue
                if field.source_column in WASTE_BRANCH_COLUMNS:
                    waste_field = find_request_form_field(fields, WASTE_FLAG_COLUMN)
                    waste_value = after_by_field.get(waste_field.field_id, "") if waste_field else ""
                    if waste_value not in {"1", "適用する", "あり", "する"}:
                        continue
                if field.source_column == SHIPPING_DEADLINE_COLUMN:
                    deadline_type = find_request_form_field(fields, SHIPPING_DEADLINE_TYPE_COLUMN)
                    deadline_value = after_by_field.get(deadline_type.field_id, "") if deadline_type else ""
                    if deadline_value not in {"0", "任意入力"}:
                        continue
                section = _field_section(field)
                if section != previous_section:
                    st.markdown(f"##### {section}")
                    previous_section = section
                field_key = f"{editor_key}_{product_index}_{field.field_id}"
                initial_value = initial_values.get(field.source_column, "")
                if field.source_column == LOCAL_PRODUCT_TYPE_COLUMN:
                    standards = load_local_product_standards()
                    labels = [f"{code}｜{description}" for code, description in standards]
                    initial_code, _, initial_reason = initial_value.partition("|")
                    initial_label = next(
                        (label for label in labels if label.startswith(f"{initial_code}｜")),
                        "",
                    )
                    st.session_state.setdefault(f"{field_key}_type", initial_label)
                    st.session_state.setdefault(f"{field_key}_reason", initial_reason)
                    selected_label = st.selectbox(
                        "地場産品類型",
                        options=[""] + labels,
                        key=f"{field_key}_type",
                        persist_state="session",
                    )
                    reason = st.text_area(
                        "地場産品に該当する理由",
                        key=f"{field_key}_reason",
                        help="2号・3号・6号は具体的な理由が必要です。",
                        persist_state="session",
                    )
                    selected_code = selected_label.split("｜", 1)[0] if selected_label else ""
                    after_by_field[field.field_id] = f"{selected_code}|{reason.strip()}" if selected_code or reason.strip() else ""
                elif field.source_column == CATEGORY_COLUMN:
                    categories = load_choice_categories()
                    initial_ids = [value.strip() for value in initial_value.split("|") if value.strip()]
                    selected_ids = []
                    st.caption("最大3カテゴリー。最下層のIDだけを保存します。")
                    for category_index in range(3):
                        initial_category = next(
                            (row for row in categories if category_index < len(initial_ids) and row.category_id == initial_ids[category_index]),
                            None,
                        )
                        major_options = list(dict.fromkeys(row.major for row in categories))
                        st.session_state.setdefault(
                            f"{field_key}_{category_index}_major",
                            initial_category.major if initial_category else "",
                        )
                        major = st.selectbox(
                            f"カテゴリー{category_index + 1}：大項目" + ("（必須）" if category_index == 0 else "（任意）"),
                            options=[""] + major_options,
                            key=f"{field_key}_{category_index}_major",
                            persist_state="session",
                        )
                        matching_major = [row for row in categories if row.major == major]
                        middle_options = list(dict.fromkeys(row.middle for row in matching_major if row.middle))
                        st.session_state.setdefault(
                            f"{field_key}_{category_index}_middle",
                            initial_category.middle if initial_category else "",
                        )
                        middle = st.selectbox(
                            f"カテゴリー{category_index + 1}：中項目",
                            options=[""] + middle_options,
                            disabled=not middle_options,
                            key=f"{field_key}_{category_index}_middle",
                            persist_state="session",
                        )
                        matching_middle = [row for row in matching_major if row.middle == middle]
                        minor_options = list(dict.fromkeys(row.minor for row in matching_middle if row.minor))
                        st.session_state.setdefault(
                            f"{field_key}_{category_index}_minor",
                            initial_category.minor if initial_category else "",
                        )
                        minor = st.selectbox(
                            f"カテゴリー{category_index + 1}：小項目",
                            options=[""] + minor_options,
                            disabled=not minor_options,
                            key=f"{field_key}_{category_index}_minor",
                            persist_state="session",
                        )
                        candidates = [
                            row for row in categories
                            if row.major == major
                            and (not minor or row.minor == minor)
                            and (minor or not middle or row.middle == middle)
                        ]
                        if major and candidates:
                            exact = [row for row in candidates if (minor and row.minor == minor) or (not minor and middle and row.middle == middle) or (not middle and not row.middle)]
                            selected_ids.append((exact or candidates)[-1].category_id)
                    after_by_field[field.field_id] = " | ".join(selected_ids)
                elif field.fixed_value:
                    after_by_field[field.field_id] = field.fixed_value
                    st.text_input(
                        field.label,
                        value=_display_field_value(field, field.fixed_value),
                        disabled=True,
                        key=field_key,
                        help="フォーム項目マスタで設定された固定値です。",
                        persist_state="session",
                    )
                elif field.input_kind == "選択" and field.options():
                    label_by_code = {code: label for label, code in field.options()}
                    st.session_state.setdefault(field_key, label_by_code.get(initial_value, initial_value))
                    after_by_field[field.field_id] = st.selectbox(
                        field.label,
                        options=[""] + [label for label, _ in field.options()],
                        key=field_key,
                        persist_state="session",
                    )
                elif field.input_kind == "日付":
                    st.session_state.setdefault(field_key, _parse_date_value(initial_value))
                    after_by_field[field.field_id] = st.date_input(
                        field.label,
                        value=None,
                        format="YYYY-MM-DD",
                        key=field_key,
                        help="カレンダーから選択できます。直接入力も可能です。",
                        persist_state="session",
                    )
                else:
                    st.session_state.setdefault(field_key, initial_value)
                    after_by_field[field.field_id] = st.text_input(
                        field.label,
                        key=field_key,
                        persist_state="session",
                    )
        edited_rows.append(after_by_field)
    return pd.DataFrame(edited_rows)


def _build_product_change_lines(
    *,
    products: list,
    selected_fields: list[RequestFormField],
    fields_for_input: list[RequestFormField],
    edited_values: pd.DataFrame,
    form_fields: list[RequestFormField],
    image_instruction: str | dict[int, str],
) -> tuple[list[ProductCorrectionLine], list[str]]:
    """編集表の変更後値を、商品ごとの修正明細へ変換する。"""

    errors = []
    lines = []
    points_field = find_request_form_field(form_fields, POINTS_COLUMN)
    selected_columns = {field.source_column for field in selected_fields}
    selected_columns.update(field.source_column for field in _system_fixed_fields(form_fields))
    waste_field = find_request_form_field(form_fields, WASTE_FLAG_COLUMN)

    for row_index, product in enumerate(products):
        product_image_instruction = (
            image_instruction.get(row_index, "")
            if isinstance(image_instruction, dict)
            else image_instruction
        )
        row = edited_values.iloc[row_index]
        after_by_field = {
            field.field_id: _normalize_editor_value(
                field, row.get(field.field_id, "")
            )
            for field in fields_for_input
        }
        field_by_column = {field.source_column: field for field in fields_for_input}
        management_field = field_by_column.get(MANAGEMENT_CODE_COLUMN)
        management_code = (
            after_by_field.get(management_field.field_id, "") if management_field else ""
        ) or product.source_values().get(MANAGEMENT_CODE_COLUMN, "")
        for field in fields_for_input:
            fixed_value = _fixed_value_for_column(field.source_column, management_code)
            if fixed_value is not None:
                after_by_field[field.field_id] = fixed_value
        product_name_field = field_by_column.get(PRODUCT_NAME_COLUMN)
        if product_name_field and management_code:
            entered_name = after_by_field.get(product_name_field.field_id, "").strip()
            if entered_name and not entered_name.endswith(f" {management_code}"):
                after_by_field[product_name_field.field_id] = f"{entered_name} {management_code}"
        if not product.product_id:
            values_by_column = {
                field.source_column: after_by_field.get(field.field_id, "")
                for field in fields_for_input
            }
            product = replace(
                product,
                product_name=values_by_column.get("（必須）お礼の品名", "") or "新規商品",
                business_id=values_by_column.get("事業者ID", "") or product.business_id,
                business_name=values_by_column.get("サイト表示事業者名", "") or product.business_name,
            )
        deadline_type_field = field_by_column.get(SHIPPING_DEADLINE_TYPE_COLUMN)
        deadline_type_value = after_by_field.get(deadline_type_field.field_id, "") if deadline_type_field else ""
        waste_selected = (
            waste_field is not None
            and after_by_field.get(waste_field.field_id) == "1"
        )
        missing_labels = []
        for field in selected_fields:
            if field.source_column == SHIPPING_DEADLINE_COLUMN and deadline_type_value not in {"0", "任意入力"}:
                continue
            if field.source_column in WASTE_BRANCH_COLUMNS and not waste_selected:
                continue
            if not after_by_field.get(field.field_id, ""):
                missing_labels.append(field.label)
        if waste_selected:
            missing_labels.extend(
                field.label for field in fields_for_input
                if field.source_column in WASTE_BRANCH_COLUMNS
                and not after_by_field.get(field.field_id, "")
            )
        local_field = field_by_column.get(LOCAL_PRODUCT_TYPE_COLUMN)
        local_value = after_by_field.get(local_field.field_id, "") if local_field else ""
        if local_value:
            local_code, _, local_reason = local_value.partition("|")
            if local_code.startswith(("2", "3", "6")) and not local_reason.strip():
                missing_labels.append("地場産品に該当する理由")
        if missing_labels:
            product_label = product.source_values().get("管理コード", "") or product.product_name
            errors.append(f"{product_label}: " + "、".join(dict.fromkeys(missing_labels)))
            continue

        product_lines = []
        for field in fields_for_input:
            after_value = after_by_field.get(field.field_id, "")
            is_system_fixed = field.source_column in selected_columns and field.source_column in HIDDEN_FORM_COLUMNS
            if not after_value and not is_system_fixed:
                continue
            if field.source_column not in selected_columns and not waste_selected:
                continue
            before_value = product.source_values().get(field.source_column, "")
            if after_value == before_value:
                continue
            product_lines.append(ProductCorrectionLine(
                product=product,
                field_name=field.source_column,
                before_value=before_value,
                after_value=after_value,
                image_instruction=product_image_instruction.strip() if not product_lines else "",
                column_number=product.source_column_number(field.source_column),
                display_name=field.label,
            ))
            if field.source_column == DONATION_COLUMN and points_field is not None:
                point_before = product.source_values().get(POINTS_COLUMN, "")
                if point_before != after_value:
                    product_lines.append(ProductCorrectionLine(
                        product=product,
                        field_name=POINTS_COLUMN,
                        before_value=point_before,
                        after_value=after_value,
                        instruction="寄付額の変更後値をポイントへ自動反映",
                        column_number=product.source_column_number(POINTS_COLUMN),
                        display_name=points_field.label,
                    ))
        lines.extend(product_lines)
    return lines, errors


def _new_product_reference(
    municipality_id: str,
    municipality_name: str,
    form_fields: list[RequestFormField],
) -> ProductReference:
    return ProductReference(
        municipality_id=municipality_id,
        municipality_name=municipality_name,
        product_id="",
        original_product_id="",
        product_name="新規商品",
        business_id="",
        business_name="",
        source_row=tuple((field.source_column, "") for field in form_fields),
    )


def _render_temperature_editor(
    products: list[ProductReference], *, editor_key: str,
    initial_values: dict[str, str] | None = None,
) -> pd.DataFrame:
    initial_values = initial_values or {}
    rows = []
    for product_index, product in enumerate(products):
        source_values = product.source_values()
        management_code = source_values.get("管理コード", "") or product.product_id
        current = [
            label for label, column in TEMPERATURE_COLUMNS.items()
            if source_values.get(column, "") == "1"
        ]
        with st.container(border=True):
            st.markdown(f"#### 品番：{management_code}")
            st.write(f"商品名：{product.product_name or '未設定'}")
            st.caption(
                "現在の温度帯：" + ("・".join(current) if current else "未設定")
            )
            temperature_key = f"{editor_key}_{product_index}"
            imported = [
                label for label, column in TEMPERATURE_COLUMNS.items()
                if initial_values.get(column) == "1"
            ]
            if imported:
                st.session_state.setdefault(temperature_key, imported)
            selected = st.pills(
                "温度帯（必須・複数選択可）",
                options=list(TEMPERATURE_COLUMNS),
                selection_mode="multi",
                key=temperature_key,
            )
        rows.append({"温度帯": selected})
    return pd.DataFrame(rows)


def _build_temperature_change_lines(
    *, products: list[ProductReference], edited_values: pd.DataFrame
) -> tuple[list[ProductCorrectionLine], list[str]]:
    lines = []
    errors = []
    for row_index, product in enumerate(products):
        selected = edited_values.iloc[row_index].get("温度帯", [])
        selected_names = set(selected if isinstance(selected, (list, tuple, set)) else [])
        if not selected_names:
            product_label = product.source_values().get("管理コード", "") or product.product_name
            errors.append(f"{product_label}: 温度帯")
            continue
        for label, column in TEMPERATURE_COLUMNS.items():
            before_value = product.source_values().get(column, "")
            after_value = "1" if label in selected_names else "0"
            if before_value == after_value:
                continue
            lines.append(ProductCorrectionLine(
                product=product,
                field_name=column,
                before_value=before_value,
                after_value=after_value,
                column_number=product.source_column_number(column),
                display_name=f"温度帯（{label}）",
            ))
    return lines, errors


def _render_selected_product_preview(selected_products: list) -> None:
    if not selected_products:
        return
    st.caption("選択中の商品・品番（管理コード）")
    st.dataframe(
        [
            {
                "品番": product.source_values().get("管理コード", ""),
                "商品名": product.product_name,
                "事業者": product.business_name,
            }
            for product in selected_products
        ],
        hide_index=True,
    )


def _render_subscription_detail_editor(*, editor_context: str, imported_rows=None):
    """選択した配送回数に合わせて定期便明細を固定行で表示する。"""
    imported_rows = list(imported_rows or [])
    default_count = max(2, len(imported_rows))
    delivery_count = int(st.number_input(
        "お届け回数（必須）", min_value=2, max_value=36, value=default_count,
        step=1, key=f"subscription_count_{editor_context}",
    ))
    st.caption(f"第1回～第{delivery_count}回の入力欄を表示しています。")
    rows = []
    for index in range(delivery_count):
        source = imported_rows[index] if index < len(imported_rows) else {}
        rows.append({
            "お届け回": str(index + 1),
            "お届け時期": source.get("お届け時期", ""),
            "お届け内容": source.get("お届け内容", ""),
            "内容量": source.get("内容量", ""),
            "数量": source.get("数量", ""),
            "温度帯": source.get("温度帯", ""),
            "補足": source.get("補足", ""),
        })
    return st.data_editor(
        pd.DataFrame(rows), hide_index=True, num_rows="fixed",
        disabled=["お届け回"],
        column_config={
            "お届け回": st.column_config.TextColumn("回", pinned=True),
            "温度帯": st.column_config.SelectboxColumn(
                "温度帯", options=["", "常温", "冷蔵", "冷凍"]
            ),
        },
        key=f"subscription_detail_{editor_context}_{delivery_count}",
    )


def _render_sku_detail_editor(
    *, editor_context: str, is_new_product: bool, selected_products: list,
    municipality_products: list, selected_business_name: str = "", imported_rows=None,
):
    """新規・既存を同じカード型フォームで入力し、登録用SKU行へ正規化する。"""
    imported_rows = list(imported_rows or [])
    if is_new_product:
        composition = st.segmented_control(
            "SKUにまとめる商品の構成（必須）",
            ["新規商品のみ", "既存商品のみ", "新規＋既存"],
            default="新規商品のみ", required=True,
            key=f"sku_composition_{editor_context}",
        )
    else:
        composition = "既存商品のみ"
        st.info("上で選択した既存商品を、1つのSKU商品としてまとめます。")

    default_count = max(2, len(imported_rows), len(selected_products) if not is_new_product else 0)
    sku_count = int(st.number_input(
        "作成するSKU数（必須）", min_value=2, max_value=100,
        value=default_count, step=1, key=f"sku_count_{editor_context}",
    ))
    split_axes = st.multiselect(
        "SKUをどの項目で分けますか（複数選択可）",
        ["品種", "容量", "色", "数量", "配送月", "その他"],
        default=["容量"], accept_new_options=True,
        key=f"sku_split_axes_{editor_context}",
        help="例：品種 → kg数（容量） → 配送月",
    )
    if split_axes:
        st.caption("SKUの分け方：" + " → ".join(split_axes))

    candidates = [
        product for product in municipality_products
        if not selected_business_name or product.business_name == selected_business_name
    ]
    if composition in {"既存商品のみ", "新規＋既存"}:
        st.caption(
            f"既存商品の選択肢は、事業者「{selected_business_name}」の商品だけを表示します。"
            if selected_business_name else "先に事業者を選択すると、その事業者の商品だけに絞り込まれます。"
        )
    existing_by_label = {_product_label(product): product for product in candidates}
    initially_selected = [_product_label(product) for product in selected_products if product in candidates]
    rows = []
    for index in range(sku_count):
        source = imported_rows[index] if index < len(imported_rows) else {}
        if composition == "既存商品のみ":
            default_type = "既存"
        elif composition == "新規商品のみ":
            default_type = "新規"
        else:
            default_type = source.get("商品区分", "新規")
        with st.container(border=True):
            st.markdown(f"#### SKU {index + 1}")
            if composition == "新規＋既存":
                item_type = st.segmented_control(
                    "商品区分（必須）", ["新規", "既存"], default=default_type,
                    key=f"sku_item_type_{editor_context}_{index}",
                )
            else:
                item_type = default_type
                st.caption(f"商品区分：{item_type}")

            existing_product = None
            existing_label = ""
            if item_type == "既存":
                default_label = source.get(
                    "既存商品", initially_selected[index] if index < len(initially_selected) else ""
                )
                existing_key = f"sku_existing_product_{editor_context}_{index}"
                if default_label in existing_by_label:
                    st.session_state.setdefault(existing_key, default_label)
                existing_label = st.selectbox(
                    "既存商品（必須）", options=list(existing_by_label),
                    format_func=lambda label: label,
                    index=None if not existing_by_label else 0,
                    placeholder="商品名または品番で検索して選択してください",
                    key=existing_key,
                ) if existing_by_label else ""
                existing_product = existing_by_label.get(existing_label)
                if not existing_by_label:
                    st.warning("選択した事業者に登録済みの商品がありません。")

            existing_values = existing_product.source_values() if existing_product else {}
            management_code = existing_values.get("管理コード", "")
            product_name = existing_product.product_name if existing_product else ""
            donation = (
                existing_values.get("（条件付き必須）寄附額", "")
                or existing_values.get("寄附額", "")
            )
            capacity = existing_values.get("容量", "")
            if item_type == "新規":
                code_method = st.segmented_control(
                    "品番の用意方法（必須）",
                    ["品番を入力する", "品番取得を依頼する"],
                    default=source.get("品番取得方法", "品番を入力する"),
                    key=f"sku_code_method_{editor_context}_{index}",
                )
                sku_code = ""
                if code_method == "品番を入力する":
                    sku_code = st.text_input(
                        "品番（必須）", value=source.get("SKU品番", ""),
                        key=f"sku_code_{editor_context}_{index}",
                    )
                sku_name = st.text_input(
                    "商品名（必須）", value=source.get("商品名", ""),
                    key=f"sku_name_{editor_context}_{index}",
                )
            else:
                code_method = "既存品番を使用"
                sku_code = management_code
                sku_name = product_name
                st.text_input(
                    "品番（既存商品から自動反映）", value=sku_code, disabled=True,
                    key=f"sku_existing_code_view_{editor_context}_{index}_{sku_code}",
                )
                st.text_input(
                    "商品名（既存商品から自動反映）", value=sku_name, disabled=True,
                    key=f"sku_existing_name_view_{editor_context}_{index}_{sku_code}",
                )

            axis_values = {}
            for axis in split_axes:
                column_name = "その他の分け方" if axis == "その他" else axis
                default_value = source.get(column_name, capacity if axis == "容量" else "")
                axis_values[column_name] = st.text_input(
                    f"{axis}（SKUの分け方・必須）", value=default_value,
                    key=f"sku_axis_{axis}_{editor_context}_{index}",
                )
            variation_default = source.get("バリエーション名", " / ".join(filter(None, axis_values.values())))
            variation = st.text_input(
                "バリエーション名（必須）", value=variation_default,
                key=f"sku_variation_{editor_context}_{index}",
                help="例：コシヒカリ / 5kg / 10月配送",
            )
            if item_type == "新規":
                cost_change_mode = "商品代を登録する"
                product_cost = st.text_input(
                    "商品代（税込・必須）", value=source.get("商品代（税込）", ""),
                    key=f"sku_cost_{editor_context}_{index}",
                )
            else:
                cost_change_mode = st.segmented_control(
                    "商品代（税込・必須）",
                    ["商品代を変更する", "商品代を変更しない"],
                    default=source.get("商品代変更", "商品代を変更しない"),
                    key=f"sku_cost_mode_{editor_context}_{index}",
                )
                product_cost = ""
                if cost_change_mode == "商品代を変更する":
                    product_cost = st.text_input(
                        "変更後の商品代（税込・必須）",
                        value=source.get("商品代（税込）", ""),
                        key=f"sku_cost_{editor_context}_{index}",
                    )
            columns = st.columns(2)
            with columns[0]:
                donation_value = st.text_input(
                    "寄附額", value=source.get("寄附額", donation),
                    key=f"sku_donation_{editor_context}_{index}",
                )
            with columns[1]:
                stock = st.text_input(
                    "在庫数", value=source.get("在庫数", ""),
                    key=f"sku_stock_{editor_context}_{index}",
                )
            temperature = st.selectbox(
                "温度帯", ["", "常温", "冷蔵", "冷凍"],
                index=["", "常温", "冷蔵", "冷凍"].index(source.get("温度帯", ""))
                if source.get("温度帯", "") in ["", "常温", "冷蔵", "冷凍"] else 0,
                key=f"sku_temperature_{editor_context}_{index}",
            )
            note = st.text_area(
                "SKUごとの補足", value=source.get("補足", ""),
                key=f"sku_note_{editor_context}_{index}",
            )
            row = {
                "登録区分": "新規登録（SKU）", "商品区分": item_type, "既存商品": existing_label,
                "品番取得方法": code_method, "SKU品番": sku_code,
                "商品名": sku_name, "バリエーション名": variation,
                "品種": "", "容量": "", "色": "", "数量": "", "配送月": "",
                "その他の分け方": "", "商品代変更": cost_change_mode,
                "商品代（税込）": product_cost,
                "寄附額": donation_value, "在庫数": stock,
                "温度帯": temperature, "補足": note,
                "チョイスマスタ値": existing_values,
            }
            row.update(axis_values)
            rows.append(row)
    return pd.DataFrame(rows), composition, split_axes


def _allergy_display_name(field: RequestFormField) -> str:
    return field.label.removeprefix(ALLERGY_PREFIX)


def _render_allergy_editor(
    products: list,
    allergy_fields: list[RequestFormField],
    allergy_note_field: RequestFormField | None,
    *,
    editor_key: str,
    initial_values: dict[str, str] | None = None,
) -> pd.DataFrame:
    initial_values = initial_values or {}
    rows = []
    allergy_options = [_allergy_display_name(field) for field in allergy_fields]
    for product_index, product in enumerate(products):
        source_values = product.source_values()
        current_allergies = [
            _allergy_display_name(field)
            for field in allergy_fields
            if source_values.get(field.source_column, "") == "1"
        ]
        management_code = source_values.get("管理コード", "") or product.product_id
        with st.container(border=True):
            st.markdown(f"#### 品番：{management_code}")
            st.write(f"商品名：{product.product_name or '未設定'}")
            st.caption("現在値")
            current_values = {
                "アレルギー品目": "、".join(current_allergies) or "該当なし",
            }
            if allergy_note_field is not None:
                current_values["アレルギー特記事項"] = (
                    source_values.get(allergy_note_field.source_column, "") or "（未設定）"
                )
            st.dataframe([current_values], hide_index=True)
            st.caption("変更後値")
            allergy_items_key = f"{editor_key}_{product_index}_items"
            imported_allergies = [
                _allergy_display_name(field) for field in allergy_fields
                if initial_values.get(field.source_column) == "1"
            ]
            if imported_allergies:
                st.session_state.setdefault(allergy_items_key, imported_allergies)
            updated_allergies = st.multiselect(
                "アレルギー品目（含む品目にチェック）",
                options=allergy_options,
                key=allergy_items_key,
            )
            updated_note = ""
            if allergy_note_field is not None:
                allergy_note_key = f"{editor_key}_{product_index}_note"
                st.session_state.setdefault(
                    allergy_note_key,
                    initial_values.get(allergy_note_field.source_column, ""),
                )
                updated_note = st.text_input(
                    "アレルギー特記事項",
                    key=allergy_note_key,
                )
        rows.append({
            "アレルギー品目（変更後）": updated_allergies,
            "アレルギー特記事項（変更後）": updated_note,
        })
    return pd.DataFrame(rows)


def _build_allergy_change_lines(
    *,
    products: list,
    allergy_fields: list[RequestFormField],
    allergy_note_field: RequestFormField | None,
    edited_values: pd.DataFrame,
) -> list[ProductCorrectionLine]:
    lines = []
    fields_by_name = {_allergy_display_name(field): field for field in allergy_fields}
    for row_index, product in enumerate(products):
        row = edited_values.iloc[row_index]
        selected_values = row["アレルギー品目（変更後）"]
        if not isinstance(selected_values, (list, tuple, set)):
            selected_values = []
        selected_names = {str(value).strip() for value in selected_values if str(value).strip()}
        for name, field in fields_by_name.items():
            before_value = product.source_values().get(field.source_column, "")
            after_value = "1" if name in selected_names else "2"
            if before_value != after_value:
                lines.append(ProductCorrectionLine(
                    product=product,
                    field_name=field.source_column,
                    before_value=before_value,
                    after_value=after_value,
                    column_number=product.source_column_number(field.source_column),
                    display_name=field.label,
                ))
        if allergy_note_field is not None:
            after_note = _normalize_editor_value(
                allergy_note_field, row["アレルギー特記事項（変更後）"]
            )
            before_note = product.source_values().get(allergy_note_field.source_column, "")
            if after_note and after_note != before_note:
                lines.append(ProductCorrectionLine(
                    product=product,
                    field_name=allergy_note_field.source_column,
                    before_value=before_note,
                    after_value=after_note,
                    column_number=product.source_column_number(allergy_note_field.source_column),
                    display_name=allergy_note_field.label,
                ))
    return lines


def _safe_attachment_name(file_name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", Path(file_name).name).strip(" .") or "attachment"


def _save_uploaded_attachments(request_id: str, uploaded_files: list) -> list[Path]:
    destination = UPLOAD_DIRECTORY / request_id
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for uploaded_file in uploaded_files:
        path = destination / f"{uuid4().hex}_{_safe_attachment_name(uploaded_file.name)}"
        path.write_bytes(uploaded_file.getvalue())
        paths.append(path)
    return paths


def _render_backlog_custom_field(custom_field, field_key: str):
    label = f"{custom_field.name}（{'必須' if custom_field.required else '任意'}）"
    if custom_field.options:
        option_names = [option.name for option in custom_field.options]
        if custom_field.type_id in {"6", "7"}:
            return st.multiselect(label, options=option_names, key=field_key)
        return st.selectbox(label, options=[""] + option_names, key=field_key)
    if custom_field.type_id == "4":
        value = st.date_input(
            label,
            value=None,
            format="YYYY-MM-DD",
            key=field_key,
        )
        return value.isoformat() if value else ""
    return st.text_input(label, key=field_key)


def _load_saved_request_into_draft(
    *,
    saved_request,
    products: list,
    form_fields: list[RequestFormField],
) -> list[str]:
    """保存済み明細を、現在の商品マスタを基に編集用の状態へ戻す。"""

    product_by_id = {
        (product.municipality_id, product.product_id): product for product in products
    }
    product_by_original_id = {
        (product.municipality_id, product.original_product_id): product
        for product in products if product.original_product_id
    }
    selected_products = []
    selected_fields = []
    lines = []
    missing_products = []
    for detail in saved_request.details:
        product = (
            product_by_id.get((saved_request.municipality_id, detail.product_id))
            or product_by_original_id.get(
                (saved_request.municipality_id, detail.original_product_id)
            )
        )
        if product is None:
            missing_products.append(detail.product_id or detail.original_product_id or "（ID未設定）")
            continue
        field = find_request_form_field(form_fields, detail.field_name)
        if field is not None and field not in selected_fields:
            selected_fields.append(field)
        if product not in selected_products:
            selected_products.append(product)
        lines.append(ProductCorrectionLine(
            product=product,
            field_name=detail.field_name,
            before_value=detail.before_value,
            after_value=detail.after_value,
            instruction=detail.instruction,
            image_instruction=detail.image_instruction,
            column_number=product.source_column_number(detail.field_name),
            display_name=field.label if field is not None else detail.field_name,
        ))

    st.session_state.correction_lines = lines
    st.session_state.request_unit = (
        saved_request.request_unit
        if saved_request.request_unit in REQUEST_UNITS else "商品単位"
    )
    st.session_state.request_work_category = (
        saved_request.work_category
        if saved_request.work_category in WORK_CATEGORIES else "一般業務"
    )
    st.session_state.request_municipality_id = saved_request.municipality_id
    st.session_state.request_selected_products = selected_products
    st.session_state.request_selected_form_fields = selected_fields
    st.session_state.request_note = saved_request.note
    st.session_state[f"request_backlog_issue_type_{saved_request.municipality_id}"] = (
        saved_request.backlog_issue_type
    )
    st.session_state.editing_source_request_id = saved_request.request_id
    st.session_state.editing_source_backlog_issue_key = saved_request.backlog_issue_key
    st.session_state.product_change_editor_version = (
        st.session_state.get("product_change_editor_version", 0) + 1
    )
    return missing_products


def render_product_request_tab(
    *,
    config_spreadsheet_id: str,
    product_spreadsheet_id: str,
    credentials_path: Path,
) -> None:
    st.subheader("商品修正・施策依頼")
    st.caption(
        "商品ごとに、上段の現在値を確認して下段の変更後値を入力し、依頼を作成します。"
        "起票時には変更後データExcelと、必要に応じて追加ファイルをBacklogへ添付します。"
    )

    try:
        with st.spinner("商品・フォーム・施策マスタを読み込んでいます。"):
            products = _load_products(product_spreadsheet_id, str(credentials_path))
            form_fields = _load_form_fields(config_spreadsheet_id, str(credentials_path))
            policies = _load_policies(config_spreadsheet_id, str(credentials_path))
    except Exception as error:
        st.error("依頼フォーム用のマスタを読み込めませんでした。")
        st.exception(error)
        return

    with st.container(border=True):
        st.subheader("登録済み依頼を再編集")
        st.caption(
            "Backlog親課題キーまたは依頼IDを入力すると、保存済みの変更明細をフォームへ戻せます。"
            "保存時は同じBacklog親課題を更新し、商品情報マスタには改訂履歴を追加します。"
        )
        history_lookup = st.text_input(
            "Backlog親課題キーまたは依頼ID",
            placeholder="例：PROJECT-123 または PR-20260805-xxxx",
            key="request_history_lookup",
        )
        if st.button("履歴を読み込む", type="secondary"):
            try:
                with st.spinner("保存済み依頼を読み込んでいます。"):
                    saved_request = load_saved_product_correction_request(
                        spreadsheet_id=product_spreadsheet_id,
                        credentials_path=credentials_path,
                        lookup_value=history_lookup,
                    )
                if saved_request is None:
                    st.warning("指定した依頼IDまたはBacklog親課題キーの履歴が見つかりません。")
                else:
                    missing_products = _load_saved_request_into_draft(
                        saved_request=saved_request,
                        products=products,
                        form_fields=form_fields,
                    )
                    if missing_products:
                        st.warning(
                            "商品マスタに見つからず読み込めなかった商品があります："
                            + "、".join(dict.fromkeys(missing_products))
                        )
                    st.success(
                        f"依頼ID：{saved_request.request_id} を読み込みました。"
                        "内容を修正して保存すると、同じBacklog親課題を更新します。"
                    )
                    st.rerun()
            except Exception as error:
                st.error("登録済み依頼を読み込めませんでした。")
                st.exception(error)

    st.session_state.setdefault("correction_lines", [])
    st.session_state.setdefault("product_change_editor_version", 0)
    correction_lines = st.session_state.correction_lines
    municipality_names = {}
    for product in products:
        municipality_names.setdefault(
            product.municipality_id,
            product.municipality_name or product.municipality_id,
        )
    if not municipality_names:
        st.warning("商品情報マスタに検索できる商品がありません。")
        return

    with st.container(border=True):
        request_unit = st.segmented_control(
            "対応単位",
            REQUEST_UNITS,
            default="商品単位",
            required=True,
            key="request_unit",
            width="stretch",
        )
        work_category = st.segmented_control(
            "業務種別",
            WORK_CATEGORIES,
            default="一般業務",
            required=True,
            key="request_work_category",
            width="stretch",
        )
        target_municipality_id = st.selectbox(
            "自治体",
            options=list(municipality_names),
            format_func=lambda municipality_id: municipality_names[municipality_id],
            key="request_municipality_id",
        )
    is_new_product = work_category == "新規商品登録"
    product_shape = "単品"
    registration_source_file = None
    imported_registration = st.session_state.get("registration_excel_import")
    if request_unit == "商品単位" or is_new_product:
        with st.container(border=True):
            st.subheader("商品形態")
            product_shape = st.segmented_control(
                "登録する商品の構成",
                PRODUCT_SHAPES,
                default="単品",
                required=True,
                key="request_product_shape",
                width="stretch",
            )
            if is_new_product:
                st.caption(
                    "単品・定期便・SKU展開ごとに、チョイス全項目を収録した公式Excelを利用できます。"
                )
                st.download_button(
                    "新規商品登録テンプレートをダウンロード",
                    data=build_registration_template(form_fields, product_shape),
                    file_name=f"新規商品登録_{product_shape}_テンプレート.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    icon=":material/download:",
                    key=f"download_registration_template_{product_shape}",
                )
                registration_source_file = st.file_uploader(
                    "入力済みの公式Excelがある場合は取り込む",
                    type=["xlsx"],
                    key="registration_excel_upload",
                    help="取り込んだ値を、新規商品登録フォームの初期値として反映します。",
                )
                if registration_source_file is not None:
                    fingerprint = (
                        registration_source_file.name,
                        registration_source_file.size,
                    )
                    if st.session_state.get("registration_excel_fingerprint") != fingerprint:
                        try:
                            imported_registration = read_registration_template(
                                registration_source_file.getvalue(), form_fields
                            )
                            st.session_state.registration_excel_import = imported_registration
                            st.session_state.registration_excel_fingerprint = fingerprint
                            st.session_state.product_change_editor_version += 1
                        except Exception as error:
                            st.error(f"Excelを取り込めませんでした：{error}")
                            imported_registration = None
                    if imported_registration is not None:
                        st.success(
                            f"Excelからチョイス項目 {len(imported_registration.choice_values)}件、"
                            f"追加情報 {len(imported_registration.extra_values)}件を読み込みました。"
                        )
                        if imported_registration.product_shape != product_shape:
                            st.warning(
                                f"Excelの商品形態は「{imported_registration.product_shape}」です。"
                                "画面の商品形態も同じものを選択してください。"
                            )
                        for warning in imported_registration.warnings:
                            st.warning(warning)

    selected_policy = None
    if work_category == "施策":
        policy_type_options = policy_types(policies, request_unit)
        with st.container(border=True):
            st.subheader("施策の選択")
            if not policy_type_options:
                st.warning(f"施策マスタに「{request_unit}」用の施策がありません。")
            else:
                policy_type = st.selectbox(
                    "施策種別",
                    policy_type_options,
                    index=None,
                    placeholder="施策種別を選択してください",
                    key="request_policy_type",
                )
                policy_content_options = (
                    policy_contents(policies, request_unit, policy_type)
                    if policy_type else []
                )
                policy_content = st.selectbox(
                    "施策具体内容",
                    policy_content_options,
                    index=None,
                    placeholder="具体内容を選択してください",
                    key="request_policy_content",
                    disabled=not policy_type,
                )
                if policy_type and policy_content:
                    selected_policy = find_policy_entry(
                        policies, request_unit, policy_type, policy_content
                    )
                if selected_policy is not None:
                    st.text_area(
                        "施策詳細（施策マスタから自動表示）",
                        value=selected_policy.detail,
                        disabled=True,
                        key="request_policy_detail_view",
                    )
                    if selected_policy.reference_url:
                        st.link_button("施策の参照URLを開く", selected_policy.reference_url)

    selected_products = []
    if request_unit == "商品単位" and not is_new_product:
        municipality_products = [
            product for product in products if product.municipality_id == target_municipality_id
        ]
        business_names = sorted({product.business_name for product in municipality_products if product.business_name})
        with st.container(border=True):
            st.subheader("対象商品の選択")
            business_name = st.selectbox(
                "事業者",
                options=["すべて"] + business_names,
                key="request_business_name",
            )
            candidate_products = [
                product for product in municipality_products
                if business_name == "すべて" or product.business_name == business_name
            ]
            selected_products = st.multiselect(
                "商品（複数選択可）",
                options=candidate_products,
                format_func=_product_label,
                placeholder="商品名または品番で検索して選択してください",
                key="request_selected_products",
            )
            _render_selected_product_preview(selected_products)
    elif is_new_product:
        municipality_products = [
            product for product in products
            if product.municipality_id == target_municipality_id
        ]
        business_options = sorted({
            product.business_name
            for product in municipality_products
            if product.business_name
        })
        with st.container(border=True):
            st.subheader("新規商品の入力")
            st.caption(
                "お礼の品ID・オリジナルお礼の品IDは空欄のまま保存します。"
                "画面では日本語を選び、商品データにはチョイス指定のコードを保存します。"
            )
            business_mode = st.segmented_control(
                "事業者の指定方法",
                ("既存事業者から選択", "新しい事業者を入力"),
                default="既存事業者から選択" if business_options else "新しい事業者を入力",
                required=True,
                key="request_new_business_mode",
            )
            if business_mode == "既存事業者から選択" and business_options:
                business_name = st.selectbox(
                    "事業者",
                    options=business_options,
                    key="request_new_existing_business",
                )
            else:
                business_name = st.text_input(
                    "事業者名（必須）", key="request_new_business_name"
                ).strip()
            new_product = _new_product_reference(
                target_municipality_id,
                municipality_names[target_municipality_id],
                form_fields,
            )
            selected_products = [replace(
                new_product,
                business_id="",
                business_name=business_name,
            )]

    try:
        active_backlog_configs = backlog_configs_by_municipality_id(
            _load_backlog_configs(config_spreadsheet_id, str(credentials_path))
        )
        issue_types = _load_backlog_issue_types(
            config_spreadsheet_id, str(credentials_path)
        )
    except Exception:
        active_backlog_configs = {}
        issue_types = []
        st.warning("Backlog設定を読み込めません。依頼の保存・起票はできません。")

    target_backlog_config = active_backlog_configs.get(target_municipality_id)
    municipality_issue_types = [
        issue_type for issue_type in issue_types
        if issue_type.municipality_id == target_municipality_id
    ]
    issue_type_by_name = {issue_type.name: issue_type for issue_type in municipality_issue_types}
    issue_type_names = list(issue_type_by_name)
    preferred_issue_type_name = ""
    if selected_policy is not None:
        preferred_issue_type_name = selected_policy.recommended_issue_type
    elif is_new_product and "新商品登録" in issue_type_names:
        preferred_issue_type_name = "新商品登録"
    elif is_new_product and "新規商品登録" in issue_type_names:
        preferred_issue_type_name = "新規商品登録"
    elif target_backlog_config is not None:
        preferred_issue_type_name = target_backlog_config.product_correction_issue_type

    selected_issue_type = None
    target_image_issue_type = None
    create_backlog_issue = False
    backlog_issue_title = ""
    if target_backlog_config is None:
        st.error("この自治体のBacklog接続設定がないため、依頼を起票できません。")
    elif not issue_type_names:
        st.warning("この自治体のBacklog課題種別を確認できません。")
    else:
        issue_type_key = f"request_backlog_issue_type_{target_municipality_id}"
        policy_context = "|".join((
            target_municipality_id,
            request_unit,
            work_category,
            selected_policy.policy_id if selected_policy else "",
            preferred_issue_type_name,
        ))
        _set_policy_issue_type_default(
            key=issue_type_key,
            context_key=policy_context,
            preferred_name=preferred_issue_type_name,
            available_names=issue_type_names,
        )
        with st.container(border=True):
            st.subheader("Backlog課題設定")
            selected_issue_type_name = st.selectbox(
                "Backlog課題種別",
                issue_type_names,
                key=issue_type_key,
                help="施策を選択した場合は施策マスタの推奨種別が初期値になります。",
            )
            selected_issue_type = issue_type_by_name[selected_issue_type_name]
            backlog_issue_title = st.text_input(
                "Backlog課題タイトル",
                placeholder="未入力の場合は自治体名・商品数から自動設定します。",
                key=f"request_backlog_issue_title_{target_municipality_id}",
            )
            if selected_policy and preferred_issue_type_name not in issue_type_by_name:
                st.warning(
                    f"施策マスタの推奨種別「{preferred_issue_type_name}」が"
                    "この自治体の課題種別にないため、選択した種別で起票します。"
                )
            st.caption("依頼を保存すると、選択した種別でBacklog課題を必ず起票します。")
            create_backlog_issue = True
        if target_backlog_config.image_child_issue_type:
            target_image_issue_type = issue_type_by_name.get(
                target_backlog_config.image_child_issue_type
            )

    if (request_unit == "商品単位" or is_new_product) and selected_products:
        visible_fields = _sort_change_fields(
            _visible_form_fields(form_fields, is_new_product=is_new_product)
        )
        selectable_fields = [
            field for field in visible_fields
            if _field_visibility(field, is_new_product=is_new_product) == "対象項目選択肢"
        ]
        always_fields = [
            field for field in visible_fields
            if _field_visibility(field, is_new_product=is_new_product) in {"常時表示", "固定"}
            or bool(field.fixed_value)
        ]
        code_change_requested = False
        if is_new_product:
            new_product_code_method = None
            if product_shape != "SKU展開":
                new_product_code_method = st.segmented_control(
                    "品番の用意方法（必須）",
                    ["品番を入力する", "品番取得を依頼する"],
                    default="品番を入力する",
                    key="new_product_code_method",
                    persist_state="session",
                )
            business_fields = []
            business_name_field = find_request_form_field(form_fields, "サイト表示事業者名")
            if business_name_field is not None:
                business_fields.append(replace(
                    business_name_field,
                    fixed_value=selected_products[0].business_name,
                ))
            business_columns = {field.source_column for field in business_fields}
            selected_fields = [
                field for field in visible_fields
                if field.source_column not in business_columns
                and field.source_column not in {
                    "（必須）定期配送対応", "（必須）別送対応", "（必須）表示有無"
                }
                and not (
                    field.source_column == MANAGEMENT_CODE_COLUMN
                    and (
                        product_shape == "SKU展開"
                        or new_product_code_method == "品番取得を依頼する"
                    )
                )
            ] + business_fields
            if product_shape != "SKU展開" and new_product_code_method == "品番を入力する":
                management_field = find_request_form_field(form_fields, MANAGEMENT_CODE_COLUMN)
                if management_field is not None and management_field not in selected_fields:
                    selected_fields.insert(0, management_field)
            st.caption(
                f"画像・動画・サイト自動取得項目を除く {len(selected_fields)}項目を、"
                "チョイスマスタ順にすべて入力してください。"
            )
        else:
            correction_type = st.selectbox(
                "修正種別",
                options=CORRECTION_TYPES,
                key="request_correction_type",
                help="修正内容に応じて必要な入力項目を自動表示します。",
            )
            if correction_type == "複合的な修正":
                st.caption("2項目以上をまとめて修正する場合はこちらを選択してください。")
                change_options: list[RequestFormField | str] = [
                    *[
                        field for field in selectable_fields
                        if field.source_column not in {
                            "（必須）定期配送対応", "（必須）別送対応", "（必須）表示有無"
                        }
                    ],
                    TEMPERATURE_CHANGE_OPTION,
                    ALLERGY_CHANGE_OPTION,
                ]
                selected_change_options = st.multiselect(
                    "変更する項目",
                    options=change_options,
                    format_func=lambda option: (
                        option.label if isinstance(option, RequestFormField) else option
                    ),
                    placeholder="変更する項目を選択してください",
                    key="request_selected_form_fields",
                )
                selected_optional_fields = [
                    option for option in selected_change_options
                    if isinstance(option, RequestFormField)
                ]
            else:
                selected_change_options = []
                target_columns = CORRECTION_TYPE_COLUMNS[correction_type]
                selected_optional_fields = [
                    field for field in visible_fields
                    if field.source_column in target_columns
                ]
                if selected_optional_fields:
                    st.caption(
                        "入力項目：" + "、".join(field.label for field in selected_optional_fields)
                    )
            selected_fields = list(dict.fromkeys(
                (always_fields if correction_type == "複合的な修正" else [])
                + selected_optional_fields
            ))
            code_change_requested = any(
                field.source_column == MANAGEMENT_CODE_COLUMN
                for field in selected_fields
            )
            if code_change_requested:
                selected_fields = [
                    field for field in selected_fields
                    if field.source_column != MANAGEMENT_CODE_COLUMN
                ]
        temperature_change_requested = is_new_product or (
            correction_type == "複合的な修正"
            and TEMPERATURE_CHANGE_OPTION in selected_change_options
        )
        allergy_fields = [
            field for field in selectable_request_form_fields(form_fields)
            if _is_allergy_item_field(field) and "欠番" not in field.label
        ]
        allergy_note_field = find_request_form_field(form_fields, ALLERGY_NOTE_COLUMN)
        allergy_change_requested = is_new_product or (
            correction_type == "複合的な修正"
            and ALLERGY_CHANGE_OPTION in selected_change_options
        )
        backlog_only_type = (
            not is_new_product
            and correction_type in {"寄附額変更", "在庫数変更"}
        )
        if selected_fields or temperature_change_requested or allergy_change_requested or backlog_only_type:
            system_fixed_fields = _system_fixed_fields(form_fields)
            fields_for_input = list(dict.fromkeys(list(selected_fields) + system_fixed_fields))
            selected_columns = {field.source_column for field in selected_fields}
            if WASTE_FLAG_COLUMN in selected_columns:
                for branch_column in WASTE_BRANCH_COLUMNS:
                    branch_field = find_request_form_field(form_fields, branch_column)
                    if branch_field is not None and branch_field not in fields_for_input:
                        fields_for_input.append(branch_field)
            editor_context = "|".join((
                target_municipality_id,
                ",".join(product.product_id for product in selected_products),
                product_shape,
                str(st.session_state.product_change_editor_version),
            ))
            with st.container(border=True):
                st.subheader("新規商品データ" if is_new_product else "商品ごとの変更後値")
                edited_product_values = None
                renderable_fields = [
                    field for field in fields_for_input
                    if field.source_column not in HIDDEN_FORM_COLUMNS
                ]
                if renderable_fields:
                    if any(field.source_column in WASTE_BRANCH_COLUMNS for field in fields_for_input):
                        st.caption("訳アリを「選択」にする場合は、理由・補足テキストも商品ごとに入力してください。")
                    edited_product_values = _render_product_change_editor(
                        selected_products,
                        fields_for_input,
                        editor_key=f"product_change_editor_{editor_context}",
                        initial_values=(
                            imported_registration.choice_values
                            if is_new_product and imported_registration is not None
                            else None
                        ),
                    )
                elif fields_for_input:
                    edited_product_values = pd.DataFrame(
                        [{} for _ in selected_products]
                    )
                stock_quantity = ""
                product_cost = ""
                new_product_extra_editor = None
                subscription_detail_editor = None
                sku_detail_editor = None
                sku_composition = ""
                sku_split_axes = []
                correction_backlog_values: dict[int, dict[str, str]] = {}
                if not is_new_product:
                    st.subheader("商品代の変更")
                    st.caption("すべての修正依頼で、商品代を変更するか変更しないかを選択してください。")
                    for product_index, product in enumerate(selected_products):
                        with st.container(border=True):
                            st.markdown(f"**{_product_label(product)}**")
                            cost_change_mode = st.segmented_control(
                                "商品代（税込・必須）",
                                ["商品代を変更する", "商品代を変更しない"],
                                default=None,
                                required=True,
                                key=f"correction_cost_mode_{editor_context}_{product_index}",
                                persist_state="session",
                            )
                            values = {"商品代変更": cost_change_mode or ""}
                            if cost_change_mode == "商品代を変更する":
                                values["商品代（税込）"] = st.text_input(
                                    "変更後の商品代（税込・必須）",
                                    placeholder="半角数字で入力",
                                    key=f"correction_cost_{editor_context}_{product_index}",
                                    persist_state="session",
                                )
                            correction_backlog_values[product_index] = values
                if not is_new_product and product_shape == "定期便":
                    st.subheader("定期便のお届け内容")
                    subscription_detail_editor = _render_subscription_detail_editor(
                        editor_context=editor_context,
                    )
                elif not is_new_product and product_shape == "SKU展開":
                    st.subheader("既存商品のSKU構成")
                    sku_detail_editor, sku_composition, sku_split_axes = _render_sku_detail_editor(
                        editor_context=editor_context,
                        is_new_product=False,
                        selected_products=selected_products,
                        municipality_products=municipality_products,
                        selected_business_name=business_name,
                    )
                if code_change_requested:
                    st.subheader("品番変更")
                    st.caption("新規登録と同様に、新品番を入力するか品番取得を依頼してください。")
                    for product_index, product in enumerate(selected_products):
                        with st.container(border=True):
                            st.markdown(f"**{_product_label(product)}**")
                            code_method = st.segmented_control(
                                "品番の用意方法（必須）",
                                ["新品番を入力する", "品番取得を依頼する"],
                                default="新品番を入力する",
                                key=f"compound_code_method_{editor_context}_{product_index}",
                                persist_state="session",
                            )
                            values = correction_backlog_values.setdefault(product_index, {})
                            values["品番取得方法"] = code_method or ""
                            if code_method == "新品番を入力する":
                                values["新品番"] = st.text_input(
                                    "新品番",
                                    key=f"compound_new_code_{editor_context}_{product_index}",
                                    persist_state="session",
                                )
                            correction_backlog_values[product_index] = values
                if is_new_product:
                    st.subheader("Backlog用の商品情報")
                    imported_extras = (
                        imported_registration.extra_values
                        if imported_registration is not None else {}
                    )
                    imported_stock = imported_extras.get("在庫数", "")
                    stock_mode_key = f"new_product_stock_mode_{editor_context}"
                    stock_value_key = f"new_product_stock_quantity_{editor_context}"
                    cost_key = f"new_product_cost_{editor_context}"
                    st.session_state.setdefault(
                        stock_mode_key,
                        "無制限" if imported_stock == "無制限" else "数量を入力",
                    )
                    st.session_state.setdefault(
                        stock_value_key,
                        "" if imported_stock == "無制限" else imported_stock,
                    )
                    st.session_state.setdefault(cost_key, imported_extras.get("商品代（税込）", ""))
                    stock_mode = st.segmented_control(
                        "在庫数（必須）",
                        options=["数量を入力", "無制限"],
                        key=stock_mode_key,
                        persist_state="session",
                    )
                    if stock_mode == "無制限":
                        stock_quantity = "無制限"
                    else:
                        stock_quantity = st.text_input(
                            "在庫数",
                            placeholder="半角数字で入力",
                            key=stock_value_key,
                            persist_state="session",
                        )
                    product_cost = st.text_input(
                        "商品代（税込・必須）",
                        placeholder="半角数字で入力",
                        key=cost_key,
                        persist_state="session",
                    )
                    shipping_period_mode = st.segmented_control(
                        "発送可能時期（必須）",
                        ["通年", "時期指定あり"],
                        default="通年",
                        key=f"shipping_period_mode_{editor_context}",
                        persist_state="session",
                    )
                    shipping_period_from = None
                    shipping_period_to = None
                    if shipping_period_mode == "時期指定あり":
                        period_columns = st.columns(2)
                        with period_columns[0]:
                            shipping_period_from = st.date_input(
                                "発送可能期間FROM", value=None, format="YYYY-MM-DD",
                                key=f"shipping_period_from_{editor_context}",
                                persist_state="session",
                            )
                        with period_columns[1]:
                            shipping_period_to = st.date_input(
                                "発送可能期間TO", value=None, format="YYYY-MM-DD",
                                key=f"shipping_period_to_{editor_context}",
                                persist_state="session",
                            )
                    st.subheader("共通追加情報")
                    st.caption(
                        "Nouless要件を参考にした補助情報です。チョイス商品マスタには書き込まず、Backlogと出力Excelへ保存します。"
                    )
                    extra_rows = [
                        {
                            "項目": label,
                            "必須区分": requirement,
                            "入力値": imported_extras.get(label, ""),
                            "選択肢": options.replace("|", " / "),
                        }
                        for label, requirement, options in NOULESS_REFERENCE_FIELDS
                        if label not in {"商品代（税込）", "在庫数"}
                    ]
                    new_product_extra_editor = st.data_editor(
                        pd.DataFrame(extra_rows),
                        hide_index=True,
                        disabled=["項目", "必須区分", "選択肢"],
                        num_rows="fixed",
                        key=f"new_product_extra_{editor_context}",
                    )
                    if product_shape == "定期便":
                        st.subheader("定期便のお届け内容")
                        subscription_rows = (
                            imported_registration.subscription_rows
                            if imported_registration is not None
                            and imported_registration.product_shape == "定期便"
                            else []
                        )
                        subscription_detail_editor = _render_subscription_detail_editor(
                            editor_context=editor_context, imported_rows=subscription_rows,
                        )
                    elif product_shape == "SKU展開":
                        st.subheader("SKU構成と商品一覧")
                        sku_rows = (
                            imported_registration.sku_rows
                            if imported_registration is not None
                            and imported_registration.product_shape == "SKU展開"
                            else []
                        )
                        sku_detail_editor, sku_composition, sku_split_axes = _render_sku_detail_editor(
                            editor_context=editor_context,
                            is_new_product=True,
                            selected_products=selected_products,
                            municipality_products=municipality_products,
                            selected_business_name=business_name,
                            imported_rows=sku_rows,
                        )
                elif correction_type in {"寄附額変更", "在庫数変更"}:
                    st.subheader("変更後の商品管理情報")
                    for product_index, product in enumerate(selected_products):
                        with st.container(border=True):
                            st.markdown(f"**{_product_label(product)}**")
                            values = correction_backlog_values.setdefault(product_index, {})
                            if correction_type == "在庫数変更":
                                stock_mode = st.segmented_control(
                                    "変更後の在庫",
                                    options=["数量を入力", "無制限"],
                                    default="数量を入力",
                                    key=f"correction_stock_mode_{editor_context}_{product_index}",
                                    persist_state="session",
                                )
                                values["在庫数"] = "無制限" if stock_mode == "無制限" else st.text_input(
                                    "変更後の在庫数",
                                    placeholder="半角数字で入力",
                                    key=f"correction_stock_value_{editor_context}_{product_index}",
                                    persist_state="session",
                                )
                            else:
                                code_method = st.segmented_control(
                                    "品番の変更方法",
                                    options=["品番を変更しない", "新品番を入力", "品番取得を外部依頼"],
                                    default="品番を変更しない",
                                    key=f"correction_code_method_{editor_context}_{product_index}",
                                    persist_state="session",
                                )
                                values["品番取得方法"] = code_method or ""
                                if code_method == "新品番を入力":
                                    values["新品番"] = st.text_input(
                                        "新品番",
                                        key=f"correction_new_code_{editor_context}_{product_index}",
                                        persist_state="session",
                                    )
                            correction_backlog_values[product_index] = values
                edited_allergy_values = None
                edited_temperature_values = None
                if temperature_change_requested:
                    st.subheader("温度帯")
                    edited_temperature_values = _render_temperature_editor(
                        selected_products,
                        editor_key=f"temperature_editor_{editor_context}",
                        initial_values=(
                            imported_registration.choice_values
                            if is_new_product and imported_registration is not None
                            else None
                        ),
                    )
                if allergy_change_requested:
                    st.subheader("アレルギー情報")
                    edited_allergy_values = _render_allergy_editor(
                        selected_products,
                        allergy_fields,
                        allergy_note_field,
                        editor_key=f"allergy_change_editor_{editor_context}",
                        initial_values=(
                            imported_registration.choice_values
                            if is_new_product and imported_registration is not None
                            else None
                        ),
                    )
                image_instruction: dict[int, str] = {}
                with st.expander("画像修正指示（任意・商品別）"):
                    st.caption(
                        "画像修正が必要な商品だけ入力してください。入力した商品をまとめて画像子課題にします。"
                    )
                    for product_index, product in enumerate(selected_products):
                        image_instruction[product_index] = st.text_area(
                            f"{_product_label(product)} の画像修正指示",
                            placeholder="例：1枚目を添付画像へ差し替え。背景を白に統一。",
                            key=f"request_image_instruction_{editor_context}_{product_index}",
                            persist_state="session",
                        )
                add_lines = st.button(
                    "選択した変更を明細に追加",
                    type="secondary",
                    key="add_selected_correction_lines",
                ) or st.session_state.pop("auto_add_pending", False)
            if add_lines:
                new_lines = []
                input_errors = []
                if edited_product_values is not None:
                    product_lines, input_errors = _build_product_change_lines(
                        products=selected_products,
                        selected_fields=selected_fields,
                        fields_for_input=fields_for_input,
                        edited_values=edited_product_values,
                        form_fields=form_fields,
                        image_instruction=image_instruction,
                    )
                    new_lines.extend(product_lines)
                # 商品タイプ・公開状態など、Excel用の自動設定を補完する。
                if is_new_product or correction_type == "複合的な修正":
                    automatic_values = {
                        "（必須）定期配送対応": "1" if product_shape == "定期便" else "0",
                        "（必須）別送対応": "1",
                        "（必須）表示有無": "0",
                    }
                    for product in selected_products:
                        new_lines = [
                            line for line in new_lines
                            if not (
                                line.product.product_id == product.product_id
                                and line.field_name in automatic_values
                            )
                        ]
                        for column, value in automatic_values.items():
                            field = find_request_form_field(form_fields, column)
                            new_lines.append(ProductCorrectionLine(
                                product=product,
                                field_name=column,
                                before_value=product.source_values().get(column, ""),
                                after_value=value,
                                instruction="【自動設定】",
                                column_number=product.source_column_number(column),
                                display_name=field.label if field else column,
                            ))
                if code_change_requested:
                    for product_index, product in enumerate(selected_products):
                        values = correction_backlog_values.get(product_index, {})
                        if values.get("品番取得方法") == "品番取得を依頼する":
                            new_lines.append(_build_product_code_request_line(product))
                        else:
                            new_code = values.get("新品番", "").strip()
                            if not new_code:
                                input_errors.append(f"{_product_label(product)}: 新品番")
                            else:
                                new_lines.extend(_build_management_code_lines(product, new_code))
                if not is_new_product:
                    for product_index, product in enumerate(selected_products):
                        values = correction_backlog_values.get(product_index, {})
                        cost_mode = values.get("商品代変更", "")
                        if not cost_mode:
                            input_errors.append(f"{_product_label(product)}: 商品代を変更する・しない")
                        elif cost_mode == "商品代を変更する":
                            cost_value = values.get("商品代（税込）", "").strip()
                            if not _is_nonnegative_integer(cost_value):
                                input_errors.append(f"{_product_label(product)}: 商品代（税込）")
                            else:
                                new_lines.append(ProductCorrectionLine(
                                    product=product,
                                    field_name=f"{BACKLOG_ONLY_PREFIX}商品代（税込）",
                                    before_value=product.source_values().get("商品代（税込）", ""),
                                    after_value=cost_value,
                                    display_name="商品代",
                                ))
                if is_new_product:
                    if stock_quantity != "無制限" and not _is_nonnegative_integer(stock_quantity):
                        input_errors.append("新規商品: 在庫数")
                    if not _is_nonnegative_integer(product_cost):
                        input_errors.append("新規商品: 商品代（税込）")
                    registration_product = (
                        new_lines[0].product if new_lines else selected_products[0]
                    )
                    if new_product_code_method == "品番取得を依頼する":
                        new_lines.append(ProductCorrectionLine(
                            product=registration_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}品番取得依頼",
                            before_value="",
                            after_value="品番取得を依頼",
                            display_name="品番取得依頼（Backlogのみ）",
                        ))
                    if shipping_period_mode == "時期指定あり":
                        if not shipping_period_from or not shipping_period_to:
                            input_errors.append("新規商品: 発送可能期間FROM・TO")
                        elif shipping_period_from > shipping_period_to:
                            input_errors.append("新規商品: 発送可能期間の前後関係")
                        shipping_period_value = (
                            f"{shipping_period_from.isoformat()}～{shipping_period_to.isoformat()}"
                            if shipping_period_from and shipping_period_to else ""
                        )
                    else:
                        shipping_period_value = "通年"
                    if shipping_period_value:
                        new_lines.append(ProductCorrectionLine(
                            product=registration_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}発送可能時期",
                            before_value="",
                            after_value=shipping_period_value,
                            display_name="発送可能時期（Backlogのみ）",
                        ))
                    new_lines.append(ProductCorrectionLine(
                        product=registration_product,
                        field_name=f"{BACKLOG_ONLY_PREFIX}商品形態",
                        before_value="",
                        after_value=product_shape,
                        display_name="商品形態（Backlogのみ）",
                    ))
                    extra_value_map = {}
                    if new_product_extra_editor is not None:
                        extra_value_map = {
                            _table_text(row["項目"]): _table_text(row["入力値"])
                            for _, row in new_product_extra_editor.iterrows()
                            if _table_text(row["入力値"])
                        }
                    for label, value in extra_value_map.items():
                        new_lines.append(ProductCorrectionLine(
                            product=registration_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}{label}",
                            before_value="",
                            after_value=value,
                            display_name=f"{label}（Backlogのみ）",
                        ))
                    subscription_rows_for_save = []
                    sku_rows_for_save = []
                    if product_shape == "定期便" and subscription_detail_editor is not None:
                        subscription_rows_for_save = [
                            {key: _table_text(value) for key, value in row.items()}
                            for _, row in subscription_detail_editor.iterrows()
                            if any(_table_text(value) for key, value in row.items() if key != "お届け回")
                        ]
                        if len(subscription_rows_for_save) < 2:
                            input_errors.append("定期便: 2回以上のお届け内容")
                        for index, row in enumerate(subscription_rows_for_save, start=1):
                            if not row.get("お届け時期") or not row.get("お届け内容"):
                                input_errors.append(f"定期便: 第{index}回のお届け時期・内容")
                            new_lines.append(ProductCorrectionLine(
                                product=registration_product,
                                field_name=f"{BACKLOG_ONLY_PREFIX}定期便第{index}回",
                                before_value="",
                                after_value="｜".join(
                                    filter(None, (
                                        row.get("お届け時期"), row.get("お届け内容"),
                                        row.get("内容量"), row.get("数量"),
                                        row.get("温度帯"), row.get("補足"),
                                    ))
                                ),
                                display_name=f"定期便 第{index}回（Backlogのみ）",
                            ))
                    elif product_shape == "SKU展開" and sku_detail_editor is not None:
                        sku_rows_for_save = [
                            {
                                key: (value if key == "チョイスマスタ値" else _table_text(value))
                                for key, value in row.items()
                            }
                            for _, row in sku_detail_editor.iterrows()
                            if any(_table_text(value) for value in row.values())
                        ]
                        if len(sku_rows_for_save) < 2:
                            input_errors.append("SKU展開: 2件以上のSKU")
                        if not sku_split_axes:
                            input_errors.append("SKU展開: SKUを分ける項目")
                        new_lines.append(ProductCorrectionLine(
                            product=registration_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}SKU設定",
                            before_value="",
                            after_value=(
                                f"構成：{sku_composition} ／ SKU数：{len(sku_rows_for_save)} ／ "
                                f"分け方：{' → '.join(sku_split_axes)}"
                            ),
                            display_name="SKU設定（Backlogのみ）",
                        ))
                        for index, row in enumerate(sku_rows_for_save, start=1):
                            if row.get("商品区分") == "新規" and row.get("品番取得方法") != "品番取得を依頼する" and not row.get("SKU品番"):
                                input_errors.append(f"SKU展開: SKU{index}の品番または品番取得依頼")
                            if not row.get("商品名") or not row.get("バリエーション名"):
                                input_errors.append(f"SKU展開: SKU{index}の商品名・バリエーション名")
                            if row.get("商品区分") == "新規":
                                if not _is_nonnegative_integer(row.get("商品代（税込）", "")):
                                    input_errors.append(f"SKU展開: SKU{index}の商品代（税込）")
                            elif row.get("商品代変更") == "商品代を変更する":
                                if not _is_nonnegative_integer(row.get("商品代（税込）", "")):
                                    input_errors.append(f"SKU展開: SKU{index}の変更後商品代（税込）")
                            for axis in sku_split_axes:
                                axis_column = "その他の分け方" if axis == "その他" else axis
                                if not row.get(axis_column):
                                    input_errors.append(f"SKU展開: SKU{index}の{axis}")
                            detail_text = " ／ ".join(
                                f"{label}：{row.get(column)}"
                                for label, column in (
                                    ("登録区分", "登録区分"), ("元商品区分", "商品区分"), ("既存商品", "既存商品"),
                                    ("品番取得", "品番取得方法"), ("品番", "SKU品番"),
                                    ("商品名", "商品名"), ("バリエーション", "バリエーション名"),
                                    ("品種", "品種"), ("容量", "容量"), ("色", "色"),
                                    ("数量", "数量"), ("配送月", "配送月"),
                                    ("その他", "その他の分け方"), ("商品代変更", "商品代変更"),
                                    ("商品代（税込）", "商品代（税込）"),
                                    ("寄附額", "寄附額"), ("在庫数", "在庫数"),
                                    ("温度帯", "温度帯"), ("補足", "補足"),
                                ) if row.get(column)
                            )
                            new_lines.append(ProductCorrectionLine(
                                product=registration_product,
                                field_name=f"{BACKLOG_ONLY_PREFIX}SKU{index}",
                                before_value="",
                                after_value=detail_text,
                                display_name=f"SKU {index}（Backlogのみ）",
                            ))
                elif correction_type in {"寄附額変更", "在庫数変更"}:
                    for product_index, product in enumerate(selected_products):
                        values = correction_backlog_values.get(product_index, {})
                        if correction_type == "在庫数変更":
                            stock_value = values.get("在庫数", "").strip()
                            if stock_value != "無制限" and not _is_nonnegative_integer(stock_value):
                                input_errors.append(f"{_product_label(product)}: 変更後の在庫数")
                            elif stock_value:
                                new_lines.append(ProductCorrectionLine(
                                    product=product,
                                    field_name=f"{BACKLOG_ONLY_PREFIX}在庫数",
                                    before_value="",
                                    after_value=stock_value,
                                    display_name="在庫数（Backlogのみ）",
                                ))
                        else:
                            code_method = values.get("品番取得方法", "")
                            if code_method == "品番取得を外部依頼":
                                new_lines.append(_build_product_code_request_line(product))
                            elif code_method == "新品番を入力":
                                new_code = values.get("新品番", "").strip()
                                if not new_code:
                                    input_errors.append(f"{_product_label(product)}: 新品番")
                                else:
                                    source_values = product.source_values()
                                    old_code = source_values.get(MANAGEMENT_CODE_COLUMN, "")
                                    for field_name, display_name in (
                                        (MANAGEMENT_CODE_COLUMN, "品番"),
                                        (LINK_CODE_COLUMN, "連携コード"),
                                    ):
                                        new_lines.append(ProductCorrectionLine(
                                            product=product,
                                            field_name=field_name,
                                            before_value=source_values.get(field_name, ""),
                                            after_value=new_code,
                                            display_name=display_name,
                                            column_number=product.source_column_number(field_name),
                                        ))
                                    base_name = product.product_name
                                    if old_code and base_name.endswith(f" {old_code}"):
                                        base_name = base_name[: -(len(old_code) + 1)]
                                    revised_name = f"{base_name} {new_code}".strip()
                                    if revised_name != product.product_name:
                                        new_lines.append(ProductCorrectionLine(
                                            product=product,
                                            field_name=PRODUCT_NAME_COLUMN,
                                            before_value=product.product_name,
                                            after_value=revised_name,
                                            display_name="商品名",
                                            column_number=product.source_column_number(PRODUCT_NAME_COLUMN),
                                        ))
                if not is_new_product and product_shape == "定期便" and subscription_detail_editor is not None:
                    detail_product = selected_products[0]
                    rows = [
                        {
                            key: (value if key == "チョイスマスタ値" else _table_text(value))
                            for key, value in row.items()
                        }
                        for _, row in subscription_detail_editor.iterrows()
                    ]
                    for index, row in enumerate(rows, start=1):
                        if not row.get("お届け時期") or not row.get("お届け内容"):
                            input_errors.append(f"定期便: 第{index}回のお届け時期・内容")
                        new_lines.append(ProductCorrectionLine(
                            product=detail_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}定期便第{index}回",
                            before_value="",
                            after_value=" ／ ".join(
                                f"{label}：{row.get(column)}"
                                for label, column in (
                                    ("時期", "お届け時期"), ("内容", "お届け内容"),
                                    ("内容量", "内容量"), ("数量", "数量"),
                                    ("温度帯", "温度帯"), ("補足", "補足"),
                                ) if row.get(column)
                            ),
                            display_name=f"定期便 第{index}回（Backlogのみ）",
                        ))
                elif not is_new_product and product_shape == "SKU展開" and sku_detail_editor is not None:
                    detail_product = selected_products[0]
                    rows = [
                        {key: _table_text(value) for key, value in row.items()}
                        for _, row in sku_detail_editor.iterrows()
                    ]
                    if not sku_split_axes:
                        input_errors.append("SKU展開: SKUを分ける項目")
                    new_lines.append(ProductCorrectionLine(
                        product=detail_product,
                        field_name=f"{BACKLOG_ONLY_PREFIX}SKU設定",
                        before_value="",
                        after_value=f"既存商品のみ ／ SKU数：{len(rows)} ／ 分け方：{' → '.join(sku_split_axes)}",
                        display_name="SKU設定（Backlogのみ）",
                    ))
                    for index, row in enumerate(rows, start=1):
                        if not row.get("既存商品"):
                            input_errors.append(f"SKU展開: SKU{index}の既存商品")
                        if row.get("商品代変更") == "商品代を変更する" and not _is_nonnegative_integer(
                            row.get("商品代（税込）", "")
                        ):
                            input_errors.append(f"SKU展開: SKU{index}の変更後商品代（税込）")
                        for axis in sku_split_axes:
                            axis_column = "その他の分け方" if axis == "その他" else axis
                            if not row.get(axis_column):
                                input_errors.append(f"SKU展開: SKU{index}の{axis}")
                        new_lines.append(ProductCorrectionLine(
                            product=detail_product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}SKU{index}",
                            before_value="",
                            after_value=" ／ ".join(
                                f"{label}：{row.get(column)}"
                                for label, column in (
                                    ("登録区分", "登録区分"), ("元商品区分", "商品区分"),
                                    ("既存商品", "既存商品"), ("品番", "SKU品番"),
                                    ("商品名", "商品名"), ("バリエーション", "バリエーション名"),
                                    ("品種", "品種"), ("容量", "容量"), ("色", "色"),
                                    ("数量", "数量"), ("配送月", "配送月"),
                                    ("その他", "その他の分け方"), ("商品代変更", "商品代変更"),
                                    ("商品代（税込）", "商品代（税込）"),
                                    ("寄附額", "寄附額"), ("在庫数", "在庫数"),
                                    ("温度帯", "温度帯"), ("補足", "補足"),
                                ) if row.get(column)
                            ),
                            display_name=f"SKU {index}（Backlogのみ）",
                        ))
                if edited_temperature_values is not None:
                    temperature_lines, temperature_errors = _build_temperature_change_lines(
                        products=selected_products,
                        edited_values=edited_temperature_values,
                    )
                    new_lines.extend(temperature_lines)
                    input_errors.extend(temperature_errors)
                if edited_allergy_values is not None:
                    new_lines.extend(_build_allergy_change_lines(
                        products=selected_products,
                        allergy_fields=allergy_fields,
                        allergy_note_field=allergy_note_field,
                        edited_values=edited_allergy_values,
                    ))
                for product_index, product in enumerate(selected_products):
                    instruction = image_instruction.get(product_index, "").strip()
                    if not instruction:
                        continue
                    matching_indexes = [
                        index for index, line in enumerate(new_lines)
                        if line.product.product_id == product.product_id
                        and line.product.municipality_id == product.municipality_id
                    ]
                    if matching_indexes:
                        target_index = matching_indexes[0]
                        new_lines[target_index] = replace(
                            new_lines[target_index], image_instruction=instruction
                        )
                    else:
                        new_lines.append(ProductCorrectionLine(
                            product=product,
                            field_name=f"{BACKLOG_ONLY_PREFIX}画像修正",
                            before_value="",
                            after_value="画像修正あり",
                            image_instruction=instruction,
                            display_name="画像修正（Backlogのみ）",
                        ))
                if input_errors:
                    st.session_state.pop("auto_save_ready", None)
                    st.error("必須項目を入力してください: " + " / ".join(input_errors))
                elif correction_lines and any(
                    line.product.municipality_id != target_municipality_id
                    for line in correction_lines
                ):
                    st.error("追加済み明細とは別の自治体です。先に明細をクリアしてください。")
                elif not new_lines:
                    st.session_state.pop("auto_save_ready", None)
                    st.warning("現在値と異なる変更後値を入力または選択してください。")
                else:
                    st.session_state.correction_lines.extend(new_lines)
                    if is_new_product:
                        st.session_state.new_product_backlog_values = {
                            "在庫数": stock_quantity,
                            "商品代（税込）": product_cost,
                        }
                        st.session_state.new_product_excel_values = {
                            "商品形態": product_shape,
                            "追加情報": extra_value_map,
                            "定期便明細": subscription_rows_for_save,
                            "SKU明細": sku_rows_for_save,
                        }
                    st.session_state.product_change_editor_version += 1
                    st.success("変更明細を追加しました。")
                    st.rerun()
        else:
            st.info("変更する項目またはアレルギー情報の変更を選択してください。")
    elif request_unit == "商品単位":
        st.info("事業者と商品を選択してください。")

    if correction_lines:
        st.divider()
        st.write(f"追加済み明細：{len(correction_lines)}件")
        st.dataframe(
            [
                {
                    "品番": line.product.source_values().get("管理コード", ""),
                    "商品名": line.product.product_name,
                    "修正項目": line.display_name or line.field_name,
                    "修正前値": line.before_value,
                    "修正後値": line.after_value,
                }
                for line in correction_lines
            ],
            hide_index=True,
            height=min(160 + 35 * len(correction_lines), 460),
        )
        if is_new_product:
            choice_export_values = {
                line.field_name: line.after_value
                for line in correction_lines
                if not line.field_name.startswith(BACKLOG_ONLY_PREFIX)
            }
            excel_values = st.session_state.get("new_product_excel_values", {})
            export_extras = dict(excel_values.get("追加情報", {}))
            export_extras.update(st.session_state.get("new_product_backlog_values", {}))
            st.download_button(
                "入力済みExcelをダウンロード",
                data=build_registration_template(
                    form_fields,
                    excel_values.get("商品形態", product_shape),
                    choice_values=choice_export_values,
                    extra_values=export_extras,
                    subscription_rows=excel_values.get("定期便明細", []),
                    sku_rows=excel_values.get("SKU明細", []),
                ),
                file_name=f"新規商品登録_{excel_values.get('商品形態', product_shape)}_入力済み.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:",
                key="download_completed_registration_excel",
            )
        with st.form("edit_added_correction_lines", border=True, enter_to_submit=False):
            st.caption("追加済み明細を再編集する場合は、変更後値または画像修正指示を修正して反映してください。")
            editable_lines = pd.DataFrame([
                {
                    "品番": line.product.source_values().get("管理コード", ""),
                    "商品名": line.product.product_name,
                    "変更項目": line.display_name or line.field_name,
                    "現在値": line.before_value,
                    "変更後値": line.after_value,
                    "画像修正指示": line.image_instruction,
                }
                for line in correction_lines
            ])
            edited_lines = st.data_editor(
                editable_lines,
                key=f"saved_correction_lines_{st.session_state.product_change_editor_version}",
                disabled=["品番", "商品名", "変更項目", "現在値"],
                hide_index=True,
                num_rows="fixed",
            )
            apply_edited_lines = st.form_submit_button("明細の変更を反映")
        if apply_edited_lines:
            st.session_state.correction_lines = [
                replace(
                    line,
                    after_value=str(edited_row["変更後値"] or "").strip(),
                    image_instruction=str(edited_row["画像修正指示"] or "").strip(),
                )
                for line, (_, edited_row) in zip(
                    correction_lines, edited_lines.iterrows()
                )
            ]
            st.session_state.product_change_editor_version += 1
            st.success("変更明細を更新しました。")
            st.rerun()
        if st.button("追加済み明細をすべてクリア", type="secondary"):
            st.session_state.correction_lines = []
            st.rerun()

    st.divider()
    st.subheader("依頼内容と担当")
    backlog_assignee_name = ""
    backlog_assignee_id = ""
    backlog_notified_user_ids: list[str] = []
    target_custom_fields = []
    target_project_users = []
    target_project_teams = []
    requester = ""
    if create_backlog_issue and selected_issue_type is not None:
        try:
            target_project_users = get_project_users(
                _load_backlog_users(config_spreadsheet_id, str(credentials_path)),
                target_municipality_id,
            )
        except Exception:
            target_project_users = []
            st.warning("Backlog担当者候補を読み込めません。担当者は未指定で起票できます。")
        try:
            target_project_teams = _load_backlog_teams(target_backlog_config)
        except Exception:
            target_project_teams = []
            st.warning("Backlogチームを読み込めません。個人の通知先は選択できます。")
        if target_project_users:
            requester_user = st.selectbox(
                "依頼者（Backlogメンバーから選択・記録用）",
                options=target_project_users,
                format_func=lambda user: user.display_name,
                key=f"requester_user_{target_municipality_id}",
            )
            requester = requester_user.name
            assignee_user = st.selectbox(
                "Backlog担当者（任意）",
                options=[None] + target_project_users,
                format_func=lambda user: "未指定" if user is None else user.display_name,
                key=f"assignee_user_{target_municipality_id}",
            )
            if assignee_user is not None:
                backlog_assignee_name = assignee_user.name
                backlog_assignee_id = assignee_user.user_id
            code_action_required = any(
                line.field_name == MANAGEMENT_CODE_COLUMN
                or line.field_name.endswith("品番取得依頼")
                for line in correction_lines
            )
            forced_assignee_id = (
                target_backlog_config.product_code_assignee_id
                if code_action_required and target_backlog_config else ""
            )
            if forced_assignee_id:
                forced_assignee = next(
                    (user for user in target_project_users if user.user_id == forced_assignee_id),
                    None,
                )
                backlog_assignee_id = forced_assignee_id
                backlog_assignee_name = forced_assignee.name if forced_assignee else backlog_assignee_name
                st.info(
                    "品番取得・変更があるため、自治体マスタの品番担当者を自動設定します。"
                )
            forced_notification_ids = set(
                target_backlog_config.product_code_notified_user_ids
                if code_action_required and target_backlog_config else ()
            )
            notification_options = [
                ("user", user.user_id, user.display_name, (user.user_id,))
                for user in target_project_users
            ] + [
                ("team", team.team_id, team.display_name, team.member_user_ids)
                for team in target_project_teams
            ]
            notification_targets = st.multiselect(
                "Backlog通知先・チーム（任意）",
                options=notification_options,
                default=[
                    option for option in notification_options
                    if option[0] == "user" and option[1] in forced_notification_ids
                ],
                format_func=lambda option: option[2],
                key=f"notified_targets_{target_municipality_id}",
                help="@チームを選ぶと、そのチームの所属メンバー全員へ通知します。",
            )
            backlog_notified_user_ids = list(dict.fromkeys(
                [
                    user_id
                    for option in notification_targets
                    for user_id in option[3]
                ] + list(forced_notification_ids)
            ))
        else:
            requester = st.text_input("依頼者", key="requester")
        try:
            target_custom_fields = get_applicable_custom_fields(
                _load_backlog_custom_fields(
                    config_spreadsheet_id, str(credentials_path)
                ),
                target_municipality_id,
                selected_issue_type.name,
                required_only=False,
            )
        except Exception:
            st.warning("Backlogカスタム属性を読み込めません。")
    else:
        requester = st.text_input("依頼者", key="requester")

    request_note = st.text_area(
        "対応内容・備考",
        placeholder="何を、どのように対応するかを補足してください。",
        key="request_note",
    )
    box_url = st.text_input(
        "BOX URL（任意）",
        placeholder="画像素材・調書を保存したBOXフォルダのURL",
        key="request_box_url",
    )
    uploaded_files = st.file_uploader(
        "添付ファイル（任意・複数可）",
        accept_multiple_files=True,
        max_upload_size=20,
        key="request_uploaded_files",
        help="依頼時にBacklog親課題へ添付します。自動生成する変更後データExcelとは別に添付されます。",
    )
    uploaded_files = list(uploaded_files or [])
    if registration_source_file is not None and all(
        file.name != registration_source_file.name for file in uploaded_files
    ):
        uploaded_files.append(registration_source_file)
        st.caption("取り込んだ公式ExcelもBacklog親課題へ添付します。")
    backlog_priority_id = "3"
    backlog_start_date = None
    backlog_due_date = None
    custom_field_values = {}
    if create_backlog_issue:
        st.caption("Backlogの基本項目")
        priority_options = {
            "高": "2",
            "中": "3",
            "低": "4",
        }
        priority_label = st.selectbox(
            "優先度",
            options=list(priority_options),
            index=1,
            key=f"backlog_priority_{target_municipality_id}",
        )
        backlog_priority_id = priority_options[priority_label]
        start_column, due_column = st.columns(2)
        with start_column:
            backlog_start_date = st.date_input(
                "開始日（任意）",
                value=None,
                format="YYYY-MM-DD",
                key=f"backlog_start_date_{target_municipality_id}",
            )
        with due_column:
            backlog_due_date = st.date_input(
                "期限日（任意）",
                value=None,
                format="YYYY-MM-DD",
                key=f"backlog_due_date_{target_municipality_id}",
            )
    if create_backlog_issue and target_custom_fields:
        st.caption("Backlogカスタム属性")
        for custom_field in target_custom_fields:
            field_key = (
                f"backlog_custom_{target_municipality_id}_"
                f"{selected_issue_type.issue_type_id}_{custom_field.field_id}"
            )
            custom_field_values[custom_field.name] = _render_backlog_custom_field(
                custom_field, field_key
            )

    image_child_assignee_id = ""
    image_child_priority_id = backlog_priority_id
    image_child_start_date = None
    image_child_due_date = None
    image_child_custom_fields = []
    image_child_custom_values = {}
    has_image_request = any(line.image_instruction.strip() for line in correction_lines)
    if create_backlog_issue and has_image_request and issue_type_names:
        st.divider()
        with st.container(border=True):
            st.subheader("画像子課題情報")
            st.caption("画像修正がある場合だけ使用します。親課題とは別に担当者・課題種別・基本項目を設定できます。")
            configured_child_name = (
                target_image_issue_type.name if target_image_issue_type is not None else ""
            )
            child_type_index = (
                issue_type_names.index(configured_child_name)
                if configured_child_name in issue_type_names else 0
            )
            image_child_issue_type_name = st.selectbox(
                "子課題の課題種別",
                options=issue_type_names,
                index=child_type_index,
                key=f"image_child_issue_type_{target_municipality_id}",
            )
            target_image_issue_type = issue_type_by_name[image_child_issue_type_name]
            if target_project_users:
                child_assignee = st.selectbox(
                    "子課題の担当者（任意）",
                    options=[None] + target_project_users,
                    format_func=lambda user: "未指定" if user is None else user.display_name,
                    key=f"image_child_assignee_{target_municipality_id}",
                )
                if child_assignee is not None:
                    image_child_assignee_id = child_assignee.user_id
            child_priority_label = st.selectbox(
                "子課題の優先度",
                options=list(priority_options),
                index=1,
                key=f"image_child_priority_{target_municipality_id}",
            )
            image_child_priority_id = priority_options[child_priority_label]
            child_start_column, child_due_column = st.columns(2)
            with child_start_column:
                image_child_start_date = st.date_input(
                    "子課題の開始日（任意）",
                    value=None,
                    format="YYYY-MM-DD",
                    key=f"image_child_start_date_{target_municipality_id}",
                )
            with child_due_column:
                image_child_due_date = st.date_input(
                    "子課題の期限日（任意）",
                    value=None,
                    format="YYYY-MM-DD",
                    key=f"image_child_due_date_{target_municipality_id}",
                )
            try:
                image_child_custom_fields = get_applicable_custom_fields(
                    _load_backlog_custom_fields(
                        config_spreadsheet_id, str(credentials_path)
                    ),
                    target_municipality_id,
                    target_image_issue_type.name,
                    required_only=False,
                )
            except Exception:
                st.warning("画像子課題のカスタム属性を読み込めません。")
            if image_child_custom_fields:
                st.caption("画像子課題のカスタム属性")
                for custom_field in image_child_custom_fields:
                    field_key = (
                        f"image_child_custom_{target_municipality_id}_"
                        f"{target_image_issue_type.issue_type_id}_{custom_field.field_id}"
                    )
                    image_child_custom_values[custom_field.name] = _render_backlog_custom_field(
                        custom_field, field_key
                    )

    save_request = st.button(
        "依頼を保存", type="primary", width="stretch"
    ) or st.session_state.pop("auto_save_ready", False)
    if save_request:
        try:
            if selected_issue_type is None or target_backlog_config is None:
                raise ValueError("Backlog課題種別または接続設定を確認してください。")
            if (request_unit == "商品単位" or is_new_product) and not correction_lines:
                if "add_lines" in locals() and not add_lines:
                    st.session_state.auto_add_pending = True
                    st.session_state.auto_save_ready = True
                    st.info("入力中の内容を明細へ自動追加してから、課題登録を続けます。")
                    st.rerun()
                raise ValueError("入力内容から追加できる変更明細がありません。入力項目を確認してください。")
            if not is_new_product and request_unit != "商品単位" and not request_note.strip():
                raise ValueError("自治体対応・その他の依頼は、対応内容・備考を入力してください。")
            if not requester.strip():
                raise ValueError("依頼者を入力してください。")
            if work_category == "施策" and selected_policy is None:
                raise ValueError("施策種別と具体内容を選択してください。")
            if backlog_start_date and backlog_due_date and backlog_start_date > backlog_due_date:
                raise ValueError("期限日は開始日以降を指定してください。")
            if (
                image_child_start_date and image_child_due_date
                and image_child_start_date > image_child_due_date
            ):
                raise ValueError("画像子課題の期限日は開始日以降を指定してください。")
            custom_field_parameters = build_custom_field_parameters(
                target_custom_fields, custom_field_values
            )
            image_child_custom_parameters = build_custom_field_parameters(
                image_child_custom_fields, image_child_custom_values
            )
            editing_source_request_id = str(
                st.session_state.get("editing_source_request_id", "")
            ).strip()
            editing_source_backlog_issue_key = str(
                st.session_state.get("editing_source_backlog_issue_key", "")
            ).strip()
            stored_note = request_note
            if box_url.strip():
                stored_note = "\n\n".join(
                    value for value in (
                        stored_note.strip(),
                        "【関連ファイル】\nBOX URL：" + box_url.strip(),
                    ) if value
                )
            if is_new_product:
                backlog_values = st.session_state.get("new_product_backlog_values", {})
                backlog_only_note = "\n".join([
                    "【商品管理情報（チョイスマスタ非連携）】",
                    f"在庫数：{backlog_values.get('在庫数', '')}",
                    f"商品代（税込）：{backlog_values.get('商品代（税込）', '')}円",
                ])
                stored_note = "\n\n".join(
                    value for value in (stored_note.strip(), backlog_only_note) if value
                )
            if editing_source_request_id:
                revision_marker = f"改訂元依頼ID：{editing_source_request_id}"
                stored_note = "\n".join(
                    value for value in (revision_marker, stored_note.strip()) if value
                )
            request = create_product_correction_request(
                requester=requester,
                municipality_id=target_municipality_id,
                municipality_name=municipality_names[target_municipality_id],
                note=stored_note,
                backlog_assignee_name=backlog_assignee_name,
                backlog_assignee_id=backlog_assignee_id,
                request_unit="新規商品登録" if is_new_product else request_unit,
                work_category=work_category,
                policy_id=selected_policy.policy_id if selected_policy else "",
                policy_type=selected_policy.policy_type if selected_policy else "",
                policy_content=selected_policy.content if selected_policy else "",
                policy_detail=selected_policy.detail if selected_policy else "",
                backlog_issue_type=selected_issue_type.name if selected_issue_type else "",
            )
            result = save_product_correction_request(
                spreadsheet_id=product_spreadsheet_id,
                credentials_path=credentials_path,
                request=request,
                lines=correction_lines,
            )
            comparison_path = None
            master_correction_lines = [
                line for line in correction_lines
                if not line.field_name.startswith(BACKLOG_ONLY_PREFIX)
            ]
            if master_correction_lines:
                try:
                    comparison_path = generate_revision_comparison_workbook(
                        request, master_correction_lines
                    )
                    st.session_state.latest_comparison_path = str(comparison_path)
                except Exception:
                    st.warning(
                        f"依頼ID：{result.request_id} は保存しましたが、変更後データExcelを生成できませんでした。"
                    )
            st.session_state.correction_lines = []
            st.session_state.pop("new_product_backlog_values", None)
            st.session_state.pop("new_product_excel_values", None)
            st.session_state.pop("registration_excel_import", None)
            st.session_state.pop("registration_excel_fingerprint", None)
            try:
                generated_summary, description = build_backlog_issue_content(
                    request, correction_lines
                )
                issue_summary = backlog_issue_title.strip() or generated_summary
                if editing_source_backlog_issue_key:
                    issue = update_issue(
                        config=target_backlog_config,
                        issue_key=editing_source_backlog_issue_key,
                        summary=issue_summary,
                        description=description,
                        priority_id=backlog_priority_id,
                        start_date=backlog_start_date,
                        due_date=backlog_due_date,
                        assignee_id=backlog_assignee_id,
                        notified_user_ids=backlog_notified_user_ids,
                        custom_field_parameters=custom_field_parameters,
                    )
                else:
                    issue = create_issue(
                        config=target_backlog_config,
                        issue_type_id=selected_issue_type.issue_type_id,
                        summary=issue_summary,
                        description=description,
                        priority_id=backlog_priority_id,
                        start_date=backlog_start_date,
                        due_date=backlog_due_date,
                        assignee_id=backlog_assignee_id,
                        notified_user_ids=backlog_notified_user_ids,
                        custom_field_parameters=custom_field_parameters,
                    )
            except Exception:
                st.warning(
                    f"依頼ID：{result.request_id} は商品情報マスタへ保存しましたが、"
                    "Backlogへの起票に失敗しました。再送前に依頼IDを確認してください。"
                )
                return
            try:
                update_product_request_backlog_parent(
                    spreadsheet_id=product_spreadsheet_id,
                    credentials_path=credentials_path,
                    request_id=result.request_id,
                    issue_key=issue.issue_key,
                    issue_url=issue.issue_url,
                )
            except Exception:
                st.warning(
                    f"Backlog課題 {issue.issue_key} は起票済みですが、"
                    f"依頼ID：{result.request_id} への記録に失敗しました。"
                )
                return

            comparison_attached = False
            if comparison_path is not None:
                try:
                    attach_file_to_issue(
                        config=target_backlog_config,
                        issue_key=issue.issue_key,
                        file_path=comparison_path,
                    )
                    comparison_attached = True
                except Exception:
                    st.warning(
                        f"Backlog課題 {issue.issue_key} は起票済みですが、変更後データExcelの添付に失敗しました。"
                    )
            uploaded_attachment_count = 0
            if uploaded_files:
                try:
                    for uploaded_path in _save_uploaded_attachments(
                        result.request_id, list(uploaded_files)
                    ):
                        attach_file_to_issue(
                            config=target_backlog_config,
                            issue_key=issue.issue_key,
                            file_path=uploaded_path,
                        )
                        uploaded_attachment_count += 1
                except Exception:
                    st.warning(
                        f"Backlog課題 {issue.issue_key} は起票済みですが、追加添付ファイルの一部を添付できませんでした。"
                    )
            image_lines = [line for line in correction_lines if line.image_instruction.strip()]
            attachment_messages = []
            if comparison_attached:
                attachment_messages.append("変更後データExcelを添付しました。")
            if uploaded_attachment_count:
                attachment_messages.append(f"追加添付ファイル {uploaded_attachment_count}件を添付しました。")
            attachment_message = " ".join(attachment_messages)
            if not image_lines:
                st.success(f"依頼を保存し、Backlog課題 {issue.issue_key} を起票しました。{attachment_message}")
            elif target_image_issue_type is None or not issue.issue_id:
                st.warning(
                    f"Backlog課題 {issue.issue_key} を起票しましたが、画像子課題は未起票です。"
                    f"{attachment_message}"
                )
            else:
                child_success_count = 0
                child_failure_count = 0
                try:
                    child_summary, child_description = build_image_backlog_issue_content(
                        request, image_lines
                    )
                    child_issue = create_issue(
                        config=target_backlog_config,
                        issue_type_id=target_image_issue_type.issue_type_id,
                        summary=child_summary,
                        description=child_description,
                        priority_id=image_child_priority_id,
                        start_date=image_child_start_date,
                        due_date=image_child_due_date,
                        parent_issue_id=issue.issue_id,
                        assignee_id=image_child_assignee_id,
                        custom_field_parameters=image_child_custom_parameters,
                    )
                    for image_request_id in result.image_request_ids:
                        update_image_request_backlog_child(
                            spreadsheet_id=product_spreadsheet_id,
                            credentials_path=credentials_path,
                            image_request_id=image_request_id,
                            issue_key=child_issue.issue_key,
                            issue_url=child_issue.issue_url,
                        )
                    child_success_count = 1
                except Exception:
                    child_failure_count = 1
                if child_failure_count:
                    st.warning(
                        f"Backlog親課題 {issue.issue_key} を起票しました。"
                        f"画像子課題：成功 {child_success_count}件 / 失敗 {child_failure_count}件。{attachment_message}"
                    )
                else:
                    st.success(
                        f"依頼を保存し、Backlog親課題 {issue.issue_key} と"
                        f"画像子課題 1件を起票しました。{attachment_message}"
                    )
            if editing_source_request_id:
                st.session_state.pop("editing_source_request_id", None)
                st.session_state.pop("editing_source_backlog_issue_key", None)
        except Exception as error:
            st.error("商品修正依頼を保存できませんでした。")
            st.exception(error)

    latest_comparison_path_value = st.session_state.get("latest_comparison_path")
    latest_comparison_path = (
        Path(latest_comparison_path_value) if latest_comparison_path_value else None
    )
    if latest_comparison_path and latest_comparison_path.is_file():
        st.download_button(
            "最新の変更後データExcelをダウンロード",
            data=latest_comparison_path.read_bytes(),
            file_name=latest_comparison_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )


def render_backlog_status_sync(
    *,
    config_spreadsheet_id: str,
    product_spreadsheet_id: str,
    credentials_path: Path,
) -> None:
    """手動の状態同期は依頼フォームの上部から呼び出す。"""

    try:
        active_backlog_configs = backlog_configs_by_municipality_id(
            _load_backlog_configs(config_spreadsheet_id, str(credentials_path))
        )
    except Exception:
        return
    if not active_backlog_configs:
        return
    if st.button("Backlog状態を同期", type="secondary"):
        try:
            with st.spinner("Backlogの状態を同期しています。"):
                sync_result = sync_product_request_statuses(
                    spreadsheet_id=product_spreadsheet_id,
                    credentials_path=credentials_path,
                    backlog_configs=active_backlog_configs,
                    backlog_statuses=_load_backlog_status_values(
                        config_spreadsheet_id, str(credentials_path)
                    ),
                )
            message = (
                f"状態同期を完了しました。確認：{sync_result.checked_count}件 / "
                f"更新：{len(sync_result.updated)}件"
            )
            if sync_result.failed_request_ids:
                st.warning(f"{message} / 取得失敗：{len(sync_result.failed_request_ids)}件")
            else:
                st.success(message)
        except Exception:
            st.error("Backlog状態を同期できませんでした。")
