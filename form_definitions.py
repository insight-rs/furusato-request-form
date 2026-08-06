"""各種マスタで管理する商品修正フォーム項目を読み込む。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gspread

from config_master import normalize


FORM_FIELD_SHEET_NAME = "フォーム項目定義"
FORM_FIELD_STATUS_SELECTABLE = "対象項目選択肢"
CHOICE_HEADER_PATH = Path(__file__).with_name("config") / "product_details_header.tsv"

CODED_OPTIONS = {
    "（必須）発送期日種別": "任意入力=0|7日程度で発送=1|2週間程度で発送=2|1か月程度で発送=3|翌営業日までに発送=4",
    "（必須）配送業者": "指定なし=0|ヤマト運輸=1|佐川急便=2|日本郵便=3|西濃運輸=4|福山通運=5|日本通運=6|佐川急便（6時間帯）=7|佐川急便（5時間帯）=8",
    "（必須）配達日種別": "指定不可=0|月単位=1|旬単位=2|日単位=3",
    "規格外になった理由": "災害=1|天候=2|製造・育成過程=3",
}
YES_NO_COLUMNS = {
    "（必須）常温配送", "（必須）冷蔵配送", "（必須）冷凍配送",
    "（必須）定期配送対応", "（必須）別送対応", "（必須）包装対応",
    "（必須）のし対応", "（必須）会員限定", "（必須）チョイス限定",
    "（必須）オンライン決済限定", "（必須）配送状況確認可能",
    "（必須）地域の生産者応援の品（訳ありの品）",
    "（必須）配達日種別必須フラグ", "（必須）配達時間指定必須フラグ",
    "（必須）還元率入力有無",
}
CODED_OPTIONS.update({column: "する=1|しない=0" for column in YES_NO_COLUMNS})
CODED_OPTIONS.update({
    "（必須）ポイント情報表示有無": "表示する=1|表示しない=0",
    "（必須）配達時間指定": "指定できる=1|指定できない=0",
    "（必須）表示有無": "表示=1|非表示=0",
})


def japanese_label(source_column: str) -> str:
    """チョイス列名の必須注記を保ちつつ、画面向けの自然な日本語にする。"""

    return normalize(source_column).removeprefix("（必須）").removeprefix("（条件付き必須）")


def choice_master_form_fields() -> list[RequestFormField]:
    """チョイスの正式ヘッダーから、マスタ欠損時にも使える項目定義を作る。"""

    headers = CHOICE_HEADER_PATH.read_text(encoding="utf-8-sig").strip().split("\t")
    fields = []
    for number, source_column in enumerate(headers, start=1):
        options_text = CODED_OPTIONS.get(source_column, "")
        input_kind = "選択" if options_text else "テキスト"
        if source_column.startswith("アレルギー："):
            options_text = "あり=1|なし=2|未確認=3"
            input_kind = "選択"
        if source_column in {"配達日FROM", "配達日TO", "受付開始日時", "受付終了日時"}:
            input_kind = "日付"
        fields.append(RequestFormField(
            field_id=f"CHOICE-{number:03d}",
            visibility=FORM_FIELD_STATUS_SELECTABLE,
            requirement="必須" if source_column.startswith("（必須）") else "任意",
            label=japanese_label(source_column),
            source_column=source_column,
            input_kind=input_kind,
            options_text=options_text,
            display_order=number,
        ))
    return fields


def merge_choice_master_fields(fields: Iterable[RequestFormField]) -> list[RequestFormField]:
    """共有マスタの設定を尊重しつつ、正式列・日本語表示・コード選択を補完する。"""

    configured = {field.source_column: field for field in fields}
    merged = []
    for fallback in choice_master_form_fields():
        current = configured.get(fallback.source_column)
        if current is None:
            merged.append(fallback)
            continue
        merged.append(RequestFormField(
            field_id=current.field_id,
            visibility=current.visibility or fallback.visibility,
            requirement=current.requirement or fallback.requirement,
            label=japanese_label(current.label or fallback.label),
            source_column=current.source_column,
            input_kind="選択" if fallback.options_text else current.input_kind,
            options_text=fallback.options_text or current.options_text,
            display_condition=current.display_condition,
            transform_rule=current.transform_rule,
            source_instruction=current.source_instruction,
            display_order=current.display_order,
            correction_visibility=current.correction_visibility,
            new_product_visibility=current.new_product_visibility,
            fixed_value=current.fixed_value,
        ))
    return merged


@dataclass(frozen=True)
class RequestFormField:
    field_id: str
    visibility: str
    requirement: str
    label: str
    source_column: str
    input_kind: str
    options_text: str = ""
    display_condition: str = ""
    transform_rule: str = ""
    source_instruction: str = ""
    display_order: int = 9999
    correction_visibility: str = ""
    new_product_visibility: str = ""
    fixed_value: str = ""

    def options(self) -> tuple[tuple[str, str], ...]:
        """`表示名=保存値|...` の設定を画面用に解釈する。"""

        pairs = []
        for option in self.options_text.split("|"):
            text = normalize(option)
            if not text:
                continue
            label, separator, value = text.partition("=")
            pairs.append((normalize(label), normalize(value) if separator else normalize(label)))
        return tuple(pairs)


def build_request_form_fields(rows: Iterable[dict]) -> list[RequestFormField]:
    fields = []
    for row in rows:
        field_id = normalize(row.get("項目ID"))
        source_column = normalize(row.get("商品マスタ列名"))
        if not field_id or not source_column:
            continue
        try:
            display_order = int(normalize(row.get("表示順")) or 9999)
        except ValueError:
            display_order = 9999
        fields.append(RequestFormField(
            field_id=field_id,
            visibility=normalize(row.get("フォーム表示")),
            requirement=normalize(row.get("必須区分")),
            label=normalize(row.get("表示名")) or source_column,
            source_column=source_column,
            input_kind=normalize(row.get("入力形式")) or "テキスト",
            options_text=normalize(row.get("選択肢（|区切り）")),
            display_condition=normalize(row.get("表示条件")),
            transform_rule=normalize(row.get("変換規則")),
            source_instruction=normalize(row.get("元指示")),
            display_order=display_order,
            correction_visibility=normalize(row.get("修正時表示")),
            new_product_visibility=normalize(row.get("新規時表示")),
            fixed_value=normalize(row.get("固定値")),
        ))
    return fields


def selectable_request_form_fields(
    fields: Iterable[RequestFormField],
) -> list[RequestFormField]:
    return [
        field for field in fields
        if field.visibility == FORM_FIELD_STATUS_SELECTABLE
        and field.input_kind != "ファイル"
    ]


def find_request_form_field(
    fields: Iterable[RequestFormField], source_column: str
) -> RequestFormField | None:
    target = normalize(source_column)
    return next((field for field in fields if field.source_column == target), None)


def load_request_form_fields(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[RequestFormField]:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(FORM_FIELD_SHEET_NAME).get_all_records()
    return merge_choice_master_fields(build_request_form_fields(rows))
