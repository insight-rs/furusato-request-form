"""Backlogプロジェクトの担当者候補をユーザー権限マスタと同期する。"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

import gspread

from backlog_client import BacklogApiError, backlog_base_url, resolve_project_id
from backlog_config import BacklogConfig
from config_master import ConfigError, normalize


USER_SHEET_NAME = "ユーザー権限マスタ"


@dataclass(frozen=True)
class BacklogProjectUser:
    municipality_id: str
    municipality_name: str
    project_id: str
    user_id: str
    name: str
    mail_address: str

    @property
    def display_name(self) -> str:
        return f"{self.name}（{self.mail_address}）" if self.mail_address else self.name


@dataclass(frozen=True)
class BacklogProjectTeam:
    team_id: str
    name: str
    member_user_ids: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return f"@{self.name}（{len(self.member_user_ids)}名）"


def build_backlog_project_users(rows: Iterable[dict]) -> list[BacklogProjectUser]:
    """ユーザー権限マスタのBacklogユーザーIDを持つ行だけを候補化する。"""

    users = []
    for row in rows:
        municipality_id = normalize(row.get("自治体ID"))
        user_id = normalize(row.get("BacklogユーザーID"))
        name = normalize(row.get("Backlogユーザー名"))
        if not municipality_id or not user_id or not name:
            continue
        users.append(BacklogProjectUser(
            municipality_id=municipality_id,
            municipality_name=normalize(row.get("担当自治体・プロジェクト")).split(" / ")[0],
            project_id=normalize(row.get("担当自治体・プロジェクト")).split(" / ")[-1],
            user_id=user_id,
            name=name,
            mail_address=normalize(row.get("Backlog登録メールアドレス")),
        ))
    return users


def get_project_users(
    users: Iterable[BacklogProjectUser], municipality_id: str
) -> list[BacklogProjectUser]:
    """自治体のBacklog担当者候補を表示名順で返す。"""

    return sorted(
        [user for user in users if user.municipality_id == normalize(municipality_id)],
        key=lambda user: (user.name.casefold(), user.user_id),
    )


def load_backlog_project_users(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[BacklogProjectUser]:
    """各種マスタのユーザー権限マスタを読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(f"サービスアカウントJSONがありません: {credentials_path}")
    factory = client_factory or gspread.service_account
    spreadsheet = factory(filename=str(credentials_path)).open_by_key(spreadsheet_id)
    return build_backlog_project_users(spreadsheet.worksheet(USER_SHEET_NAME).get_all_records())


def fetch_backlog_project_users(config: BacklogConfig) -> list[dict]:
    """Backlogからプロジェクトメンバーを取得する。"""

    project_id = resolve_project_id(config)
    url = (
        f"{backlog_base_url(config.space_id)}/api/v2/projects/{project_id}/users?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    try:
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise BacklogApiError("Backlogプロジェクトメンバーを取得できませんでした。") from error
    if not isinstance(payload, list):
        raise BacklogApiError("Backlogプロジェクトメンバーの応答形式が不正です。")
    return [row for row in payload if isinstance(row, dict)]


def fetch_backlog_project_teams(config: BacklogConfig) -> list[BacklogProjectTeam]:
    """プロジェクトに登録されたBacklogチームと所属メンバーを取得する。"""

    project_id = resolve_project_id(config)
    url = (
        f"{backlog_base_url(config.space_id)}/api/v2/projects/{project_id}/teams?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    try:
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise BacklogApiError("Backlogプロジェクトチームを取得できませんでした。") from error
    if not isinstance(payload, list):
        raise BacklogApiError("Backlogプロジェクトチームの応答形式が不正です。")
    teams = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        member_ids = tuple(
            normalize(member.get("id"))
            for member in row.get("members", [])
            if isinstance(member, dict) and normalize(member.get("id"))
        )
        if normalize(row.get("id")) and normalize(row.get("name")):
            teams.append(BacklogProjectTeam(
                team_id=normalize(row.get("id")),
                name=normalize(row.get("name")),
                member_user_ids=member_ids,
            ))
    return sorted(teams, key=lambda team: team.name.casefold())


def sync_backlog_project_users(
    spreadsheet_id: str,
    credentials_path: Path,
    configs: Iterable[BacklogConfig],
    client_factory: Callable | None = None,
) -> int:
    """有効な自治体のユーザー候補を同期し、反映行数を返す。"""

    config_list = list(configs)
    if not config_list:
        return 0
    factory = client_factory or gspread.service_account
    spreadsheet = factory(filename=str(credentials_path)).open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(USER_SHEET_NAME)
    values = worksheet.get_all_values()
    if not values:
        raise ConfigError("ユーザー権限マスタのヘッダーがありません。")
    headers = values[0]
    required_headers = {
        "Backlogユーザー名", "Backlog登録メールアドレス", "担当自治体・プロジェクト",
        "Googleログイン用アドレス", "属性", "自治体ID", "BacklogユーザーID",
    }
    if not required_headers.issubset(headers):
        raise ConfigError("ユーザー権限マスタの列が不足しています。")
    indexes = {header: index for index, header in enumerate(headers)}
    target_ids = {config.municipality_id for config in config_list}
    retained_rows = [
        row for row in values[1:]
        if len(row) <= indexes["自治体ID"] or row[indexes["自治体ID"]].strip() not in target_ids
    ]
    synced_rows = []
    for config in config_list:
        for user in fetch_backlog_project_users(config):
            mail_address = normalize(user.get("mailAddress"))
            row = {
                "Backlogユーザー名": normalize(user.get("name")),
                "Backlog登録メールアドレス": mail_address,
                "担当自治体・プロジェクト": f"{config.municipality_name} / {config.project_id}",
                "Googleログイン用アドレス": mail_address,
                "属性": "Backlogプロジェクトメンバー",
                "自治体ID": config.municipality_id,
                "BacklogユーザーID": normalize(user.get("id")),
            }
            if row["Backlogユーザー名"] and row["BacklogユーザーID"]:
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
