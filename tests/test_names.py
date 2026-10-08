"""ファイル名と印。"""
import pytest

from lexcrew_pdf.names import output_filename, sanitize_filename_title, stamp_label


def test_filename_drops_windows_illegal_characters_and_keeps_the_fullwidth_colon():
    assert sanitize_filename_title("建物:賃貸*借/契約書") == "建物賃貸借契約書"
    assert "：" in output_filename("甲", 1, None, "建物：賃貸借契約書")
    filename = output_filename("甲", 1, None, "建物:賃貸*借/契約書")
    assert filename == "甲001：建物賃貸借契約書.pdf"
    assert ":" not in filename


def test_otsu_number_twelve_has_fullwidth_stamp_digits():
    assert stamp_label("乙", 12, None) == "乙第１２号証"
    assert output_filename("乙", 12, None, "証拠").startswith("乙012：")


def test_hei_branch_uses_halfwidth_in_the_filename():
    assert stamp_label("丙", 3, 3) == "丙第３号証の３"
    assert "丙003-3：" in output_filename("丙", 3, 3, "書名")


def test_empty_title_becomes_shoko():
    assert output_filename("甲", 1, None, "") == "甲001：証拠.pdf"
    assert output_filename("甲", 1, None, "   ") == "甲001：証拠.pdf"


def test_title_is_cut_at_120_characters():
    title = "あ" * 121
    cleaned = sanitize_filename_title(title)
    assert len(cleaned) <= 120
    assert not cleaned.endswith(" ")
    assert not cleaned.endswith(".")


def test_extra_series_are_accepted():
    assert stamp_label("丁", 1, None).startswith("丁")
    assert stamp_label("戊", 2, None).startswith("戊")


def test_preset_templates_keep_their_filename_heading():
    assert output_filename("丙第N号証", 1, None, "書") == "丙001：書.pdf"
    assert output_filename("疎甲第N号証", 1, None, "書") == "疎甲001：書.pdf"
    assert output_filename("疎甲第N号証", 1, 1, "書") == "疎甲001-1：書.pdf"
    assert output_filename("疎乙第N号証", 2, 1, "書") == "疎乙002-1：書.pdf"
    assert output_filename("疎丙第N号証", 3, 1, "書") == "疎丙003-1：書.pdf"
    assert output_filename("別紙N", 1, None, "書") == "別紙001：書.pdf"
    assert output_filename("資料N", 1, None, "契約書") == "資料001：契約書.pdf"
    assert stamp_label("疎甲第N号証", 1, 1) == "疎甲第１号証の１"
    assert stamp_label("別紙N", 2, None) == "別紙２"
    assert stamp_label("資料N", 1, None) == "資料１"


def test_template_without_n_is_rejected():
    with pytest.raises(ValueError):
        stamp_label("資料", 1, None)


def test_unknown_series_is_rejected():
    with pytest.raises(ValueError):
        stamp_label("A", 1, None)
    with pytest.raises(ValueError):
        output_filename("A", 1, None, "書名")


def test_branch_digits_differ_in_width():
    assert output_filename("甲", 4, 2, "更新契約書") == "甲004-2：更新契約書.pdf"
    assert "の２" in stamp_label("甲", 4, 2)
