"""Backlog APIの最小クライアント。

APIキーは各種マスタから受け取るだけで、ログや例外文字列には含めない。
"""

from dataclasses import dataclass
from datetime import date, datetime
import json
from mimetypes import guess_type
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from backlog_config import BacklogConfig
from config_master import ConfigError, normalize


class BacklogApiError(RuntimeError):
    """Backlog APIの呼び出しに失敗した場合の安全なエラー。"""


@dataclass(frozen=True)
class BacklogIssue:
    issue_id: str
    issue_key: str
    issue_url: str


@dataclass(frozen=True)
class BacklogIssueStatus:
    status_id: str
    status_name: str


RequestSender = Callable[[str, str, bytes | None], tuple[int, bytes]]
AttachmentRequestSender = Callable[[str, str, bytes, dict[str, str]], tuple[int, bytes]]


def backlog_base_url(space_id: str) -> str:
    """スペースIDまたはドメインからBacklogのベースURLを返す。"""

    source = normalize(space_id).removeprefix("https://").removeprefix("http://").strip("/")
    if not source:
        raise ConfigError("BacklogスペースIDが設定されていません。")
    if "." in source:
        return f"https://{source}"
    return f"https://{source}.backlog.com"


def _default_request_sender(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/x-www-form-urlencoded"} if data else {},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        raise BacklogApiError("Backlog APIへ接続できませんでした。") from error


def _default_attachment_request_sender(
    method: str,
    url: str,
    data: bytes,
    headers: dict[str, str],
) -> tuple[int, bytes]:
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        raise BacklogApiError("Backlog APIへ接続できませんでした。") from error


def _read_response(
    method: str,
    url: str,
    data: bytes | None,
    request_sender: RequestSender,
) -> dict:
    status, body = request_sender(method, url, data)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BacklogApiError("Backlog APIから有効な応答を受け取れませんでした。") from error
    if status < 200 or status >= 300:
        errors = payload.get("errors") if isinstance(payload, dict) else None
        error_codes = []
        if isinstance(errors, list):
            error_codes = [
                str(error.get("code")).strip()
                for error in errors
                if isinstance(error, dict) and str(error.get("code", "")).strip()
            ]
            error_messages = [
                normalize(error.get("message"))
                for error in errors
                if isinstance(error, dict) and normalize(error.get("message"))
            ]
        else:
            error_messages = []
        code_suffix = f"、エラーコード {', '.join(error_codes)}" if error_codes else ""
        message_suffix = f" 詳細: {' / '.join(error_messages[:2])}" if error_messages else ""
        raise BacklogApiError(
            f"Backlog APIの処理に失敗しました（HTTP {status}{code_suffix}）。"
            f"設定またはBacklog側の権限を確認してください。{message_suffix}"
        )
    if not isinstance(payload, dict):
        raise BacklogApiError("Backlog APIから想定外の応答を受け取りました。")
    return payload


def resolve_project_id(
    config: BacklogConfig,
    request_sender: RequestSender = _default_request_sender,
) -> str:
    """プロジェクトIDまたはプロジェクトキーを数値IDに解決する。"""

    project_id = normalize(config.project_id)
    if not project_id:
        raise ConfigError("BacklogプロジェクトIDが設定されていません。")
    if project_id.isdecimal():
        return project_id

    base_url = backlog_base_url(config.space_id)
    url = (
        f"{base_url}/api/v2/projects/{quote(project_id, safe='')}?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    payload = _read_response("GET", url, None, request_sender)
    resolved_id = normalize(payload.get("id"))
    if not resolved_id:
        raise BacklogApiError("BacklogプロジェクトIDを取得できませんでした。")
    return resolved_id


def create_issue(
    config: BacklogConfig,
    issue_type_id: str,
    summary: str,
    description: str,
    priority_id: str = "3",
    start_date: date | datetime | str | None = None,
    due_date: date | datetime | str | None = None,
    parent_issue_id: str = "",
    assignee_id: str = "",
    custom_field_parameters: Mapping[str, str | list[str]] | None = None,
    request_sender: RequestSender = _default_request_sender,
) -> BacklogIssue:
    """Backlogに親課題を1件起票する。"""

    normalized_summary = normalize(summary)
    normalized_issue_type_id = normalize(issue_type_id)
    if not normalized_summary:
        raise ConfigError("Backlog課題の件名を入力してください。")
    if not normalized_issue_type_id:
        raise ConfigError("Backlog課題種別IDが設定されていません。")

    base_url = backlog_base_url(config.space_id)
    project_id = resolve_project_id(config, request_sender)
    values = {
        "projectId": project_id,
        "summary": normalized_summary,
        "issueTypeId": normalized_issue_type_id,
        "priorityId": normalize(priority_id) or "3",
        "description": normalize(description),
    }
    normalized_start_date = _normalize_issue_date(start_date, "開始日")
    normalized_due_date = _normalize_issue_date(due_date, "期限日")
    if normalized_start_date:
        values["startDate"] = normalized_start_date
    if normalized_due_date:
        values["dueDate"] = normalized_due_date
    if normalize(parent_issue_id):
        values["parentIssueId"] = normalize(parent_issue_id)
    if normalize(assignee_id):
        values["assigneeId"] = normalize(assignee_id)
    for key, value in (custom_field_parameters or {}).items():
        normalized_key = normalize(key)
        if not normalized_key.startswith("customField_"):
            raise ConfigError("Backlogカスタム属性のパラメータ名が不正です。")
        values[normalized_key] = value
    body = urlencode(values, doseq=True).encode("utf-8")
    url = f"{base_url}/api/v2/issues?{urlencode({'apiKey': config.api_key})}"
    payload = _read_response("POST", url, body, request_sender)
    issue_key = normalize(payload.get("issueKey"))
    issue_id = normalize(payload.get("id"))
    if not issue_key:
        raise BacklogApiError("Backlog課題キーを取得できませんでした。")
    return BacklogIssue(
        issue_id=issue_id,
        issue_key=issue_key,
        issue_url=f"{base_url}/view/{quote(issue_key, safe='')}",
    )


def update_issue(
    config: BacklogConfig,
    issue_key: str,
    summary: str,
    description: str,
    priority_id: str = "3",
    start_date: date | datetime | str | None = None,
    due_date: date | datetime | str | None = None,
    assignee_id: str = "",
    custom_field_parameters: Mapping[str, str | list[str]] | None = None,
    request_sender: RequestSender = _default_request_sender,
) -> BacklogIssue:
    """既存のBacklog課題を、再編集した依頼内容で更新する。"""

    normalized_issue_key = normalize(issue_key)
    normalized_summary = normalize(summary)
    if not normalized_issue_key:
        raise ConfigError("更新するBacklog課題キーが設定されていません。")
    if not normalized_summary:
        raise ConfigError("Backlog課題の件名を入力してください。")

    values = {
        "summary": normalized_summary,
        "description": normalize(description),
        "priorityId": normalize(priority_id) or "3",
    }
    normalized_start_date = _normalize_issue_date(start_date, "開始日")
    normalized_due_date = _normalize_issue_date(due_date, "期限日")
    if normalized_start_date:
        values["startDate"] = normalized_start_date
    if normalized_due_date:
        values["dueDate"] = normalized_due_date
    if normalize(assignee_id):
        values["assigneeId"] = normalize(assignee_id)
    for key, value in (custom_field_parameters or {}).items():
        normalized_key = normalize(key)
        if not normalized_key.startswith("customField_"):
            raise ConfigError("Backlogカスタム属性のパラメータ名が不正です。")
        values[normalized_key] = value

    base_url = backlog_base_url(config.space_id)
    url = (
        f"{base_url}/api/v2/issues/{quote(normalized_issue_key, safe='')}?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    payload = _read_response(
        "PATCH", url, urlencode(values, doseq=True).encode("utf-8"), request_sender
    )
    returned_issue_key = normalize(payload.get("issueKey")) or normalized_issue_key
    return BacklogIssue(
        issue_id=normalize(payload.get("id")),
        issue_key=returned_issue_key,
        issue_url=f"{base_url}/view/{quote(returned_issue_key, safe='')}",
    )


def _normalize_issue_date(value: date | datetime | str | None, label: str) -> str:
    """Backlog APIへ渡す日付を YYYY-MM-DD に正規化する。"""

    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = normalize(value)
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ConfigError(f"{label}は YYYY-MM-DD 形式で入力してください。") from error


def get_issue_status(
    config: BacklogConfig,
    issue_key: str,
    request_sender: RequestSender = _default_request_sender,
) -> BacklogIssueStatus:
    """Backlog課題の現在の状態を取得する。"""

    normalized_issue_key = normalize(issue_key)
    if not normalized_issue_key:
        raise ConfigError("Backlog課題キーが設定されていません。")
    base_url = backlog_base_url(config.space_id)
    url = (
        f"{base_url}/api/v2/issues/{quote(normalized_issue_key, safe='')}?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    payload = _read_response("GET", url, None, request_sender)
    status = payload.get("status")
    if not isinstance(status, dict):
        raise BacklogApiError("Backlog課題の状態を取得できませんでした。")
    status_name = normalize(status.get("name"))
    if not status_name:
        raise BacklogApiError("Backlog課題の状態名を取得できませんでした。")
    return BacklogIssueStatus(
        status_id=normalize(status.get("id")),
        status_name=status_name,
    )


def upload_file(
    config: BacklogConfig,
    file_path: Path,
    request_sender: AttachmentRequestSender = _default_attachment_request_sender,
) -> str:
    """Backlogの添付一時領域へファイルをアップロードし、添付IDを返す。"""

    if not file_path.exists():
        raise FileNotFoundError(f"添付ファイルがありません: {file_path}")
    base_url = backlog_base_url(config.space_id)
    boundary = f"----furusato-{uuid4().hex}"
    file_name = file_path.name
    content_type = guess_type(file_name)[0] or "application/octet-stream"
    file_contents = file_path.read_bytes()
    body = b"".join([
        f"--{boundary}\r\n".encode("utf-8"),
        (
            "Content-Disposition: form-data; name=\"file\"; "
            f"filename=\"{file_name}\"\r\n"
        ).encode("utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
        file_contents,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    url = f"{base_url}/api/v2/space/attachment?{urlencode({'apiKey': config.api_key})}"
    status, response_body = request_sender(
        "POST", url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    if status < 200 or status >= 300:
        raise BacklogApiError("Backlogへの添付アップロードに失敗しました。")
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BacklogApiError("Backlog添付の応答を確認できませんでした。") from error
    attachment_id = normalize(payload.get("id")) if isinstance(payload, dict) else ""
    if not attachment_id:
        raise BacklogApiError("Backlog添付IDを取得できませんでした。")
    return attachment_id


def attach_file_to_issue(
    config: BacklogConfig,
    issue_key: str,
    file_path: Path,
    upload_request_sender: AttachmentRequestSender = _default_attachment_request_sender,
    request_sender: RequestSender = _default_request_sender,
) -> None:
    """ファイルをアップロードし、指定したBacklog課題へ添付する。"""

    normalized_issue_key = normalize(issue_key)
    if not normalized_issue_key:
        raise ConfigError("Backlog課題キーが設定されていません。")
    attachment_id = upload_file(config, file_path, upload_request_sender)
    base_url = backlog_base_url(config.space_id)
    url = (
        f"{base_url}/api/v2/issues/{quote(normalized_issue_key, safe='')}?"
        f"{urlencode({'apiKey': config.api_key})}"
    )
    data = urlencode({"attachmentId[]": attachment_id}).encode("utf-8")
    status, response_body = request_sender("PATCH", url, data)
    if status < 200 or status >= 300:
        error_codes = []
        error_messages = []
        try:
            payload = json.loads(response_body.decode("utf-8"))
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if isinstance(errors, list):
                error_codes = [
                    normalize(error.get("code"))
                    for error in errors
                    if isinstance(error, dict) and normalize(error.get("code"))
                ]
                error_messages = [
                    normalize(error.get("message"))
                    for error in errors
                    if isinstance(error, dict) and normalize(error.get("message"))
                ]
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        code_suffix = f"、エラーコード {', '.join(error_codes)}" if error_codes else ""
        message_suffix = f" 詳細: {' / '.join(error_messages[:2])}" if error_messages else ""
        raise BacklogApiError(
            f"Backlog課題への添付に失敗しました（HTTP {status}{code_suffix}）。"
            f"{message_suffix}"
        )
