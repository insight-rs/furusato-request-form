"""ローカルPCとクラウドで共用する実行時設定。"""

from __future__ import annotations

import json
import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", PROJECT_DIR))
CONFIG_SPREADSHEET_ID = os.environ.get(
    "CONFIG_SPREADSHEET_ID", "1T7cCWkIJ8f5gFOmhi1eAqId7SwsIyfijfpI-CMegh_4"
)
PRODUCT_SPREADSHEET_ID = os.environ.get(
    "PRODUCT_SPREADSHEET_ID", "1k_yCwLMcwEbVT91jnkGUi-FhR69Doos-kHC8ibICA40"
)


def google_credentials_path() -> Path:
    """ローカルファイルまたはクラウド秘密情報から認証JSONを用意する。"""

    explicit_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if explicit_path:
        return Path(explicit_path)

    credentials_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not credentials_json:
        try:
            import streamlit as st

            credentials_json = str(
                st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
            ).strip()
        except Exception:
            credentials_json = ""
    if credentials_json:
        parsed = json.loads(credentials_json)
        runtime_dir = Path(os.environ.get("APP_RUNTIME_DIR", "/tmp/tsv_auto_runtime"))
        runtime_dir.mkdir(parents=True, exist_ok=True)
        destination = runtime_dir / "google-service-account.json"
        destination.write_text(
            json.dumps(parsed, ensure_ascii=False), encoding="utf-8"
        )
        return destination

    return DATA_DIR / "config" / "google-service-account.json"
