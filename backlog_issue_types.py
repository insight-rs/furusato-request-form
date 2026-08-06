"""各種マスタに同期済みのBacklog課題種別を参照する。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gspread

from config_master import ConfigError, normalize


ISSUE_TYPE_SHEET_NAME = "種別マスタ"
LEGACY_ISSUE_TYPE_SHEET_NAME = "07_種別マスタ"


@dataclass(frozen=True)
class BacklogIssueType:
    municipality_id: str
    municipality_name: str
    project_id: str
    name: str
    issue_type_id: str


def build_backlog_issue_types(rows: Iterable[dict]) -> list[BacklogIssueType]:
    """課題種別マスタの完全な行だけを利用可能な課題種別に整形する。"""

    issue_types = []
    for row in rows:
        municipality_id = normalize(row.get("自治体ID"))
        name = normalize(row.get("種別名"))
        issue_type_id = normalize(row.get("種別ID"))
        if not municipality_id or not name or not issue_type_id:
            continue
        issue_types.append(BacklogIssueType(
            municipality_id=municipality_id,
            municipality_name=normalize(row.get("自治体名")),
            project_id=normalize(row.get("プロジェクトID")),
            name=name,
            issue_type_id=issue_type_id,
        ))
    return issue_types


def find_backlog_issue_type(
    issue_types: Iterable[BacklogIssueType],
    municipality_id: str,
    issue_type_name: str,
) -> BacklogIssueType:
    """自治体と種別名で、Backlog起票に使う種別IDを取得する。"""

    target_municipality_id = normalize(municipality_id)
    target_name = normalize(issue_type_name)
    if not target_name:
        raise ConfigError("商品修正親課題種別が設定されていません。")
    for issue_type in issue_types:
        if (
            issue_type.municipality_id == target_municipality_id
            and issue_type.name == target_name
        ):
            return issue_type
    raise ConfigError(
        f"自治体ID {target_municipality_id} に課題種別「{target_name}」がありません。"
    )


def load_backlog_issue_types(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[BacklogIssueType]:
    """各種マスタの ``種別マスタ`` を読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(ISSUE_TYPE_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.worksheet(LEGACY_ISSUE_TYPE_SHEET_NAME)
    rows = worksheet.get_all_records()
    return build_backlog_issue_types(rows)
