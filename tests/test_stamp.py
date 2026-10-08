"""A4縦・縦横比・右上の赤枠。"""
import os

import fitz
import pytest

from lexcrew_pdf.stamp import (
    STAMP_MARGIN_PT,
    StampFontMissing,
    _draw_stamp,
    _stamp_box,
    describe_source_pages,
    render_piece_jpeg,
    render_stamped_page_jpeg,
    stamp_sources_to_pdf,
    viewer_rotate,
    yu_mincho_path,
)


def _write_pdf(path, *, width, height, text="", square=None, rotation=0):
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    if text:
        page.insert_text((72, 80), text)
    if square is not None:
        page.draw_rect(square, color=(0, 0, 0), fill=(0, 0, 0), width=0)
    if rotation:
        page.set_rotation(rotation)
    document.save(path)
    document.close()


def _open_stamped(data):
    return fitz.open(stream=data, filetype="pdf")


def _require_font():
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")


def _red_drawings(page):
    found = []
    for drawing in page.get_drawings():
        color = drawing.get("color")
        if not color or len(color) < 3:
            continue
        if color[0] > 0.8 and color[1] < 0.2 and color[2] < 0.2:
            found.append(drawing)
    return found


def _dark_bbox(page):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    width, height, channels = pixmap.width, pixmap.height, pixmap.n
    samples = pixmap.samples
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        row = y * width * channels
        for x in range(width):
            index = row + x * channels
            red, green, blue = samples[index], samples[index + 1], samples[index + 2]
            if red > 180 and green < 80 and blue < 80:
                continue
            if red > 230 and green > 230 and blue > 230:
                continue
            if max(red, green, blue) > 80:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    return min_x, min_y, max_x, max_y


def test_missing_font_refuses_to_stamp(monkeypatch, tmp_path):
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    monkeypatch.setattr(
        "lexcrew_pdf.stamp.yu_mincho_path",
        lambda: str(tmp_path / "missing.ttf"),
    )
    with pytest.raises(StampFontMissing):
        stamp_sources_to_pdf([str(source)], "甲第１号証")


def test_portrait_pages_are_a4_and_only_the_first_page_has_the_red_label(tmp_path):
    _require_font()
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _write_pdf(first, width=595, height=842, text="BODY")
    _write_pdf(second, width=595, height=842, text="NEXT")
    data = stamp_sources_to_pdf([str(first), str(second)], "甲第１号証")
    document = _open_stamped(data)
    try:
        assert document.page_count == 2
        for index, marker in enumerate(("BODY", "NEXT")):
            page = document[index]
            assert abs(page.rect.width - 595.27) < 1
            assert abs(page.rect.height - 841.89) < 1
            assert page.rotation == 0
            assert page.rect.width < page.rect.height
            text = page.get_text("text")
            assert marker in text
            drawings = _red_drawings(page)
            if index == 0:
                assert "甲第１号証" in text
                assert len(drawings) == 1
                assert drawings[0].get("fill") in (None, ())
                rect = drawings[0]["rect"]
                assert abs(rect.y0 - STAMP_MARGIN_PT) < 1.5
                assert abs(rect.x1 - (page.rect.width - STAMP_MARGIN_PT)) < 1.5
            else:
                assert "甲第１号証" not in text
                assert drawings == []
    finally:
        document.close()


def _stamp_span(page, label):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if label in span["text"]:
                    return span
    raise AssertionError(label)


def test_stamp_label_sits_in_the_vertical_center_of_the_frame(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    document = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第２号証"))
    try:
        page = document[0]
        rect = _red_drawings(page)[0]["rect"]
        bbox = _stamp_span(page, "甲第２号証")["bbox"]
        assert abs((bbox[1] + bbox[3]) / 2 - (rect.y0 + rect.y1) / 2) < 0.6
        assert abs((bbox[0] + bbox[2]) / 2 - (rect.x0 + rect.x1) / 2) < 1.0
    finally:
        document.close()


def test_landscape_page_stays_proportional_on_portrait_a4(tmp_path):
    _require_font()
    source = tmp_path / "land.pdf"
    _write_pdf(
        source,
        width=842,
        height=595,
        square=fitz.Rect(360, 230, 480, 350),
    )
    data = stamp_sources_to_pdf([str(source)], "甲第２号証")
    document = _open_stamped(data)
    try:
        page = document[0]
        assert abs(page.rect.width - 595.27) < 1
        assert abs(page.rect.height - 841.89) < 1
        assert "甲第２号証" in page.get_text("text")
        min_x, min_y, max_x, max_y = _dark_bbox(page)
        assert max_x > min_x and max_y > min_y
        ratio = (max_x - min_x + 1) / (max_y - min_y + 1)
        assert 0.85 <= ratio <= 1.15
    finally:
        document.close()


def _dominant_edge(page):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
    width, height, channels = pixmap.width, pixmap.height, pixmap.n
    samples = pixmap.samples
    band = max(8, int(min(width, height) * 0.18))
    counts = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    for y in range(height):
        row = y * width * channels
        for x in range(width):
            index = row + x * channels
            red, green, blue = samples[index], samples[index + 1], samples[index + 2]
            if red > 140 and red > green + 40 and red > blue + 40:
                continue
            if red > 40 or green > 40 or blue > 40:
                continue
            if y < band:
                counts["top"] += 1
            if y >= height - band:
                counts["bottom"] += 1
            if x < band:
                counts["left"] += 1
            if x >= width - band:
                counts["right"] += 1
    winner = max(counts, key=counts.get)
    assert counts[winner] > 20, counts
    others = [value for name, value in counts.items() if name != winner]
    assert counts[winner] > max(others) * 1.5, counts
    return winner


def test_viewer_rotate_turns_clockwise():
    assert viewer_rotate(0) == 0
    assert viewer_rotate(90) == 270
    assert viewer_rotate(180) == 180
    assert viewer_rotate(270) == 90
    with pytest.raises(ValueError):
        viewer_rotate(45)


def test_rotated_landscape_stays_upright_and_tilt_turns_clockwise(tmp_path):
    _require_font()
    source = tmp_path / "scan.pdf"
    _write_pdf(
        source,
        width=842,
        height=595,
        square=fitz.Rect(0, 0, 842, 36),
        rotation=90,
    )
    native = fitz.open(source)
    try:
        viewed = _dominant_edge(native[0])
    finally:
        native.close()
    upright = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証"))
    try:
        page = upright[0]
        assert page.rotation == 0
        assert page.rect.width < page.rect.height
        assert _dominant_edge(page) == viewed
    finally:
        upright.close()


def test_tilt_turns_clockwise_and_leaves_the_stamp_upright(tmp_path):
    _require_font()
    source = tmp_path / "upright.pdf"
    _write_pdf(source, width=595, height=842, square=fitz.Rect(0, 0, 595, 36))
    upright = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証"))
    turned = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証", tilt=90))
    try:
        assert _dominant_edge(upright[0]) == "top"
        assert _dominant_edge(turned[0]) == "right"
        drawings = _red_drawings(turned[0])
        assert len(drawings) == 1
        rect = drawings[0]["rect"]
        assert abs(rect.y0 - STAMP_MARGIN_PT) < 1.5
        assert abs(rect.x1 - (turned[0].rect.width - STAMP_MARGIN_PT)) < 1.5
        assert turned[0].rotation == 0
    finally:
        upright.close()
        turned.close()


def test_portrait_page_rotated_to_landscape_keeps_the_viewer_orientation(tmp_path):
    _require_font()
    source = tmp_path / "spread.pdf"
    _write_pdf(
        source,
        width=595,
        height=842,
        square=fitz.Rect(0, 0, 595, 28),
        rotation=90,
    )
    native = fitz.open(source)
    try:
        viewed = _dominant_edge(native[0])
    finally:
        native.close()
    document = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第３号証"))
    try:
        page = document[0]
        assert page.rotation == 0
        assert page.rect.width < page.rect.height
        assert _dominant_edge(page) == viewed
        min_x, min_y, max_x, max_y = _dark_bbox(page)
        assert min_y > page.rect.height * 0.08
        assert max_y < page.rect.height * 0.92
        assert max_x > min_x
        drawings = _red_drawings(page)
        rect = drawings[0]["rect"]
        assert abs(rect.y0 - STAMP_MARGIN_PT) < 1.5
        assert abs(rect.x1 - (page.rect.width - STAMP_MARGIN_PT)) < 1.5
    finally:
        document.close()


def test_unrotated_landscape_stays_letterboxed(tmp_path):
    _require_font()
    source = tmp_path / "wide.pdf"
    _write_pdf(source, width=842, height=595, square=fitz.Rect(0, 0, 842, 36))
    document = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第２号証"))
    try:
        page = document[0]
        min_x, min_y, max_x, max_y = _dark_bbox(page)
        assert (max_x - min_x) > (max_y - min_y) * 3
        assert min_y > page.rect.height * 0.12
    finally:
        document.close()


def test_rotated_source_is_placed_on_an_unrotated_a4_page(tmp_path):
    _require_font()
    source = tmp_path / "turned.pdf"
    _write_pdf(source, width=595, height=842, text="ROTATEDMARK", rotation=90)
    data = stamp_sources_to_pdf([str(source)], "甲第３号証の１")
    document = _open_stamped(data)
    try:
        page = document[0]
        assert page.rotation == 0
        assert abs(page.rect.width - 595.27) < 1
        assert page.rect.width < page.rect.height
        text = page.get_text("text")
        assert "甲第３号証の１" in text
        assert "ROTATEDMARK" in text
    finally:
        document.close()


def _assert_a4_portrait(page):
    assert page.rotation == 0
    assert abs(page.rect.width - 595.27) < 1
    assert page.rect.width < page.rect.height


def _corner_has_dark(data: bytes, kind: str) -> bool:
    document = fitz.open(stream=data, filetype=kind)
    try:
        pix = document[0].get_pixmap()
        found = 0
        x0 = int(pix.width * 0.72)
        y0 = int(pix.height * 0.03)
        y1 = max(int(pix.height * 0.12), y0 + 1)
        for y in range(y0, y1):
            for x in range(x0, pix.width):
                red, green, blue = pix.pixel(x, y)[:3]
                if red < 40 and green < 40 and blue < 40:
                    found += 1
                    if found > 6:
                        return True
        return False
    finally:
        document.close()


def test_later_pages_keep_the_corner_image_and_gain_no_new_stamp(tmp_path):
    _require_font()
    source = tmp_path / "baked.pdf"
    font = yu_mincho_path()
    ink = fitz.Rect(470, 32, 484, 48)
    document = fitz.open()
    for marker in ("ONE", "TWO"):
        page = document.new_page(width=595, height=842)
        page.insert_font(fontname="bodyMincho", fontfile=font)
        page.insert_text((72, 200), marker)
        page.insert_text((72, 240), "甲第３号証", fontname="bodyMincho", fontsize=11)
        page.draw_rect(ink, color=(0, 0, 0), fill=(0, 0, 0), width=0)
    box_w, box_h = _stamp_box(font)
    _draw_stamp(document[1], "甲第３号証", font, box_w, box_h)
    document.save(source)
    document.close()

    stamped = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第９号証"))
    try:
        first, second = stamped[0], stamped[1]
        assert "ONE" in first.get_text("text")
        assert "甲第９号証" in first.get_text("text")
        assert _corner_has_dark(first.get_pixmap().tobytes("png"), "png")
        second_text = second.get_text("text")
        assert "TWO" in second_text
        assert "甲第９号証" not in second_text
        assert second_text.count("甲第３号証") == 2
        assert _corner_has_dark(second.get_pixmap().tobytes("png"), "png")
    finally:
        stamped.close()

    later = render_stamped_page_jpeg([str(source)], "甲第９号証", 1, zoom=1)
    thumb = render_piece_jpeg([str(source)], 0, 1, 0, zoom=1)
    assert _corner_has_dark(later, "jpeg")
    assert _corner_has_dark(thumb, "jpeg")


def test_a4_page_is_not_split(tmp_path):
    source = tmp_path / "a4.pdf"
    _write_pdf(source, width=595, height=842, text="A4BODY")
    raw, expanded, splittable = describe_source_pages([str(source)])
    assert (raw, expanded, splittable) == (1, 1, False)


def test_a3_landscape_splits_left_then_right_onto_a4(tmp_path):
    _require_font()
    source = tmp_path / "spread.pdf"
    document = fitz.open()
    page = document.new_page(width=1191, height=842)
    page.insert_text((40, 80), "LEFTSIDE")
    page.insert_text((1191 - 160, 80), "RIGHTSIDE")
    document.save(source)
    document.close()
    raw, expanded, splittable = describe_source_pages([str(source)])
    assert (raw, expanded, splittable) == (1, 2, True)

    whole = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第３号証"))
    halves = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第３号証", split=True))
    try:
        assert whole.page_count == 1
        assert halves.page_count == 2
        _assert_a4_portrait(halves[0])
        _assert_a4_portrait(halves[1])
        left = halves[0].get_text("text")
        right = halves[1].get_text("text")
        assert "LEFTSIDE" in left
        assert "RIGHTSIDE" not in left
        assert "RIGHTSIDE" in right
        assert "LEFTSIDE" not in right
        assert "甲第３号証" in left
        assert "甲第３号証" not in right
        assert _red_drawings(halves[1]) == []
    finally:
        whole.close()
        halves.close()


def test_rotated_a3_portrait_splits_the_viewed_spread(tmp_path):
    _require_font()
    source = tmp_path / "guarantee.pdf"
    document = fitz.open()
    page = document.new_page(width=842, height=1191)
    page.set_rotation(90)
    left = fitz.Point(36, 90) * ~page.rotation_matrix
    right = fitz.Point(page.rect.width - 150, 90) * ~page.rotation_matrix
    page.insert_text(left, "LEFTSIDE")
    page.insert_text(right, "RIGHTSIDE")
    document.save(source)
    document.close()

    halves = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第３号証", split=True))
    try:
        assert halves.page_count == 2
        assert "LEFTSIDE" in halves[0].get_text("text")
        assert "RIGHTSIDE" not in halves[0].get_text("text")
        assert "RIGHTSIDE" in halves[1].get_text("text")
        assert "LEFTSIDE" not in halves[1].get_text("text")
    finally:
        halves.close()
