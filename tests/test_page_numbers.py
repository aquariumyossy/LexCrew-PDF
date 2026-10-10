"""ページ番号は初期状態でオフ。付けたときは出力 PDF ごとに 1 から振る。"""
import json
import os

import fitz
import pytest

from lexcrew_pdf.layout import default_layout, layout_to_json, load_layout, parse_layout
from lexcrew_pdf.plan import OutputJob, OutputPart
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import PAGE_NUMBER_SIZE, stamp_sources_to_pdf, yu_mincho_path
from lexcrew_pdf.write import write_jobs


def _pdf(path, texts):
    document = fitz.open()
    for text in texts:
        page = document.new_page(width=400, height=400)
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _use_stamp_font(monkeypatch) -> None:
    if os.path.isfile(yu_mincho_path()):
        return
    fallback = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    if not os.path.isfile(fallback):
        pytest.skip("游明朝がありません")
    monkeypatch.setattr("lexcrew_pdf.stamp.yu_mincho_path", lambda: fallback)


def _number_span(page, label):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["text"] == label:
                    return span
    raise AssertionError(label)


def test_page_numbers_are_off_unless_saved(tmp_path):
    assert default_layout().page_numbers is False
    assert "pageNumbers" not in layout_to_json(default_layout())
    missing = {
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
        "lastWritten": [],
    }
    assert parse_layout(missing).page_numbers is False
    with pytest.raises(ValueError):
        parse_layout({**missing, "pageNumbers": "yes"})

    session = Session(tmp_path)
    assert session.view()["pageNumbers"] is False
    session.set_page_numbers(True)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["pageNumbers"] is True
    assert load_layout(tmp_path).page_numbers is True
    session.set_series("乙")
    assert session.layout.page_numbers is True
    session.set_page_numbers(False)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "pageNumbers" not in raw
    session.set_page_numbers(True)
    session.clear()
    assert session.layout.page_numbers is False
    assert session.view()["pageNumbers"] is False


def test_numbers_restart_on_each_output_and_run_through_a_merged_file(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    first = tmp_path / "一.pdf"
    second = tmp_path / "二.pdf"
    third = tmp_path / "三.pdf"
    _pdf(first, ("ONE", "TWO"))
    _pdf(second, ("THREE",))
    _pdf(third, ("FOUR",))

    alone = fitz.open(stream=stamp_sources_to_pdf([str(third)], "甲第２号証", page_numbers=True), filetype="pdf")
    numbered = fitz.open(
        stream=stamp_sources_to_pdf([str(first)], "甲第１号証", page_numbers=True),
        filetype="pdf",
    )
    plain = fitz.open(stream=stamp_sources_to_pdf([str(first)], "甲第１号証"), filetype="pdf")
    try:
        assert "1 / 1" in alone[0].get_text()
        assert "2 / 2" not in alone[0].get_text()
        assert numbered.page_count == 2
        assert "1 / 2" not in plain[0].get_text()
        for index, label in enumerate(("1 / 2", "2 / 2")):
            page = numbered[index]
            span = _number_span(page, label)
            assert span["size"] == pytest.approx(PAGE_NUMBER_SIZE)
            box = span["bbox"]
            assert abs((box[0] + box[2]) / 2 - page.rect.width / 2) < 2
            assert box[3] > page.rect.height - 24
            assert box[2] - box[0] < 80
    finally:
        alone.close()
        numbered.close()
        plain.close()

    parts = (
        OutputPart("甲第１号証の１", "甲001-1", "一", ((0, 0, 0), (0, 1, 0)), 0, 0, 0, 0),
        OutputPart("甲第１号証の２", "甲001-2", "二", ((1, 0, 0),), 0, 0, 0, 1),
    )
    merged = fitz.open(
        stream=stamp_sources_to_pdf(
            [str(first), str(second)],
            "甲第１号証の１",
            page_numbers=True,
            parts=parts,
        ),
        filetype="pdf",
    )
    try:
        assert merged.page_count == 3
        assert [label for label in ("1 / 3", "2 / 3", "3 / 3")] == [
            _number_span(merged[index], label)["text"]
            for index, label in enumerate(("1 / 3", "2 / 3", "3 / 3"))
        ]
        assert "甲第１号証の１" in merged[0].get_text()
        assert "甲第１号証の２" not in merged[0].get_text()
        assert "甲第１号証の２" in merged[2].get_text()
    finally:
        merged.close()


def test_written_files_each_start_at_one(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    one = tmp_path / "one.pdf"
    two = tmp_path / "two.pdf"
    _pdf(one, ("AAA",))
    _pdf(two, ("BBB", "CCC"))
    jobs = (
        OutputJob(1, (str(one),), "甲第１号証", "甲001 一.pdf", 0, False, None),
        OutputJob(2, (str(two),), "甲第２号証", "甲002 二.pdf", 0, False, None),
    )
    write_jobs(tmp_path, jobs, last_written=(), page_numbers=True)
    dest = tmp_path / "LexCrew-PDF-Downloads"
    first_out = fitz.open(dest / "甲001 一.pdf")
    second_out = fitz.open(dest / "甲002 二.pdf")
    try:
        assert first_out[0].get_text().count("1 / 1") == 1
        assert "1 / 2" in second_out[0].get_text()
        assert "2 / 2" in second_out[1].get_text()
        assert "3 /" not in second_out[1].get_text()
    finally:
        first_out.close()
        second_out.close()
