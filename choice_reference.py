"""添付のチョイス参照表からフォーム用の選択肢を読み込む。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


CONFIG_DIR = Path(__file__).with_name("config")


@dataclass(frozen=True)
class ChoiceCategory:
    category_id: str
    major: str
    middle: str
    minor: str

    @property
    def leaf_label(self) -> str:
        return self.minor or self.middle or self.major


def _rows(path: Path) -> list[list[object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def load_local_product_standards() -> list[tuple[str, str]]:
    """「コード」「説明」の組を、添付シートの表示順で返す。"""

    result: list[tuple[str, str]] = []
    current_code = ""
    current_lines: list[str] = []
    for row in _rows(CONFIG_DIR / "local_product_standards.json"):
        text = str(row[0] if row else "").strip()
        if not text:
            continue
        normalized_text = text.replace("７号の３イ五万以下（宿泊）", "7の3イ（宿泊 五万以下）").replace(
            "７号の３ロ該当地域（宿泊）", "7の3ロ（宿泊 該当地域）"
        )
        match = re.match(r"^(3イ（熟成肉）|3イ（精米）|3ロ（企画立案）|7の2（宿泊）|7の3イ（宿泊 五万以下）|7の3ロ（宿泊 該当地域）|7の4（電気）|8[イロハ]|99|セット|[1-9])", normalized_text)
        if match:
            if current_code:
                result.append((current_code, " ".join(current_lines)))
            current_code = match.group(1)
            current_lines = [normalized_text]
        elif current_code:
            current_lines.append(text)
    if current_code:
        result.append((current_code, " ".join(current_lines)))
    return result


def load_choice_categories() -> list[ChoiceCategory]:
    result: list[ChoiceCategory] = []
    for row in _rows(CONFIG_DIR / "choice_categories.json")[1:]:
        values = list(row) + [None] * 4
        category_id = str(values[0] or "").strip()
        major = str(values[1] or "").strip()
        middle = str(values[2] or "").strip()
        minor = str(values[3] or "").strip()
        if category_id and major:
            result.append(ChoiceCategory(category_id, major, middle, minor))
    return result
