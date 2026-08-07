"""Backlog 連携用の設定を各種マスタから読み込む。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gspread

from config_master import ConfigError, is_true, normalize


BACKLOG_CONNECTION_SHEET_NAME = "Backlog接続設定"


@dataclass(frozen=True)
class BacklogConfig:
    """自治体ごとの Backlog 接続情報。

    api_key はスプレッドシートのアクセス権限で保護された値を保持する。
    エラー表示やログに api_key を含めてはならない。
    """

    municipality_id: str
    municipality_name: str
    team_name: str
    space_id: str
    project_id: str
    api_key: str
    api_key_storage_key: str
    image_child_issue_type: str
    product_correction_issue_type: str
    note: str
    product_code_assignee_id: str = ""
    product_code_notified_user_ids: tuple[str, ...] = ()


def _required(row: dict, field: str, label: str) -> str:
    value = normalize(row.get(field))
    if not value:
        raise ConfigError(f"{label}: {field} を入力してください。")
    return value


def build_backlog_configs(rows: list[dict]) -> list[BacklogConfig]:
    """有効な自治体の Backlog 接続設定だけを検証して返す。"""

    configs = []
    seen_ids = set()

    for row_number, row in enumerate(rows, start=2):
        if not is_true(row.get("連携有効")):
            continue

        label = normalize(row.get("自治体名")) or f"Backlog接続設定 {row_number}行目"
        municipality_id = _required(row, "自治体ID", label)
        if municipality_id in seen_ids:
            raise ConfigError(f"自治体ID {municipality_id} が重複しています。")
        seen_ids.add(municipality_id)

        notified_ids = tuple(
            value.strip() for value in normalize(row.get("品番通知先ユーザーID")).split("|")
            if value.strip()
        )
        configs.append(BacklogConfig(
            municipality_id=municipality_id,
            municipality_name=_required(row, "自治体名", municipality_id),
            team_name=normalize(row.get("チーム")),
            space_id=_required(row, "BacklogスペースID", municipality_id),
            project_id=_required(row, "BacklogプロジェクトID", municipality_id),
            api_key=_required(row, "Backlog APIキー", municipality_id),
            api_key_storage_key=normalize(row.get("APIキー保管先")),
            image_child_issue_type=normalize(row.get("画像子課題種別")),
            product_correction_issue_type=normalize(row.get("商品修正親課題種別")),
            note=normalize(row.get("備考")),
            product_code_assignee_id=normalize(row.get("品番担当者ユーザーID")),
            product_code_notified_user_ids=notified_ids,
        ))

    return configs


def load_backlog_configs(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[BacklogConfig]:
    """各種マスタの ``Backlog接続設定`` を読み込む。"""

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )

    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(BACKLOG_CONNECTION_SHEET_NAME).get_all_records()
    return build_backlog_configs(rows)


def backlog_configs_by_municipality_id(
    configs: list[BacklogConfig],
) -> dict[str, BacklogConfig]:
    """自治体IDをキーにした設定辞書を返す。"""

    return {config.municipality_id: config for config in configs}
