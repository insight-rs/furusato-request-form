"""商品修正依頼のBacklog状態を商品情報マスタへ同期する。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import gspread

from backlog_client import BacklogIssueStatus, get_issue_status
from backlog_config import BacklogConfig
from backlog_statuses import BacklogStatus, internal_status_for_backlog_status
from config_master import normalize
from product_requests import REQUEST_SHEET_NAME


JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class ProductRequestStatusUpdate:
    row_number: int
    request_id: str
    old_status: str
    new_status: str
    backlog_issue_key: str


@dataclass(frozen=True)
class ProductRequestStatusSyncResult:
    checked_count: int
    updated: tuple[ProductRequestStatusUpdate, ...]
    skipped_count: int
    failed_request_ids: tuple[str, ...]


def plan_status_updates(
    request_rows: Iterable[dict],
    backlog_configs: dict[str, BacklogConfig],
    backlog_statuses: Iterable[BacklogStatus],
    status_fetcher: Callable[[BacklogConfig, str], BacklogIssueStatus] = get_issue_status,
) -> ProductRequestStatusSyncResult:
    """同期対象を取得し、更新が必要な依頼行だけを計画する。"""

    updates = []
    failed_request_ids = []
    checked_count = 0
    skipped_count = 0
    statuses = list(backlog_statuses)

    for row_number, row in enumerate(request_rows, start=2):
        request_id = normalize(row.get("依頼ID"))
        municipality_id = normalize(row.get("自治体ID"))
        issue_key = normalize(row.get("Backlog親課題キー"))
        if not request_id or not municipality_id or not issue_key:
            skipped_count += 1
            continue
        config = backlog_configs.get(municipality_id)
        if config is None:
            skipped_count += 1
            continue

        checked_count += 1
        try:
            backlog_status = status_fetcher(config, issue_key)
        except Exception:
            failed_request_ids.append(request_id)
            continue
        new_status = internal_status_for_backlog_status(
            statuses, municipality_id, backlog_status.status_name
        )
        old_status = normalize(row.get("状態"))
        if new_status and new_status != old_status:
            updates.append(ProductRequestStatusUpdate(
                row_number=row_number,
                request_id=request_id,
                old_status=old_status,
                new_status=new_status,
                backlog_issue_key=issue_key,
            ))

    return ProductRequestStatusSyncResult(
        checked_count=checked_count,
        updated=tuple(updates),
        skipped_count=skipped_count,
        failed_request_ids=tuple(failed_request_ids),
    )


def sync_product_request_statuses(
    spreadsheet_id: str,
    credentials_path: Path,
    backlog_configs: dict[str, BacklogConfig],
    backlog_statuses: Iterable[BacklogStatus],
    client_factory: Callable | None = None,
    status_fetcher: Callable[[BacklogConfig, str], BacklogIssueStatus] = get_issue_status,
) -> ProductRequestStatusSyncResult:
    """Backlogを参照し、変更があった依頼の状態だけを更新する。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(REQUEST_SHEET_NAME)
    result = plan_status_updates(
        worksheet.get_all_records(), backlog_configs, backlog_statuses, status_fetcher
    )
    if not result.updated:
        return result

    now_text = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    updates = []
    for update in result.updated:
        updates.extend([
            {"range": f"I{update.row_number}", "values": [[update.new_status]]},
            {"range": f"L{update.row_number}", "values": [[now_text]]},
        ])
    worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    return result
