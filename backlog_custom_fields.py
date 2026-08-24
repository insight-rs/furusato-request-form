"""Backlogのカスタム属性マスタを読み込み、起票用パラメータを組み立てる。"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

import gspread

from backlog_client import BacklogApiError, backlog_base_url, resolve_project_id
from backlog_config import BacklogConfig
from config_master import ConfigError, normalize


CUSTOM_FIELD_SHEET_NAME = "カスタム属性マスタ"
LEGACY_CUSTOM_FIELD_SHEET_NAME = "09_カスタム属性マスタ"
LIST_TYPE_IDS = {"5", "6", "7", "8"}
MULTI_VALUE_TYPE_IDS = {"6", "7"}


@dataclass(frozen=True)
class BacklogCustomFieldOption:
    name: str
    option_id: str


@dataclass(frozen=True)
class BacklogCustomField:
    municipality_id: str
    municipality_name: str
    project_id: str
    issue_type_name: str
    issue_type_id: str
    name: str
    field_id: str
    type_id: str
    required: bool
    options: tuple[BacklogCustomFieldOption, ...]

    def applies_to(self, issue_type_name: str) -> bool:
        configured = normalize(self.issue_type_name)
        return not configured or configured == "すべての種別" or configured == normalize(issue_type_name)


def _is_required(value: object) -> bool:
    return normalize(value).casefold() in {"必須", "true", "yes", "1"}


def _split_options(names: object, option_ids: object) -> tuple[BacklogCustomFieldOption, ...]:
    option_names = [item.strip() for item in normalize(names).split(",") if item.strip()]
    ids = [item.strip() for item in normalize(option_ids).split(",") if item.strip()]
    return tuple(
        BacklogCustomFieldOption(name=name, option_id=ids[index])
        for index, name in enumerate(option_names)
        if index < len(ids)
    )


def build_backlog_custom_fields(rows: Iterable[dict]) -> list[BacklogCustomField]:
    """マスタの完全な行をアプリで利用可能なカスタム属性に整形する。"""

    fields = []
    for row in rows:
        municipality_id = normalize(row.get("自治体ID"))
        name = normalize(row.get("属性名(項目名)"))
        field_id = normalize(row.get("属性ID"))
        type_id = normalize(row.get("列 1"))
        if not municipality_id or not name or not field_id or not type_id:
            continue
        fields.append(BacklogCustomField(
            municipality_id=municipality_id,
            municipality_name=normalize(row.get("自治体名")),
            project_id=normalize(row.get("プロジェクトID")),
            issue_type_name=normalize(row.get("課題種別名")),
            issue_type_id=normalize(row.get("課題種別ID")),
            name=name,
            field_id=field_id,
            type_id=type_id,
            required=_is_required(row.get("必須設定")),
            options=_split_options(
                row.get("選択肢リスト(カンマ区切り)"), row.get("選択肢IDリスト")
            ),
        ))
    return fields


def get_applicable_custom_fields(
    fields: Iterable[BacklogCustomField],
    municipality_id: str,
    issue_type_name: str,
    required_only: bool = False,
) -> list[BacklogCustomField]:
    """自治体・課題種別に適用される属性を、同じ属性IDで重複させず返す。"""

    selected = {}
    for field in fields:
        if field.municipality_id != normalize(municipality_id):
            continue
        if required_only and not field.required:
            continue
        if not field.applies_to(issue_type_name):
            continue
        existing = selected.get(field.field_id)
        if existing is None or field.issue_type_name == normalize(issue_type_name):
            selected[field.field_id] = field
    return list(selected.values())


def build_custom_field_parameters(
    fields: Iterable[BacklogCustomField],
    values_by_name: Mapping[str, object],
) -> dict[str, str | list[str]]:
    """画面の属性名・選択肢名からBacklog APIの ``customField_*`` を生成する。"""

    parameters: dict[str, str | list[str]] = {}
    for field in fields:
        raw_value = values_by_name.get(field.name, "")
        if isinstance(raw_value, (list, tuple, set)):
            normalized_values = [normalize(value) for value in raw_value if normalize(value)]
        else:
            normalized_values = [normalize(raw_value)] if normalize(raw_value) else []
        if field.required and not normalized_values:
            raise ConfigError(f"Backlog必須属性「{field.name}」を入力してください。")
        if not normalized_values:
            continue

        if field.type_id in LIST_TYPE_IDS:
            option_ids = {option.name: option.option_id for option in field.options}
            resolved_values = []
            for value in normalized_values:
                option_id = option_ids.get(value, value if value in option_ids.values() else "")
                if not option_id:
                    raise ConfigError(
                        f"Backlog属性「{field.name}」の選択肢「{value}」がありません。"
                    )
                resolved_values.append(option_id)
            # Backlogの課題追加・更新APIでは、複数選択のカスタム属性も
            # パラメータ名は ``customField_{id}``（[]なし）で送る。
            # 複数値は urlencode(..., doseq=True) が同じキーを繰り返して展開する。
            key = f"customField_{field.field_id}"
            parameters[key] = (
                resolved_values
                if field.type_id in MULTI_VALUE_TYPE_IDS
                else resolved_values[0]
            )
        elif field.type_id == "3":
            try:
                float(normalized_values[0])
            except ValueError as error:
                raise ConfigError(f"Backlog属性「{field.name}」は数値で入力してください。") from error
            parameters[f"customField_{field.field_id}"] = normalized_values[0]
        else:
            parameters[f"customField_{field.field_id}"] = normalized_values[0]
    return parameters


def load_backlog_custom_fields(
    spreadsheet_id: str,
    credentials_path: Path | str,
    client_factory: Callable | None = None,
) -> list[BacklogCustomField]:
    """各種マスタのカスタム属性マスタを読み込む。"""

    credentials_path = Path(credentials_path)
    if not credentials_path.exists():
        raise FileNotFoundError(f"サービスアカウントJSONがありません: {credentials_path}")
    factory = client_factory or gspread.service_account
    spreadsheet = factory(filename=str(credentials_path)).open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(CUSTOM_FIELD_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.worksheet(LEGACY_CUSTOM_FIELD_SHEET_NAME)
    values = worksheet.get_all_values()
    if not values:
        return []
    return build_backlog_custom_fields([
        dict(zip(values[0], row)) for row in values[1:]
    ])


def fetch_backlog_custom_fields(config: BacklogConfig) -> list[dict]:
    """Backlogから対象プロジェクトの最新カスタム属性を取得する。"""

    project_id = resolve_project_id(config)
    url = (
        f"{backlog_base_url(config.space_id)}/api/v2/projects/{project_id}/customFields?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    try:
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise BacklogApiError("Backlogカスタム属性を取得できませんでした。") from error
    if not isinstance(payload, list):
        raise BacklogApiError("Backlogカスタム属性の応答形式が不正です。")
    return [field for field in payload if isinstance(field, dict)]


def sync_backlog_custom_fields(
    spreadsheet_id: str,
    credentials_path: Path,
    configs: Iterable[BacklogConfig],
    client_factory: Callable | None = None,
) -> int:
    """有効な自治体の最新属性をマスタへ反映し、登録した行数を返す。"""

    config_list = list(configs)
    if not config_list:
        return 0
    factory = client_factory or gspread.service_account
    spreadsheet = factory(filename=str(credentials_path)).open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(CUSTOM_FIELD_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.worksheet(LEGACY_CUSTOM_FIELD_SHEET_NAME)
    values = worksheet.get_all_values()
    if not values:
        raise ConfigError("カスタム属性マスタのヘッダーがありません。")
    headers = values[0]
    required_headers = {
        "自治体名", "プロジェクトID", "課題種別名", "課題種別ID", "属性名(項目名)",
        "属性ID", "必須設定", "選択肢リスト(カンマ区切り)", "選択肢IDリスト", "列 1", "自治体ID",
    }
    if not required_headers.issubset(headers):
        raise ConfigError("カスタム属性マスタの列が不足しています。")
    indexes = {header: index for index, header in enumerate(headers)}
    issue_type_rows = spreadsheet.worksheet("07_種別マスタ").get_all_values()
    issue_type_names = {
        (row[4].strip(), row[3].strip()): row[2].strip()
        for row in issue_type_rows[1:]
        if len(row) >= 5 and row[4].strip() and row[3].strip() and row[2].strip()
    }
    target_ids = {config.municipality_id for config in config_list}
    retained_rows = [
        row for row in values[1:]
        if len(row) <= indexes["自治体ID"] or row[indexes["自治体ID"]].strip() not in target_ids
    ]
    synced_rows = []
    for config in config_list:
        for field in fetch_backlog_custom_fields(config):
            applicable_types = field.get("applicableIssueTypes")
            applicable_types = applicable_types if isinstance(applicable_types, list) and applicable_types else [""]
            items = field.get("items") if isinstance(field.get("items"), list) else []
            option_names = ",".join(normalize(item.get("name")) for item in items if isinstance(item, dict))
            option_ids = ",".join(normalize(item.get("id")) for item in items if isinstance(item, dict))
            for issue_type in applicable_types:
                if isinstance(issue_type, dict):
                    issue_type_id = normalize(issue_type.get("id"))
                    issue_type_name = normalize(issue_type.get("name"))
                else:
                    issue_type_id = normalize(issue_type)
                    issue_type_name = issue_type_names.get(
                        (config.municipality_id, issue_type_id), ""
                    )
                row = {
                    "自治体名": config.municipality_name,
                    "プロジェクトID": config.project_id,
                    "課題種別名": issue_type_name or "すべての種別",
                    "課題種別ID": issue_type_id,
                    "属性名(項目名)": normalize(field.get("name")),
                    "属性ID": normalize(field.get("id")),
                    "必須設定": "必須" if field.get("required") else "任意",
                    "選択肢リスト(カンマ区切り)": option_names,
                    "選択肢IDリスト": option_ids,
                    "列 1": normalize(field.get("typeId")),
                    "自治体ID": config.municipality_id,
                }
                synced_rows.append([row.get(header, "") for header in headers])
    end_row = max(len(values), len(retained_rows) + len(synced_rows) + 1)
    worksheet.batch_clear([f"A2:{_column_name(len(headers))}{end_row}"])
    if retained_rows or synced_rows:
        worksheet.update(
            f"A2:{_column_name(len(headers))}{len(retained_rows) + len(synced_rows) + 1}",
            retained_rows + synced_rows,
            value_input_option="RAW",
        )
    return len(synced_rows)


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result
