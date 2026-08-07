"""商品情報マスタ内の商品修正依頼を読み書きする。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4
from zoneinfo import ZoneInfo

import gspread

from config_master import ConfigError, normalize
from form_definitions import CODED_OPTIONS


ALL_PRODUCTS_SHEET_NAME = "全自治体マスタ"
REQUEST_SHEET_NAME = "商品修正依頼"
REQUEST_DETAIL_SHEET_NAME = "商品修正依頼明細"
IMAGE_REQUEST_SHEET_NAME = "画像修正依頼"
PRODUCT_COLUMN_DEFINITION_SHEET_NAME = "商品マスタ列定義"
JST = ZoneInfo("Asia/Tokyo")


def _coded_labels(options_text: str) -> dict[str, str]:
    labels = {}
    for option in options_text.split("|"):
        label, separator, code = option.partition("=")
        if separator:
            labels[normalize(code)] = normalize(label)
    return labels


def _backlog_display_value(field_name: str, value: object) -> str:
    """Backlog本文では保存コードではなく利用者向けの日本語を表示する。"""

    text = normalize(value)
    if not text:
        return "（未設定）"
    if field_name.startswith("アレルギー："):
        return {"1": "あり", "2": "なし", "3": "未確認"}.get(text, text)
    if field_name in {
        "（必須）常温配送", "（必須）冷蔵配送", "（必須）冷凍配送"
    }:
        return {"1": "対象", "0": "対象外"}.get(text, text)
    labels = _coded_labels(CODED_OPTIONS.get(field_name, ""))
    if "," in text:
        return "、".join(labels.get(part.strip(), part.strip()) for part in text.split(","))
    return labels.get(text, text)


def _backlog_change_section(field_name: str) -> str:
    if field_name.startswith("アレルギー：") or field_name == "アレルギー特記事項":
        return "アレルギー情報"
    if any(word in field_name for word in ("配送", "発送", "配達")):
        return "配送情報"
    if any(word in field_name for word in ("表示", "受付")):
        return "公開・受付設定"
    if field_name.startswith("Backlogのみ："):
        return "商品管理情報"
    if field_name in {"管理コード", "（必須）お礼の品名", "サイト表示事業者名"}:
        return "基本情報"
    return "商品詳細"


@dataclass(frozen=True)
class ProductReference:
    municipality_id: str
    municipality_name: str
    product_id: str
    original_product_id: str
    product_name: str
    business_id: str
    business_name: str
    source_row: tuple[tuple[str, str], ...] = ()

    def source_values(self) -> dict[str, str]:
        return dict(self.source_row)

    def source_column_number(self, column_name: str) -> int:
        target = normalize(column_name)
        for number, (name, _) in enumerate(self.source_row, start=1):
            if name == target:
                return number
        return 0


@dataclass(frozen=True)
class ProductCorrectionField:
    column_number: int
    column_name: str


@dataclass(frozen=True)
class ProductCorrectionLine:
    product: ProductReference
    field_name: str
    before_value: str
    after_value: str
    instruction: str = ""
    image_instruction: str = ""
    column_number: int = 0
    display_name: str = ""


@dataclass(frozen=True)
class ProductCorrectionRequest:
    request_id: str
    requested_at: datetime
    requester: str
    municipality_id: str
    municipality_name: str
    note: str = ""
    backlog_assignee_name: str = ""
    backlog_assignee_id: str = ""
    request_unit: str = "商品単位"
    work_category: str = "一般業務"
    policy_id: str = ""
    policy_type: str = ""
    policy_content: str = ""
    policy_detail: str = ""
    backlog_issue_type: str = ""


@dataclass(frozen=True)
class ProductRequestSaveResult:
    request_id: str
    detail_ids: tuple[str, ...]
    image_request_ids: tuple[str, ...]


@dataclass(frozen=True)
class SavedProductCorrectionDetail:
    product_id: str
    original_product_id: str
    field_name: str
    before_value: str
    after_value: str
    instruction: str = ""
    image_instruction: str = ""


@dataclass(frozen=True)
class SavedProductCorrectionRequest:
    request_id: str
    backlog_issue_key: str
    municipality_id: str
    municipality_name: str
    requester: str
    request_unit: str
    work_category: str
    note: str
    backlog_issue_type: str
    details: tuple[SavedProductCorrectionDetail, ...]


def _required(value: object, label: str) -> str:
    normalized = normalize(value)
    if not normalized:
        raise ConfigError(f"{label} を入力してください。")
    return normalized


def create_product_correction_request(
    requester: str,
    municipality_id: str,
    municipality_name: str,
    note: str = "",
    backlog_assignee_name: str = "",
    backlog_assignee_id: str = "",
    request_unit: str = "商品単位",
    work_category: str = "一般業務",
    policy_id: str = "",
    policy_type: str = "",
    policy_content: str = "",
    policy_detail: str = "",
    backlog_issue_type: str = "",
    requested_at: datetime | None = None,
    request_id_factory: Callable[[], str] | None = None,
) -> ProductCorrectionRequest:
    """保存前の依頼ヘッダーを生成する。"""

    timestamp = requested_at or datetime.now(JST)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=JST)
    factory = request_id_factory or (lambda: uuid4().hex[:12])
    return ProductCorrectionRequest(
        request_id=f"PR-{timestamp.strftime('%Y%m%d')}-{factory()}",
        requested_at=timestamp.astimezone(JST),
        requester=_required(requester, "依頼者"),
        municipality_id=_required(municipality_id, "自治体ID"),
        municipality_name=_required(municipality_name, "自治体名"),
        note=normalize(note),
        backlog_assignee_name=normalize(backlog_assignee_name),
        backlog_assignee_id=normalize(backlog_assignee_id),
        request_unit=_required(request_unit, "対応単位"),
        work_category=_required(work_category, "業務種別"),
        policy_id=normalize(policy_id),
        policy_type=normalize(policy_type),
        policy_content=normalize(policy_content),
        policy_detail=normalize(policy_detail),
        backlog_issue_type=normalize(backlog_issue_type),
    )


def build_product_references(rows: Iterable[dict]) -> list[ProductReference]:
    """全自治体マスタの必要列だけを商品選択用に整形する。"""

    products = []
    for row in rows:
        municipality_id = normalize(row.get("自治体ID"))
        product_id = normalize(row.get("お礼の品ID"))
        if not municipality_id or not product_id:
            continue
        products.append(ProductReference(
            municipality_id=municipality_id,
            municipality_name=normalize(row.get("自治体名")),
            product_id=product_id,
            original_product_id=normalize(row.get("オリジナルお礼の品ID")),
            product_name=normalize(row.get("（必須）お礼の品名")),
            business_id=normalize(row.get("事業者ID")),
            business_name=normalize(row.get("サイト表示事業者名")),
            source_row=tuple((str(name), normalize(value)) for name, value in row.items()),
        ))
    return products


def search_products(
    products: Iterable[ProductReference],
    municipality_id: str,
    keyword: str = "",
    limit: int = 100,
) -> list[ProductReference]:
    """自治体内で商品ID・商品名・事業者情報を検索する。"""

    target_municipality_id = _required(municipality_id, "自治体ID")
    query = normalize(keyword).casefold()
    matches = []
    for product in products:
        if product.municipality_id != target_municipality_id:
            continue
        search_text = " ".join((
            product.product_id,
            product.original_product_id,
            product.product_name,
            product.business_id,
            product.business_name,
        )).casefold()
        if query and query not in search_text:
            continue
        matches.append(product)
        if len(matches) >= limit:
            break
    return matches


def build_product_correction_fields(rows: Iterable[dict]) -> list[ProductCorrectionField]:
    """商品マスタ列定義で「対象」に指定された列だけを修正依頼候補にする。"""

    fields = []
    for row in rows:
        if normalize(row.get("修正依頼対象")) != "対象":
            continue
        name = normalize(row.get("列名"))
        try:
            column_number = int(normalize(row.get("列番号")))
        except ValueError:
            continue
        if name and column_number > 0:
            fields.append(ProductCorrectionField(
                column_number=column_number,
                column_name=name,
            ))
    return fields


def load_product_correction_fields(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[ProductCorrectionField]:
    """商品情報マスタの列定義から、依頼画面に表示する固定項目を読む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(PRODUCT_COLUMN_DEFINITION_SHEET_NAME).get_all_records()
    return build_product_correction_fields(rows)


def validate_correction_lines(
    request: ProductCorrectionRequest,
    lines: Iterable[ProductCorrectionLine],
) -> list[ProductCorrectionLine]:
    """依頼ヘッダーと明細の整合性を検証する。"""

    validated = list(lines)
    if not validated:
        if request.request_unit == "商品単位":
            raise ConfigError("少なくとも1件の商品修正明細を追加してください。")
        return []

    for line_number, line in enumerate(validated, start=1):
        label = f"明細{line_number}"
        if line.product.municipality_id != request.municipality_id:
            raise ConfigError(f"{label}: 選択商品の自治体が依頼と一致しません。")
        if request.request_unit != "新規商品登録":
            _required(line.product.product_id, f"{label}のお礼の品ID")
        _required(line.field_name, f"{label}の修正項目")
        source_column_number = line.product.source_column_number(line.field_name)
        if line.column_number and source_column_number and line.column_number != source_column_number:
            raise ConfigError(f"{label}: 対象列番号が商品マスタと一致しません。")
        if not normalize(line.before_value) and not normalize(line.after_value):
            raise ConfigError(f"{label}: 修正前値または修正後値を入力してください。")
    return validated


def build_backlog_issue_content(
    request: ProductCorrectionRequest,
    lines: Iterable[ProductCorrectionLine],
) -> tuple[str, str]:
    """商品修正依頼からBacklog親課題の件名・本文を組み立てる。"""

    validated_lines = validate_correction_lines(request, lines)
    if request.work_category == "施策":
        summary_label = "施策"
    elif request.request_unit == "新規商品登録":
        summary_label = "新規商品登録"
    elif request.request_unit == "商品単位":
        summary_label = "商品修正"
    else:
        summary_label = request.request_unit
    summary = f"【{summary_label}】{request.municipality_name}"
    if validated_lines:
        product_count = len({
            (line.product.municipality_id, line.product.product_id)
            for line in validated_lines
        })
        summary += f" {product_count}商品"
    # 商品修正の親課題は、担当者などの運用情報を混ぜず、商品ごとの
    # 変更点だけを確認できる本文にする。
    description_lines: list[str] = []
    if request.request_unit != "商品単位":
        description_lines.extend([
            f"依頼ID: {request.request_id}",
            f"依頼者: {request.requester}",
            f"対応単位: {request.request_unit}",
            f"業務種別: {request.work_category}",
        ])
    if request.policy_id:
        description_lines.extend([
            f"施策ID: {request.policy_id}",
            f"施策種別: {request.policy_type}",
            f"施策具体内容: {request.policy_content}",
            f"施策詳細: {request.policy_detail}",
        ])
    if request.note and request.request_unit != "商品単位":
        description_lines.extend(["", "【対応内容・備考】", request.note])
    if request.request_unit in {"商品単位", "新規商品登録"}:
        description_lines.append("【商品の変更点】")
    if not validated_lines:
        description_lines.append("商品単位の変更はありません。")
    else:
        lines_by_product: dict[tuple[str, str], list[ProductCorrectionLine]] = {}
        for line in validated_lines:
            key = (line.product.municipality_id, line.product.product_id)
            lines_by_product.setdefault(key, []).append(line)
        for product_number, product_lines in enumerate(lines_by_product.values(), start=1):
            product = product_lines[0].product
            management_code = normalize(product.source_values().get("管理コード"))
            description_lines.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                f"■ 商品{product_number}｜品番：{management_code or product.product_id or '未設定'}",
                f"商品名：{product.product_name or '未設定'}",
            ])
            if product.business_name:
                description_lines.append(f"事業者：{product.business_name}")
            image_instructions = []
            previous_section = ""
            for line in product_lines:
                field_label = normalize(line.display_name) or normalize(line.field_name)
                section = _backlog_change_section(line.field_name)
                if section != previous_section:
                    description_lines.extend(["", f"【{section}】"])
                    previous_section = section
                description_lines.extend([
                    f"・{field_label}",
                    f"  現状：{_backlog_display_value(line.field_name, line.before_value)}",
                    f"  更新後：{_backlog_display_value(line.field_name, line.after_value)}",
                ])
                if normalize(line.instruction):
                    description_lines.append(f"補足：{normalize(line.instruction)}")
                if normalize(line.image_instruction):
                    image_instructions.append(normalize(line.image_instruction))
            # 画像の指示は、商品情報の変更点の最後にまとめる。
            if image_instructions:
                description_lines.extend([
                    "",
                    "画像修正指示：",
                    *dict.fromkeys(image_instructions),
                ])
    return summary, "\n".join(description_lines)


def build_image_backlog_issue_content(
    request: ProductCorrectionRequest,
    lines: ProductCorrectionLine | Iterable[ProductCorrectionLine],
) -> tuple[str, str]:
    """画像指示を一件のBacklog子課題に集約する。"""

    candidate_lines = [lines] if isinstance(lines, ProductCorrectionLine) else list(lines)
    image_lines = [line for line in candidate_lines if normalize(line.image_instruction)]
    if not image_lines:
        raise ConfigError("画像修正指示を入力してください。")

    products: dict[tuple[str, str], list[ProductCorrectionLine]] = {}
    for line in image_lines:
        products.setdefault(
            (line.product.municipality_id, line.product.product_id), []
        ).append(line)

    unique_businesses = list(dict.fromkeys(
        normalize(lines[0].product.business_name) or "事業者未設定"
        for lines in products.values()
    ))
    product_codes = []
    for product_lines in products.values():
        product = product_lines[0].product
        product_codes.append(
            normalize(product.source_values().get("管理コード"))
            or normalize(product.product_id)
            or "品番未設定"
        )
    business_label = "・".join(unique_businesses[:2])
    if len(unique_businesses) > 2:
        business_label += f"ほか{len(unique_businesses) - 2}事業者"
    code_label = "・".join(product_codes[:3])
    if len(product_codes) > 3:
        code_label += f"ほか{len(product_codes) - 3}品番"
    summary = f"【画像修正】{business_label}｜{code_label}｜{len(products)}商品"
    description_lines = [f"親依頼ID: {request.request_id}"]
    for product_lines in products.values():
        product = product_lines[0].product
        management_code = normalize(product.source_values().get("管理コード"))
        instructions = list(dict.fromkeys(
            normalize(line.image_instruction) for line in product_lines
            if normalize(line.image_instruction)
        ))
        description_lines.extend([
            "",
            f"■ 品番：{management_code or product.product_id or '未設定'}",
            f"商品名：{product.product_name or '未設定'}",
        ])
        if product.business_name:
            description_lines.append(f"事業者：{product.business_name}")
        description_lines.extend(["画像修正指示：", *instructions])
    return summary, "\n".join(description_lines)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")


def save_product_correction_request(
    spreadsheet_id: str,
    credentials_path: Path,
    request: ProductCorrectionRequest,
    lines: Iterable[ProductCorrectionLine],
    client_factory: Callable | None = None,
) -> ProductRequestSaveResult:
    """依頼ヘッダー・明細・画像指示を商品情報マスタへ追記する。

    Backlog起票はこの段階では行わない。まず依頼を一意なIDで保存することで、
    連携失敗時にも作業内容を失わないようにする。
    """

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    validated_lines = validate_correction_lines(request, lines)
    now_text = _format_datetime(datetime.now(JST))
    requested_at_text = _format_datetime(request.requested_at)
    detail_ids = tuple(
        f"{request.request_id}-D{index:03d}"
        for index, _ in enumerate(validated_lines, start=1)
    )
    image_entries = [
        (f"{request.request_id}-I{index:03d}", detail_id, line)
        for index, (detail_id, line) in enumerate(zip(detail_ids, validated_lines), start=1)
        if normalize(line.image_instruction)
    ]

    request_kind = (
        "施策" if request.work_category == "施策"
        else "新規商品登録" if request.request_unit == "新規商品登録"
        else "商品修正" if request.request_unit == "商品単位"
        else request.request_unit
    )
    request_row = [[
        request.request_id,
        requested_at_text,
        request.requester,
        request.municipality_id,
        request.municipality_name,
        request_kind,
        "",
        "",
        "受付",
        "あり" if image_entries else "なし",
        request.note,
        now_text,
        request.backlog_assignee_name,
        request.backlog_assignee_id,
        request.request_unit,
        request.work_category,
        request.policy_id,
        request.policy_type,
        request.policy_content,
        request.policy_detail,
        request.backlog_issue_type,
    ]]
    detail_rows = [[
        detail_id,
        request.request_id,
        line.product.municipality_id,
        line.product.product_id,
        line.product.original_product_id,
        line.product.product_name,
        line.product.business_id,
        line.product.business_name,
        normalize(line.field_name),
        normalize(line.before_value),
        normalize(line.after_value),
        normalize(line.instruction),
        normalize(line.image_instruction),
        "受付",
        now_text,
        line.column_number or line.product.source_column_number(line.field_name),
    ] for detail_id, line in zip(detail_ids, validated_lines)]
    image_rows = [[
        image_request_id,
        request.request_id,
        detail_id,
        "画像修正",
        normalize(line.image_instruction),
        "",
        "",
        "",
        "",
        "受付",
        now_text,
    ] for image_request_id, detail_id, line in image_entries]

    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    spreadsheet.worksheet(REQUEST_SHEET_NAME).append_rows(
        request_row, value_input_option="USER_ENTERED"
    )
    if detail_rows:
        spreadsheet.worksheet(REQUEST_DETAIL_SHEET_NAME).append_rows(
            detail_rows, value_input_option="USER_ENTERED"
        )
    if image_rows:
        spreadsheet.worksheet(IMAGE_REQUEST_SHEET_NAME).append_rows(
            image_rows, value_input_option="USER_ENTERED"
        )

    return ProductRequestSaveResult(
        request_id=request.request_id,
        detail_ids=detail_ids,
        image_request_ids=tuple(entry[0] for entry in image_entries),
    )


def update_product_request_backlog_parent(
    spreadsheet_id: str,
    credentials_path: Path,
    request_id: str,
    issue_key: str,
    issue_url: str,
    client_factory: Callable | None = None,
) -> None:
    """保存済み依頼にBacklog親課題キー・URL・状態を記録する。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    target_request_id = _required(request_id, "依頼ID")
    target_issue_key = _required(issue_key, "Backlog親課題キー")
    target_issue_url = _required(issue_url, "Backlog親課題URL")

    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(REQUEST_SHEET_NAME)
    request_ids = worksheet.col_values(1)
    try:
        row_number = request_ids.index(target_request_id) + 1
    except ValueError as error:
        raise ConfigError(f"依頼ID {target_request_id} が商品修正依頼にありません。") from error

    worksheet.batch_update([
        {
            "range": f"G{row_number}:I{row_number}",
            "values": [[target_issue_key, target_issue_url, "Backlog起票済"]],
        },
        {
            "range": f"L{row_number}",
            "values": [[_format_datetime(datetime.now(JST))]],
        },
    ], value_input_option="USER_ENTERED")


def update_image_request_backlog_child(
    spreadsheet_id: str,
    credentials_path: Path,
    image_request_id: str,
    issue_key: str,
    issue_url: str,
    client_factory: Callable | None = None,
) -> None:
    """保存済み画像依頼にBacklog子課題キー・URL・状態を記録する。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    target_image_request_id = _required(image_request_id, "画像依頼ID")
    target_issue_key = _required(issue_key, "Backlog子課題キー")
    target_issue_url = _required(issue_url, "Backlog子課題URL")

    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(IMAGE_REQUEST_SHEET_NAME)
    image_request_ids = worksheet.col_values(1)
    try:
        row_number = image_request_ids.index(target_image_request_id) + 1
    except ValueError as error:
        raise ConfigError(
            f"画像依頼ID {target_image_request_id} が画像修正依頼にありません。"
        ) from error

    worksheet.batch_update([
        {
            "range": f"G{row_number}:H{row_number}",
            "values": [[target_issue_key, target_issue_url]],
        },
        {"range": f"J{row_number}", "values": [["Backlog起票済"]]},
        {
            "range": f"K{row_number}",
            "values": [[_format_datetime(datetime.now(JST))]],
        },
    ], value_input_option="USER_ENTERED")


def load_product_references(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[ProductReference]:
    """商品情報マスタの全自治体マスタを商品検索用に読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(ALL_PRODUCTS_SHEET_NAME).get_all_records()
    return build_product_references(rows)


def load_saved_product_correction_request(
    spreadsheet_id: str,
    credentials_path: Path,
    lookup_value: str,
    client_factory: Callable | None = None,
) -> SavedProductCorrectionRequest | None:
    """依頼IDまたはBacklog親課題キーから、再編集用の履歴を取得する。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    target = _required(lookup_value, "依頼IDまたはBacklog課題キー")
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    request_rows = spreadsheet.worksheet(REQUEST_SHEET_NAME).get_all_records()
    request_row = next(
        (
            row for row in request_rows
            if normalize(row.get("依頼ID")) == target
            or normalize(row.get("Backlog親課題キー")) == target
        ),
        None,
    )
    if request_row is None:
        return None

    request_id = normalize(request_row.get("依頼ID"))
    detail_rows = spreadsheet.worksheet(REQUEST_DETAIL_SHEET_NAME).get_all_records()
    details = []
    for row in detail_rows:
        if normalize(row.get("依頼ID")) != request_id:
            continue
        field_name = normalize(row.get("修正項目")) or normalize(row.get("変更項目"))
        if not field_name:
            continue
        details.append(SavedProductCorrectionDetail(
            product_id=normalize(row.get("お礼の品ID")),
            original_product_id=normalize(row.get("オリジナルお礼の品ID")),
            field_name=field_name,
            before_value=(
                normalize(row.get("修正前値")) or normalize(row.get("変更前値"))
            ),
            after_value=(
                normalize(row.get("修正後値")) or normalize(row.get("変更後値"))
            ),
            instruction=normalize(row.get("補足・根拠")) or normalize(row.get("備考・根拠")),
            image_instruction=normalize(row.get("画像修正指示")) or normalize(row.get("画像指示")),
        ))

    return SavedProductCorrectionRequest(
        request_id=request_id,
        backlog_issue_key=normalize(request_row.get("Backlog親課題キー")),
        municipality_id=normalize(request_row.get("自治体ID")),
        municipality_name=normalize(request_row.get("自治体名")),
        requester=normalize(request_row.get("依頼者")),
        request_unit=normalize(request_row.get("対応単位")) or "商品単位",
        work_category=normalize(request_row.get("業務種別")) or "一般業務",
        note=normalize(request_row.get("依頼内容・備考")),
        backlog_issue_type=normalize(request_row.get("Backlog課題種別")),
        details=tuple(details),
    )
