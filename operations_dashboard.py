"""商品修正依頼の運用状況を集計する。"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gspread

from config_master import normalize
from product_requests import REQUEST_SHEET_NAME


@dataclass(frozen=True)
class RequestDashboardSummary:
    total_requests: int
    backlog_linked_requests: int
    image_work_requests: int
    status_rows: tuple[tuple[str, int], ...]
    municipality_rows: tuple[tuple[str, int], ...]


def build_request_dashboard_summary(rows: Iterable[dict]) -> RequestDashboardSummary:
    """商品修正依頼のヘッダー行から、画面表示用の集計値を作る。"""

    valid_rows = [row for row in rows if normalize(row.get("依頼ID"))]
    status_counts = Counter(
        normalize(row.get("状態")) or "未設定" for row in valid_rows
    )
    municipality_counts = Counter(
        normalize(row.get("自治体名")) or normalize(row.get("自治体ID")) or "未設定"
        for row in valid_rows
    )
    return RequestDashboardSummary(
        total_requests=len(valid_rows),
        backlog_linked_requests=sum(
            bool(normalize(row.get("Backlog親課題キー"))) for row in valid_rows
        ),
        image_work_requests=sum(
            normalize(row.get("画像作業有無")) == "あり" for row in valid_rows
        ),
        status_rows=tuple(sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))),
        municipality_rows=tuple(
            sorted(municipality_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
    )


def load_request_dashboard_summary(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> RequestDashboardSummary:
    """商品情報マスタから商品修正依頼の運用サマリを読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(REQUEST_SHEET_NAME).get_all_records()
    return build_request_dashboard_summary(rows)
