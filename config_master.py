from dataclasses import dataclass
from datetime import time
import os
from pathlib import Path
from time import sleep
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gspread
from gspread.exceptions import APIError


MUNICIPALITY_SHEET_NAME = "自治体設定"
CREDENTIAL_SHEET_NAME = "認証情報"
COMMON_SHEET_NAME = "共通設定"
CREDENTIAL_SOURCE_FILE_NAME = "credential-spreadsheet-id.txt"
SUPPORTED_PORTALS = {"furusato_choice"}
SUPPORTED_OUTPUT_METHODS = {"spreadsheet", "excel", "both"}
OUTPUT_METHOD_ALIASES = {
    "spreadsheet": "spreadsheet",
    "スプレッドシート": "spreadsheet",
    "excel": "excel",
    "エクセル": "excel",
    "both": "both",
    "両方": "both",
}


class ConfigError(ValueError):
    """設定マスタの値が処理に利用できない場合のエラー。"""


class SheetsReadQuotaError(RuntimeError):
    """Google Sheets API の一時的な読み取り上限に到達した場合のエラー。"""


def _read_with_retry(operation: Callable[[], object], attempts: int = 5):
    """429/一時的なサーバーエラーだけを短時間の指数バックオフで再試行する。"""

    last_error = None
    for attempt in range(attempts):
        try:
            return operation()
        except APIError as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code not in {429, 500, 502, 503, 504}:
                raise
            last_error = error
            if attempt == attempts - 1:
                break
            sleep(min(2 ** (attempt + 1), 12))
    raise SheetsReadQuotaError(
        "Googleスプレッドシートの読み取り上限に一時的に達しました。"
        "約1分待ってから、画面を再読み込みしてください。"
    ) from last_error


@dataclass(frozen=True)
class MunicipalityConfig:
    municipality_id: str
    municipality_name: str
    portal_id: str
    portal_name: str
    login_url: str
    otp_recipient: str
    output_method: str
    spreadsheet_id: str
    worksheet_name: str
    credential_key: str
    first_auth_id: str
    first_auth_password: str
    second_auth_id: str
    second_auth_password: str
    automatic_update: bool = False
    automatic_update_verified: bool = False
    run_times: tuple[time, ...] = ()

    @property
    def automatic_update_enabled(self) -> bool:
        return self.automatic_update and self.automatic_update_verified


@dataclass(frozen=True)
class CommonSettings:
    default_run_times: tuple[time, ...]
    check_interval_minutes: int
    timezone_name: str


DEFAULT_COMMON_SETTINGS = CommonSettings(
    default_run_times=(time(6, 0), time(18, 0)),
    check_interval_minutes=15,
    timezone_name="Asia/Tokyo",
)


def normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_credential_spreadsheet_id(base_folder: Path) -> str:
    """認証情報の参照先を、環境変数またはローカル設定から取得する。"""
    environment_value = normalize(
        os.environ.get("FURUSATO_CREDENTIAL_SPREADSHEET_ID")
    )
    if environment_value:
        return environment_value

    source_file = base_folder / "config" / CREDENTIAL_SOURCE_FILE_NAME
    if not source_file.exists():
        return ""
    return normalize(source_file.read_text(encoding="utf-8"))


def is_true(value: object) -> bool:
    return normalize(value).lower() in {"true", "1", "yes", "はい", "有効"}


def parse_run_times(value: object) -> tuple[time, ...]:
    source = normalize(value)
    if not source:
        raise ConfigError("実行時刻が空です。")
    parsed = set()
    for part in source.replace("、", ",").split(","):
        text = part.strip()
        try:
            parsed.add(time.fromisoformat(text))
        except ValueError as error:
            raise ConfigError(f"実行時刻 {text} は HH:MM 形式ではありません。") from error
    return tuple(sorted(parsed))


def format_run_times(run_times: tuple[time, ...]) -> str:
    return "、".join(value.strftime("%H:%M") for value in run_times)


def build_common_settings(rows: list[dict]) -> CommonSettings:
    values = {}
    for row in rows:
        key = normalize(row.get("設定キー"))
        if not key:
            continue
        if key in values:
            raise ConfigError(f"共通設定の {key} が重複しています。")
        values[key] = normalize(row.get("設定値"))

    required = {"基本実行時刻", "確認間隔（分）", "タイムゾーン"}
    missing = sorted(required - values.keys())
    if missing:
        raise ConfigError(f"共通設定に不足があります: {', '.join(missing)}")

    try:
        interval = int(values["確認間隔（分）"])
    except ValueError as error:
        raise ConfigError("確認間隔（分）は整数で指定してください。") from error
    if interval <= 0:
        raise ConfigError("確認間隔（分）は1以上で指定してください。")

    timezone_name = values["タイムゾーン"]
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ConfigError(f"タイムゾーン {timezone_name} は利用できません。") from error

    return CommonSettings(
        default_run_times=parse_run_times(values["基本実行時刻"]),
        check_interval_minutes=interval,
        timezone_name=timezone_name,
    )


def _required(row: dict, field: str, label: str) -> str:
    value = normalize(row.get(field))
    if not value:
        raise ConfigError(f"{label}: {field} が空です。")
    return value


def build_municipality_configs(
    municipality_rows: list[dict],
    credential_rows: list[dict],
    common_settings: CommonSettings = DEFAULT_COMMON_SETTINGS,
) -> list[MunicipalityConfig]:
    credentials_by_key = {
        normalize(row.get("認証情報キー")): row
        for row in credential_rows
        if normalize(row.get("認証情報キー"))
    }
    configs = []
    seen_ids = set()

    for row_number, row in enumerate(municipality_rows, start=2):
        if not is_true(row.get("有効")):
            continue

        label = normalize(row.get("自治体名")) or f"自治体設定 {row_number}行目"
        municipality_id = _required(row, "自治体ID", label)
        if municipality_id in seen_ids:
            raise ConfigError(f"自治体ID {municipality_id} が重複しています。")
        seen_ids.add(municipality_id)

        municipality_name = _required(row, "自治体名", municipality_id)
        credential_key = _required(row, "認証情報キー", municipality_name)
        portal_id = _required(row, "ポータルID", municipality_name)
        login_url = _required(row, "ログインURL", municipality_name)
        output_source = _required(row, "出力方法", municipality_name).lower()
        output_method = OUTPUT_METHOD_ALIASES.get(output_source, output_source)

        if portal_id not in SUPPORTED_PORTALS:
            raise ConfigError(f"{municipality_name}: ポータルID {portal_id} は未対応です。")
        if output_method not in SUPPORTED_OUTPUT_METHODS:
            raise ConfigError(f"{municipality_name}: 出力方法 {output_method} は未対応です。")

        credential = credentials_by_key.get(credential_key)
        if credential is None:
            raise ConfigError(
                f"{municipality_name}: 認証情報キー {credential_key} に対応する認証情報がありません。"
            )

        spreadsheet_id = normalize(row.get("出力先スプレッドシートID"))
        worksheet_name = normalize(row.get("出力先シート名")) or municipality_name
        if output_method in {"spreadsheet", "both"}:
            if not spreadsheet_id:
                raise ConfigError(f"{municipality_name}: 出力先スプレッドシートID が空です。")
            if not worksheet_name:
                raise ConfigError(f"{municipality_name}: 出力先シート名 が空です。")

        configs.append(MunicipalityConfig(
            municipality_id=municipality_id,
            municipality_name=municipality_name,
            portal_id=portal_id,
            portal_name=normalize(row.get("ポータル名")),
            login_url=login_url,
            otp_recipient=normalize(row.get("OTP受信先")),
            output_method=output_method,
            spreadsheet_id=spreadsheet_id,
            worksheet_name=worksheet_name,
            credential_key=credential_key,
            first_auth_id=_required(credential, "第一認証ID", municipality_name),
            first_auth_password=_required(credential, "第一認証PW", municipality_name),
            second_auth_id=_required(credential, "第二認証ID", municipality_name),
            second_auth_password=_required(credential, "第二認証PW", municipality_name),
            automatic_update=is_true(row.get("毎日自動更新")),
            automatic_update_verified=is_true(row.get("自動更新確認済み")),
            run_times=(
                parse_run_times(row.get("実行時刻"))
                if normalize(row.get("実行時刻"))
                else common_settings.default_run_times
            ),
        ))

    return configs


def load_municipality_configs(
    spreadsheet_id: str,
    credentials_path: Path,
    credential_spreadsheet_id: str = "",
    client_factory: Callable | None = None,
) -> list[MunicipalityConfig]:
    _, configs = load_automation_configuration(
        spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        credential_spreadsheet_id=credential_spreadsheet_id,
        client_factory=client_factory,
    )
    return configs


def load_automation_configuration(
    spreadsheet_id: str,
    credentials_path: Path,
    credential_spreadsheet_id: str = "",
    client_factory: Callable | None = None,
) -> tuple[CommonSettings, list[MunicipalityConfig]]:
    if not credentials_path.exists():
        raise FileNotFoundError(f"サービスアカウントJSONがありません: {credentials_path}")
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = _read_with_retry(lambda: client.open_by_key(spreadsheet_id))
    municipality_rows = _read_with_retry(
        lambda: spreadsheet.worksheet(MUNICIPALITY_SHEET_NAME).get_all_records()
    )
    credential_source_id = normalize(credential_spreadsheet_id) or spreadsheet_id
    credential_spreadsheet = (
        spreadsheet
        if credential_source_id == spreadsheet_id
        else _read_with_retry(lambda: client.open_by_key(credential_source_id))
    )
    credential_rows = _read_with_retry(
        lambda: credential_spreadsheet.worksheet(
            CREDENTIAL_SHEET_NAME
        ).get_all_records()
    )
    try:
        common_rows = _read_with_retry(
            lambda: spreadsheet.worksheet(COMMON_SHEET_NAME).get_all_records()
        )
        common_settings = build_common_settings(common_rows)
    except gspread.WorksheetNotFound:
        common_settings = DEFAULT_COMMON_SETTINGS
    configs = build_municipality_configs(
        municipality_rows, credential_rows, common_settings
    )
    return common_settings, configs


def configs_by_id(configs: list[MunicipalityConfig]) -> dict[str, MunicipalityConfig]:
    return {config.municipality_id: config for config in configs}
