"""ファイル名と印。"""
import pytest

from lexcrew_pdf.names import (
    MAX_FILENAME_CHARS,
    document_title,
    exhibit_number,
    filename_prefix,
    require_first_number,
    shown_number,
    output_filename,
    sanitize_filename_title,
    stamp_label,
    strip_leading_exhibit_number,
)


def test_filename_drops_windows_illegal_characters_and_keeps_the_fullwidth_colon():
    assert sanitize_filename_title("建物:賃貸*借/契約書") == "建物賃貸借契約書"
    assert output_filename("甲", 1, None, "建物：賃貸借契約書") == "甲001 建物：賃貸借契約書.pdf"
    filename = output_filename("甲", 1, None, "建物:賃貸*借/契約書")
    assert filename == "甲001 建物賃貸借契約書.pdf"
    assert ":" not in filename


def test_number_and_title_are_joined_by_a_space():
    assert output_filename("甲", 1, None, "売買契約書") == "甲001 売買契約書.pdf"
    assert output_filename("甲", 4, 2, "更新契約書") == "甲004-2 更新契約書.pdf"


def test_otsu_number_twelve_has_fullwidth_stamp_digits():
    assert stamp_label("乙", 12, None) == "乙第１２号証"
    assert output_filename("乙", 12, None, "証拠").startswith("乙012 ")


def test_hei_branch_uses_halfwidth_in_the_filename():
    assert stamp_label("丙", 3, 3) == "丙第３号証の３"
    assert "丙003-3 " in output_filename("丙", 3, 3, "書名")


def test_empty_title_becomes_shoko():
    assert output_filename("甲", 1, None, "") == "甲001 証拠.pdf"
    assert output_filename("甲", 1, None, "   ") == "甲001 証拠.pdf"


def test_filename_including_extension_is_at_most_100_characters():
    plain = output_filename("甲", 1, None, "あ" * 200)
    assert len(plain) == MAX_FILENAME_CHARS
    assert plain.startswith("甲001 ")
    assert plain.endswith(".pdf")
    assert not plain[:-4].endswith(" ")
    assert not plain[:-4].endswith(".")
    ranged = output_filename("疎甲第N号証", 12, 1, "あ" * 200, branch_end=10)
    assert len(ranged) <= MAX_FILENAME_CHARS
    assert ranged.startswith("疎甲012-1~10 ")
    assert ranged.endswith(".pdf")
    dotted = output_filename("甲", 1, None, "あ." * 80)
    assert len(dotted) <= MAX_FILENAME_CHARS
    assert not dotted[:-4].endswith(".")
    assert not dotted[:-4].endswith(" ")
    short = output_filename("甲", 1, None, "あ" * 91)
    assert len(short) == MAX_FILENAME_CHARS
    longer = output_filename("甲", 1, None, "あ" * 92)
    assert longer == short
    kept = output_filename("甲", 1, None, "売買契約書")
    assert kept == "甲001 売買契約書.pdf"


def test_extra_series_are_accepted():
    assert stamp_label("丁", 1, None).startswith("丁")
    assert stamp_label("戊", 2, None).startswith("戊")


def test_preset_templates_keep_their_filename_heading():
    assert output_filename("丙第N号証", 1, None, "書") == "丙001 書.pdf"
    assert output_filename("疎甲第N号証", 1, None, "書") == "疎甲001 書.pdf"
    assert output_filename("疎甲第N号証", 1, 1, "書") == "疎甲001-1 書.pdf"
    assert output_filename("疎乙第N号証", 2, 1, "書") == "疎乙002-1 書.pdf"
    assert output_filename("疎丙第N号証", 3, 1, "書") == "疎丙003-1 書.pdf"
    assert output_filename("別紙N", 1, None, "書") == "別紙001 書.pdf"
    assert output_filename("資料N", 1, None, "契約書") == "資料001 契約書.pdf"
    assert stamp_label("疎甲第N号証", 1, 1) == "疎甲第１号証の１"
    assert stamp_label("別紙N", 2, None) == "別紙２"
    assert stamp_label("資料N", 1, None) == "資料１"


def test_party_letter_is_kept_in_the_filename_prefix():
    assert filename_prefix("乙A第N号証") == "乙A"
    assert filename_prefix("甲B第N号証") == "甲B"
    assert filename_prefix("丙第N号証") == "丙"
    assert filename_prefix("疎乙B第N号証") == "疎乙B"
    assert filename_prefix("丁A第N号証") == "丁A"
    assert filename_prefix("戊C第N号証") == "戊C"
    assert output_filename("乙A第N号証", 1, None, "準備書面") == "乙A001 準備書面.pdf"
    assert output_filename("甲B第N号証", 2, 1, "書") == "甲B002-1 書.pdf"
    assert output_filename("丙Ｃ第N号証", 3, None, "書") == "丙C003 書.pdf"
    assert output_filename("乙A第N号証", 1, 1, "準備書面", branch_end=3) == "乙A001-1~3 準備書面.pdf"
    assert stamp_label("乙A第N号証", 1, 1) == "乙A第１号証の１"
    assert stamp_label("丙Ｃ第N号証", 1, None) == "丙Ｃ第１号証"
    assert exhibit_number("甲第N号証", 1, None) == "甲001"
    assert exhibit_number("甲", 1, 1) == "甲001-1"
    assert exhibit_number("乙A第N号証", 1, None) == "乙A001"
    assert exhibit_number("乙A第N号証", 2, 3) == "乙A002-3"
    assert exhibit_number("丙Ｃ第N号証", 3, None) == "丙C003"
    assert not output_filename("乙A第N号証", 1, None, "書").startswith("乙A第")


def test_branch_range_uses_a_tilde_between_the_first_and_last():
    assert output_filename("甲", 1, 1, "売買契約書", branch_end=3) == "甲001-1~3 売買契約書.pdf"
    assert output_filename("甲", 1, 2, "書", branch_end=2) == "甲001-2 書.pdf"
    with pytest.raises(ValueError):
        output_filename("甲", 1, None, "書", branch_end=3)
    with pytest.raises(ValueError):
        output_filename("甲", 1, 3, "書", branch_end=1)


def test_template_without_n_is_rejected():
    with pytest.raises(ValueError):
        stamp_label("資料", 1, None)


def test_shown_number_counts_from_the_first_number():
    assert shown_number(1, 1) == 1
    assert shown_number(7, 1) == 7
    assert shown_number(7, 6) == 12
    assert require_first_number(7.0) == 7
    with pytest.raises(ValueError, match="開始番号は1から9999までの整数です。"):
        require_first_number(0)
    with pytest.raises(ValueError, match="開始番号は1から9999までの整数です。"):
        require_first_number(7.5)
    with pytest.raises(ValueError, match="開始番号は1から9999までの整数です。"):
        require_first_number(10000)
    with pytest.raises(ValueError, match="開始番号は1から9999までの整数です。"):
        require_first_number(True)


def test_unknown_series_is_rejected():
    with pytest.raises(ValueError):
        stamp_label("A", 1, None)
    with pytest.raises(ValueError):
        output_filename("A", 1, None, "書名")


def test_branch_digits_differ_in_width():
    assert output_filename("甲", 4, 2, "更新契約書") == "甲004-2 更新契約書.pdf"
    assert "の２" in stamp_label("甲", 4, 2)


def test_fallback_title_drops_a_leading_exhibit_number():
    assert strip_leading_exhibit_number("甲1 売買契約書") == "売買契約書"
    assert strip_leading_exhibit_number("甲第2号証_契約書") == "契約書"
    assert strip_leading_exhibit_number("乙3の1 納品書") == "納品書"
    assert strip_leading_exhibit_number("乙Ａ第１号証の２　領収書") == "領収書"
    assert strip_leading_exhibit_number("甲001-1~3 書名") == "書名"
    assert strip_leading_exhibit_number("甲001：契約書") == "契約書"
    assert strip_leading_exhibit_number("疎甲001-2 書") == "書"
    assert strip_leading_exhibit_number("甲第２号証の１_書") == "書"
    assert strip_leading_exhibit_number("5.建物評価証明書") == "5.建物評価証明書"
    assert strip_leading_exhibit_number("甲府の地図") == "甲府の地図"
    assert strip_leading_exhibit_number("甲1000円の領収書") == "甲1000円の領収書"
    assert strip_leading_exhibit_number("甲第2号証") == ""
    assert document_title("甲1 残す", "甲9 原本.pdf") == "甲1 残す"
    assert document_title("", "甲1 売買契約書.pdf") == "売買契約書"
    assert document_title("", "甲第2号証_契約書.PDF") == "契約書"
    assert document_title("", "乙3の1 納品書.pdf") == "納品書"
    assert document_title("", "甲1 売買契約書.jpg") == "売買契約書"
    assert document_title("", "甲第2号証_契約書.JPEG") == "契約書"
    assert document_title("", "乙3の1 納品書.png") == "納品書"
    assert document_title("", "甲001-1~3 書名.jpeg") == "書名"
    assert document_title("甲1 残す", "甲9 原本.jpg") == "甲1 残す"
    assert document_title("  ", None) == ""
