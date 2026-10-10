"""頁番号は初期状態でオフ。付けたとき、2ページ以上の出力 PDF ごとに 1 から振る。"""
import json
import os
from dataclasses import replace

import fitz
import pytest

from lexcrew_pdf.layout import default_layout, layout_to_json, load_layout, parse_layout
from lexcrew_pdf.plan import OutputJob, OutputPart, page_label
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import (
    DEFAULT_PAGE_NUMBERS,
    PAGE_NUMBER_MARGIN,
    PAGE_NUMBER_SIZE,
    render_piece_jpeg,
    render_stamped_page_jpeg,
    stamp_sources_to_pdf,
    yu_mincho_path,
)
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


def _on(**kwargs):
    return replace(DEFAULT_PAGE_NUMBERS, enabled=True, **kwargs)


def _plain(text: str) -> str:
    return text.replace("\xa0", " ")


def _number_span(page, label):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if _plain(span["text"]) == label:
                    return span
    raise AssertionError(label)


def _bare_layout():
    return {
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
        "lastWritten": [],
    }


def test_page_numbers_are_off_unless_saved(tmp_path):
    assert default_layout().page_numbers == DEFAULT_PAGE_NUMBERS
    assert "pageNumbers" not in layout_to_json(default_layout())
    missing = _bare_layout()
    assert parse_layout(missing).page_numbers == DEFAULT_PAGE_NUMBERS
    legacy = parse_layout({**missing, "pageNumbers": True})
    assert legacy.page_numbers == _on()
    assert parse_layout({**missing, "pageNumbers": False}).page_numbers == DEFAULT_PAGE_NUMBERS
    with pytest.raises(ValueError):
        parse_layout({**missing, "pageNumbers": "yes"})
    with pytest.raises(ValueError):
        parse_layout({**missing, "pageNumbers": {"place": "top"}})

    session = Session(tmp_path)
    assert session.view()["pageNumbers"]["enabled"] is False
    assert session.view()["pageNumbers"]["place"] == "center"
    assert session.view()["pageNumbers"]["pattern"] == "n/N"
    kept = parse_layout({**missing, "pageNumbers": {"enabled": True}})
    assert kept.page_numbers.pattern == "n/N"
    with pytest.raises(ValueError):
        parse_layout({**missing, "pageNumbers": {"pattern": "page"}})
    session.set_page_number_style(True, "#000000", 8, "mincho", "center")
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["pageNumbers"]["enabled"] is True
    assert raw["pageNumbers"]["color"] == "#000000"
    assert raw["pageNumbers"]["size"] == 8
    assert raw["pageNumbers"]["font"] == "mincho"
    assert raw["pageNumbers"]["place"] == "center"
    assert load_layout(tmp_path).page_numbers == _on()
    session.set_series("乙")
    assert session.layout.page_numbers == _on()
    session.set_page_number_style(False, "#000000", 8, "mincho", "center")
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "pageNumbers" not in raw
    session.set_page_number_style(True, "#ff0000", 14, "mincho", "left")
    session.clear()
    assert session.layout.page_numbers == DEFAULT_PAGE_NUMBERS
    assert session.view()["pageNumbers"]["enabled"] is False


def test_numbers_restart_on_each_branch_even_inside_one_file(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    first = tmp_path / "一.pdf"
    second = tmp_path / "二.pdf"
    third = tmp_path / "三.pdf"
    _pdf(first, ("ONE", "TWO"))
    _pdf(second, ("THREE",))
    _pdf(third, ("FOUR",))

    alone = fitz.open(stream=stamp_sources_to_pdf([str(third)], "甲第２号証", page_numbers=_on()), filetype="pdf")
    numbered = fitz.open(
        stream=stamp_sources_to_pdf([str(first)], "甲第１号証", page_numbers=_on()),
        filetype="pdf",
    )
    plain = fitz.open(stream=stamp_sources_to_pdf([str(first)], "甲第１号証"), filetype="pdf")
    try:
        assert "1 / 1" not in _plain(alone[0].get_text())
        assert numbered.page_count == 2
        assert "1 / 2" not in _plain(plain[0].get_text())
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
            page_numbers=_on(),
            parts=parts,
        ),
        filetype="pdf",
    )
    try:
        assert merged.page_count == 3
        assert _plain(_number_span(merged[0], "1 / 2")["text"]) == "1 / 2"
        assert _plain(_number_span(merged[1], "2 / 2")["text"]) == "2 / 2"
        assert "1 / 3" not in _plain(merged[2].get_text())
        assert "3 / 3" not in _plain(merged[2].get_text())
        assert "1 / 1" not in _plain(merged[2].get_text())
        assert "甲第１号証の１" in merged[0].get_text()
        assert "甲第１号証の２" not in merged[0].get_text()
        assert "甲第１号証の２" in merged[2].get_text()
    finally:
        merged.close()

    later = tmp_path / "四.pdf"
    _pdf(later, ("FIVE", "SIX"))
    both = (
        OutputPart("甲第１号証の１", "甲001-1", "一", ((0, 0, 0), (0, 1, 0)), 0, 0, 0, 0),
        OutputPart("甲第１号証の２", "甲001-2", "四", ((1, 0, 0), (1, 1, 0)), 0, 0, 0, 1),
    )
    restarted = fitz.open(
        stream=stamp_sources_to_pdf(
            [str(first), str(later)],
            "甲第１号証の１",
            page_numbers=_on(),
            parts=both,
        ),
        filetype="pdf",
    )
    try:
        assert restarted.page_count == 4
        assert [_plain(_number_span(restarted[index], label)["text"]) for index, label in enumerate(
            ("1 / 2", "2 / 2", "1 / 2", "2 / 2")
        )] == ["1 / 2", "2 / 2", "1 / 2", "2 / 2"]
        assert "3 / 4" not in _plain(restarted[2].get_text())
    finally:
        restarted.close()


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
    write_jobs(tmp_path, jobs, last_written=(), page_numbers=_on())
    dest = tmp_path / "LexCrew-PDF-Downloads"
    first_out = fitz.open(dest / "甲001 一.pdf")
    second_out = fitz.open(dest / "甲002 二.pdf")
    try:
        assert "1 / 1" not in _plain(first_out[0].get_text())
        assert "1 / 2" in _plain(second_out[0].get_text())
        assert "2 / 2" in _plain(second_out[1].get_text())
        assert "3 /" not in _plain(second_out[1].get_text())
    finally:
        first_out.close()
        second_out.close()


def test_page_number_place_size_and_color(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    path = tmp_path / "two.pdf"
    _pdf(path, ("A", "B"))
    left = fitz.open(
        stream=stamp_sources_to_pdf(
            [str(path)],
            "甲第１号証",
            page_numbers=_on(place="left", size=16, color=(1.0, 0.0, 0.0)),
        ),
        filetype="pdf",
    )
    try:
        page = left[0]
        span = _number_span(page, "1 / 2")
        assert span["size"] == pytest.approx(16)
        assert span["color"] == 0xFF0000
        assert span["bbox"][0] == pytest.approx(PAGE_NUMBER_MARGIN, abs=2)
    finally:
        left.close()

    right = fitz.open(
        stream=stamp_sources_to_pdf(
            [str(path)],
            "甲第１号証",
            page_numbers=_on(place="right"),
        ),
        filetype="pdf",
    )
    try:
        page = right[0]
        span = _number_span(page, "1 / 2")
        assert span["bbox"][2] == pytest.approx(page.rect.width - PAGE_NUMBER_MARGIN, abs=2)
    finally:
        right.close()

    plain = fitz.open(
        stream=stamp_sources_to_pdf(
            [str(path)],
            "甲第１号証",
            page_numbers=_on(pattern="n", place="right"),
        ),
        filetype="pdf",
    )
    try:
        assert "1 / 2" not in _plain(plain[0].get_text())
        span = _number_span(plain[0], "1")
        assert span["bbox"][2] == pytest.approx(plain[0].rect.width - PAGE_NUMBER_MARGIN, abs=2)
        assert _number_span(plain[1], "2")
    finally:
        plain.close()

    session = Session(tmp_path)
    session.set_page_number_style(True, "#000000", 8, "mincho", "center", "n")
    assert session.view()["pageNumbers"]["pattern"] == "n"
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["pageNumbers"]["pattern"] == "n"


def test_page_label_counts_each_branch():
    assert page_label([2], 0, 0) == (1, 2)
    assert page_label([2], 0, 1) == (2, 2)
    assert page_label([1], 0, 0) is None
    assert page_label([2, 1], 0, 1) == (2, 2)
    assert page_label([2, 1], 1, 0) is None
    assert page_label([2, 3], 1, 0) == (1, 3)
    assert page_label([2, 0, 2], 2, 0) == (1, 2)
    assert page_label([2], 0, 5) is None


def _bottom_ink(jpeg: bytes) -> int:
    pix = fitz.Pixmap(jpeg)
    y0 = int(pix.height * 0.92)
    found = 0
    for y in range(y0, pix.height):
        for x in range(pix.width):
            red, green, blue = pix.pixel(x, y)[:3]
            if red < 180 and green < 180 and blue < 180:
                found += 1
    return found


def test_preview_jpeg_paints_one_page_number(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    source = tmp_path / "a.pdf"
    _pdf(source, ("ONE", "TWO"))
    numbered = render_stamped_page_jpeg(
        [str(source)], "甲第１号証", 1, zoom=1, numbers=_on(), page_number=(2, 2),
    )
    plain = render_stamped_page_jpeg([str(source)], "甲第１号証", 1, zoom=1)
    skipped = render_stamped_page_jpeg(
        [str(source)], "甲第１号証", 0, zoom=1, numbers=_on(), page_number=(1, 1),
    )
    film = render_piece_jpeg(
        [str(source)], 0, 0, 0, zoom=1, numbers=_on(), page_number=(1, 2),
    )
    assert _bottom_ink(numbered) > 8
    assert _bottom_ink(plain) == 0
    assert _bottom_ink(skipped) == 0
    assert _bottom_ink(film) > 8


def test_thumbnails_and_editor_count_each_branch(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    import lexcrew_pdf.stamp as stamp

    painted = []
    real = stamp._paint_page_number

    def spy(page, style, index, total, *, font_path, font):
        painted.append((index, total))
        return real(page, style, index, total, font_path=font_path, font=font)

    monkeypatch.setattr(stamp, "_paint_page_number", spy)
    first = tmp_path / "一.pdf"
    second = tmp_path / "二.pdf"
    alone = tmp_path / "三.pdf"
    _pdf(first, ("ONE", "TWO"))
    _pdf(second, ("THREE",))
    _pdf(alone, ("FOUR",))
    session = Session(tmp_path)
    session.set_page_number_style(True, "#000000", 8, "mincho", "center")
    session.add_file(2, 0, str(alone))
    session.media(2)
    session.preview(2, 0, 0)
    session.piece(2, 0, 0, 0, 0.45, 0, 0)
    assert painted == []

    session.add_branch(1)
    session.add_file(1, 0, str(first))
    session.add_file(1, 1, str(second))
    session.media(1)
    assert painted == [(1, 2)]
    painted.clear()
    session.preview(1, 1, 0)
    session.piece(1, 1, 0, 0, 0.45, 1, 0)
    session.preview(1, 0, 1)
    assert painted == [(2, 2)]
    painted.clear()
    session.set_merge_branches(False)
    session.media(1)
    session.preview(1, 0, 0)
    session.preview(1, 1, 0)
    assert painted == [(1, 2), (1, 2)]
