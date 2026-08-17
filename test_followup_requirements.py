from dataclasses import replace
from datetime import datetime

from backlog_config import build_backlog_configs
from product_requests import (
    ProductCorrectionLine,
    ProductCorrectionRequest,
    ProductReference,
    build_backlog_issue_content,
)


def _request():
    return ProductCorrectionRequest(
        request_id="REQ-1", requested_at=datetime.now(), requester="担当者",
        municipality_id="m1", municipality_name="自治体",
        note="優先して対応してください。\n\n【関連ファイル】\nBOX URL：https://example.test",
    )


def _product():
    return ProductReference(
        municipality_id="m1", municipality_name="自治体", product_id="p1",
        original_product_id="", product_name="商品", business_id="b1", business_name="事業者",
        source_row=(("管理コード", "CODE-1"), ("（必須）表示有無", "1"), ("登録年度", "2025")),
    )


def test_backlog_uses_per_product_table_and_hides_automatic_fields():
    product = _product()
    lines = [
        ProductCorrectionLine(
            product, "説明", "旧", "新", display_name="商品説明",
            image_instruction="2枚目を差し替え",
        ),
        ProductCorrectionLine(product, "登録年度", "2025", "2026", display_name="登録年度"),
        ProductCorrectionLine(product, "（必須）表示有無", "1", "0", instruction="【自動設定】"),
    ]
    _, description = build_backlog_issue_content(_request(), lines)
    assert "| 変更項目 | 現在値 | 更新後 |" in description
    assert "| 商品説明 | 旧 | 新 |" in description
    assert "登録年度" not in description
    assert "表示有無" not in description
    assert "BOX URL" in description
    assert "画像修正指示：2枚目を差し替え" in description
    assert "画像修正指示：\n" not in description
    assert "| 品番 | CODE-1 | CODE-1 |" in description
    assert "| 商品名 | 商品 | 商品 |" in description


def test_backlog_config_accepts_product_code_routing_columns():
    config = build_backlog_configs([{
        "連携有効": "1", "自治体ID": "m1", "自治体名": "自治体",
        "BacklogスペースID": "space", "BacklogプロジェクトID": "1",
        "Backlog APIキー": "secret", "品番担当者ユーザーID": "10",
        "品番通知先ユーザーID": "10|20",
    }])[0]
    assert config.product_code_assignee_id == "10"
    assert config.product_code_notified_user_ids == ("10", "20")


def test_page_correction_template_and_table_use_business_priority_order():
    product = ProductReference(
        municipality_id="m1", municipality_name="自治体", product_id="p1",
        original_product_id="", product_name="旧商品 OLD-1", business_id="b1", business_name="事業者",
        source_row=(("管理コード", "OLD-1"), ("（条件付き必須）必要寄付金額", "10000")),
    )
    request = replace(_request(), request_unit="商品単位")
    lines = [
        ProductCorrectionLine(product, "説明", "旧説明", "新説明", display_name="商品説明"),
        ProductCorrectionLine(product, "【Backlogのみ】在庫数", "", "20", display_name="在庫数"),
        ProductCorrectionLine(product, "【Backlogのみ】商品代（税込）", "1200", "1400", display_name="商品代"),
        ProductCorrectionLine(product, "（条件付き必須）必要寄付金額", "10000", "12000", display_name="寄付額"),
        ProductCorrectionLine(product, "（必須）お礼の品名", "旧商品 OLD-1", "新商品 NEW-1", display_name="商品名"),
        ProductCorrectionLine(product, "管理コード", "OLD-1", "NEW-1", display_name="品番"),
    ]
    _, description = build_backlog_issue_content(request, lines)
    assert "【ページ修正テンプレート】" not in description
    assert "【商品の変更点】" not in description
    assert "■ 商品" not in description
    assert description.index("対応内容・備考：") < description.index("| 品番 | OLD-1 | NEW-1 |")
    assert "対応内容・備考：優先して対応してください。" in description
    assert "対応内容・備考：\n" not in description
    assert "品番：OLD-1 → NEW-1" not in description
    assert "商品名：旧商品 OLD-1 → 新商品 NEW-1" not in description
    assert "事業者名：事業者" not in description
    assert "| 品番 | OLD-1 | NEW-1 |" in description
    assert "| 商品名 | 旧商品 OLD-1 | 新商品 NEW-1 |" in description
    assert "| 寄附額 | 10000 | 12000 |" in description
    assert "| 在庫数 | （未設定） | 20 |" in description
    assert "| 商品代 | — | 1400（変更後商品代） |" in description
    assert description.rstrip().endswith("BOX URL：https://example.test")
    assert description.index("| 品番 |") < description.index("| 商品名 |")
    assert description.index("| 商品名 |") < description.index("| 寄附額 |")
    assert description.index("| 寄附額 |") < description.index("| 商品代 |")
    assert description.index("| 商品代 |") < description.index("| 在庫数 |")


def test_product_code_request_shows_current_code_and_blank_instruction():
    product = ProductReference(
        municipality_id="m1", municipality_name="自治体", product_id="p1",
        original_product_id="", product_name="商品 OLD-1",
        business_id="b1", business_name="事業者",
        source_row=(("管理コード", "OLD-1"),),
    )
    request = replace(_request(), request_unit="商品単位")
    lines = [ProductCorrectionLine(
        product, "【Backlogのみ】品番取得依頼", "OLD-1",
        "（空欄：品番を取得してください）", display_name="品番",
    )]
    _, description = build_backlog_issue_content(request, lines)
    assert "品番：OLD-1 → （空欄：品番を取得してください）" not in description
    assert "商品名：商品 OLD-1 → 商品" not in description
    assert "| 品番 | OLD-1 | （空欄：品番を取得してください） |" in description
    assert "| 商品名 | 商品 OLD-1 | 商品 |" in description
    assert "【商品の変更点】" not in description


def test_duplicate_product_name_lines_are_merged_and_use_new_code():
    product = ProductReference(
        municipality_id="m1", municipality_name="自治体", product_id="p1",
        original_product_id="", product_name="旧商品 OLD-1",
        business_id="b1", business_name="事業者",
        source_row=(("管理コード", "OLD-1"),),
    )
    request = replace(_request(), request_unit="商品単位")
    lines = [
        ProductCorrectionLine(
            product, "（必須）お礼の品名", "旧商品 OLD-1", "新しい商品 OLD-1",
            display_name="商品名",
        ),
        ProductCorrectionLine(
            product, "（必須）お礼の品名", "旧商品 OLD-1", "旧商品 NEW-1",
            display_name="商品名",
        ),
        ProductCorrectionLine(product, "管理コード", "OLD-1", "NEW-1", display_name="品番"),
    ]
    _, description = build_backlog_issue_content(request, lines)
    assert description.count("| 商品名 |") == 1
    assert "商品名：旧商品 OLD-1 → 新しい商品 NEW-1" not in description
    assert "| 商品名 | 旧商品 OLD-1 | 新しい商品 NEW-1 |" in description


def test_donation_correction_types_control_product_cost_input():
    source = __import__("pathlib").Path(__file__).with_name("request_form.py").read_text(
        encoding="utf-8"
    )
    assert '"寄附額変更（商品代変更アリ）"' in source
    assert '"寄附額変更（商品代変更ナシ）"' in source
    cost_section = source.index('st.subheader("商品代の変更")')
    cost_condition = source.rfind("if donation_with_cost_requested:", 0, cost_section)
    assert cost_condition >= 0
    no_cost_branch = source.index("elif donation_without_cost_requested:", cost_section)
    assert '"商品代変更": "商品代を変更しない"' in source[
        no_cost_branch:no_cost_branch + 400
    ]


def test_compound_donation_options_control_product_cost_input():
    source = __import__("pathlib").Path(__file__).with_name("request_form.py").read_text(
        encoding="utf-8"
    )
    assert 'COMPOUND_DONATION_WITH_COST_OPTION = "寄附額（商品代変更アリ）"' in source
    assert 'COMPOUND_DONATION_WITHOUT_COST_OPTION = "寄附額（商品代変更ナシ）"' in source
    assert "and COMPOUND_DONATION_WITH_COST_OPTION in selected_change_options" in source
    assert "and COMPOUND_DONATION_WITHOUT_COST_OPTION in selected_change_options" in source
    assert "if donation_with_cost_requested:" in source
    assert "and not _is_donation_field(field)" in source


def test_donation_field_detection_handles_master_label_variants():
    source = __import__("pathlib").Path(__file__).with_name("request_form.py").read_text(
        encoding="utf-8"
    )
    helper = source[source.index("def _is_donation_field"):source.index("def _sort_change_fields")]
    assert 'field.source_column == POINTS_COLUMN' in helper
    assert '("必要寄付金額", "寄附額", "寄付額")' in helper


def test_initial_request_flow_is_limited_to_correction_or_new_registration():
    source = __import__("pathlib").Path(__file__).with_name("request_form.py").read_text(
        encoding="utf-8"
    )
    assert 'REQUEST_MODES = ("修正", "新規商品登録")' in source
    assert '"依頼内容",\n            REQUEST_MODES' in source
    assert 'request_unit = "商品単位"' in source
    assert 'work_category = "新規商品登録" if request_mode == "新規商品登録" else "一般業務"' in source
    assert '"定期便・SKU展開を利用する（試験運用）"' in source
    assert 'product_shape = "単品"' in source
