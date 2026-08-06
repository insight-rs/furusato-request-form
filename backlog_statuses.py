"""各種マスタに同期済みのBacklog状態を参照する。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gspread

from config_master import normalize


STATUS_SHEET_NAME = "状態マスタ"
LEGACY_STATUS_SHEET_NAME = "08_状態マスタ"


@dataclass(frozen=True)
class BacklogStatus:
    municipality_id: str
    municipality_name: str
    project_id: str
    name: str
    status_id: str
    recommended_internal_status: str
    requires_confirmation: bool


def build_backlog_statuses(rows: Iterable[dict]) -> list[BacklogStatus]:
    """状態マスタの完全な行だけを状態同期に利用する。"""

    statuses = []
    for row in rows:
        municipality_id = normalize(row.get("自治体ID"))
        name = normalize(row.get("状態名"))
        status_id = normalize(row.get("状態ID"))
        if not municipality_id or not name or not status_id:
            continue
        statuses.append(BacklogStatus(
            municipality_id=municipality_id,
            municipality_name=normalize(row.get("自治体名")),
            project_id=normalize(row.get("プロジェクトID")),
            name=name,
            status_id=status_id,
            recommended_internal_status=normalize(row.get("推奨社内共通状態")),
            requires_confirmation=normalize(row.get("要確認")).lower()
            in {"true", "1", "yes", "はい"},
        ))
    return statuses


def internal_status_for_backlog_status(
    statuses: Iterable[BacklogStatus],
    municipality_id: str,
    backlog_status_name: str,
) -> str:
    """Backlogの状態名を商品修正依頼に書く社内状態へ変換する。"""

    target_municipality_id = normalize(municipality_id)
    target_status_name = normalize(backlog_status_name)
    for status in statuses:
        if (
            status.municipality_id == target_municipality_id
            and status.name == target_status_name
        ):
            return status.recommended_internal_status or status.name
    return target_status_name


def load_backlog_statuses(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[BacklogStatus]:
    """各種マスタの状態マスタを新旧タブ名に対応して読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(STATUS_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.worksheet(LEGACY_STATUS_SHEET_NAME)
    return build_backlog_statuses(worksheet.get_all_records())
