"""各種マスタの施策マスタを、依頼フォームの段階選択へ変換する。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gspread

from config_master import normalize


POLICY_SHEET_NAME = "施策マスタ"


@dataclass(frozen=True)
class PolicyMasterEntry:
    policy_id: str
    request_unit: str
    policy_type: str
    content: str
    detail: str
    recommended_issue_type: str
    reference_url: str = ""


def build_policy_entries(rows: Iterable[dict]) -> list[PolicyMasterEntry]:
    entries = []
    for row in rows:
        policy_id = normalize(row.get("施策ID"))
        request_unit = normalize(row.get("対応単位"))
        policy_type = normalize(row.get("種別"))
        content = normalize(row.get("具体内容"))
        if not (policy_id and request_unit and policy_type and content):
            continue
        entries.append(PolicyMasterEntry(
            policy_id=policy_id,
            request_unit=request_unit,
            policy_type=policy_type,
            content=content,
            detail=normalize(row.get("詳細")),
            recommended_issue_type=normalize(row.get("Backlog推奨種別")),
            reference_url=normalize(row.get("参照URL")),
        ))
    return entries


def _unique(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def policy_types(entries: Iterable[PolicyMasterEntry], request_unit: str) -> list[str]:
    target_unit = normalize(request_unit)
    return _unique(
        entry.policy_type for entry in entries if entry.request_unit == target_unit
    )


def policy_contents(
    entries: Iterable[PolicyMasterEntry], request_unit: str, policy_type: str
) -> list[str]:
    target_unit = normalize(request_unit)
    target_type = normalize(policy_type)
    return _unique(
        entry.content
        for entry in entries
        if entry.request_unit == target_unit and entry.policy_type == target_type
    )


def find_policy_entry(
    entries: Iterable[PolicyMasterEntry],
    request_unit: str,
    policy_type: str,
    content: str,
) -> PolicyMasterEntry | None:
    target = (normalize(request_unit), normalize(policy_type), normalize(content))
    return next((
        entry for entry in entries
        if (entry.request_unit, entry.policy_type, entry.content) == target
    ), None)


def load_policy_entries(
    spreadsheet_id: str,
    credentials_path: Path,
    client_factory: Callable | None = None,
) -> list[PolicyMasterEntry]:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"サービスアカウントJSONがありません: {credentials_path}"
        )
    factory = client_factory or gspread.service_account
    client = factory(filename=str(credentials_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    rows = spreadsheet.worksheet(POLICY_SHEET_NAME).get_all_records()
    return build_policy_entries(rows)
