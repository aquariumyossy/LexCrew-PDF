"""A4縦・縦横比・右上の赤枠。"""
import os
from types import SimpleNamespace

import fitz
import pytest

from lexcrew_pdf.stamp import (
    STAMP_MARGIN_PT,
    PageTrim,
    StampFontMissing,
    StampStyle,
    _draw_stamp,
    _stamp_box,
    describe_source_pages,
    output_mask_from_source,
    page_skew,
    page_trim,
    render_piece_jpeg,
    render_stamped_page_jpeg,
    stamp_frame,
    stamp_sources_to_pdf,
    viewer_rotate,
    yu_gothic_path,
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


def test_a4_landscape_splits_left_then_right_onto_a4(tmp_path):
    _require_font()
    source = tmp_path / "a4wide.pdf"
    document = fitz.open()
    page = document.new_page(width=842, height=595)
    page.insert_text((40, 80), "LEFTSIDE")
    page.insert_text((842 - 160, 80), "RIGHTSIDE")
    document.save(source)
    document.close()
    raw, expanded, splittable = describe_source_pages([str(source)])
    assert (raw, expanded, splittable) == (1, 2, True)

    whole = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第６号証"))
    halves = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第６号証", split=True))
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
    finally:
        whole.close()
        halves.close()


def test_a4_portrait_turned_sideways_splits_the_view_left_then_right(tmp_path):
    _require_font()
    source = tmp_path / "a4tall.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 80), "TOPWORD")
    page.insert_text((72, 780), "BOTTOMWORD")
    document.save(source)
    document.close()
    upright = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第６号証", tilt=90, split=True))
    try:
        assert upright.page_count == 2
        _assert_a4_portrait(upright[0])
        _assert_a4_portrait(upright[1])
        assert "BOTTOMWORD" in upright[0].get_text("text")
        assert "TOPWORD" not in upright[0].get_text("text")
        assert "TOPWORD" in upright[1].get_text("text")
        assert "BOTTOMWORD" not in upright[1].get_text("text")
    finally:
        upright.close()


def test_a4_landscape_turned_upright_is_not_split(tmp_path):
    _require_font()
    source = tmp_path / "a4wide.pdf"
    document = fitz.open()
    page = document.new_page(width=842, height=595)
    page.insert_text((40, 80), "LEFTSIDE")
    page.insert_text((842 - 160, 80), "RIGHTSIDE")
    document.save(source)
    document.close()
    turned = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第６号証", tilt=90, split=True))
    try:
        assert turned.page_count == 1
        text = turned[0].get_text("text")
        assert "LEFTSIDE" in text
        assert "RIGHTSIDE" in text
    finally:
        turned.close()


def test_a3_portrait_is_not_split(tmp_path):
    source = tmp_path / "a3tall.pdf"
    document = fitz.open()
    document.new_page(width=842, height=1191)
    document.save(source)
    document.close()
    raw, expanded, splittable = describe_source_pages([str(source)])
    assert (raw, expanded, splittable) == (1, 1, False)


def test_rotated_a4_portrait_box_splits_the_viewed_spread(tmp_path):
    _require_font()
    source = tmp_path / "rotated-a4.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.set_rotation(90)
    left = fitz.Point(36, 80) * ~page.rotation_matrix
    right = fitz.Point(page.rect.width - 150, 80) * ~page.rotation_matrix
    page.insert_text(left, "LEFTSIDE")
    page.insert_text(right, "RIGHTSIDE")
    document.save(source)
    document.close()
    raw, expanded, splittable = describe_source_pages([str(source)])
    assert (raw, expanded, splittable) == (1, 2, True)

    halves = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第６号証", split=True))
    try:
        assert halves.page_count == 2
        _assert_a4_portrait(halves[0])
        _assert_a4_portrait(halves[1])
        assert "LEFTSIDE" in halves[0].get_text("text")
        assert "RIGHTSIDE" not in halves[0].get_text("text")
        assert "RIGHTSIDE" in halves[1].get_text("text")
        assert "LEFTSIDE" not in halves[1].get_text("text")
    finally:
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


def _write_color_pdf(path):
    document = fitz.open()
    page = document.new_page(width=400, height=400)
    page.insert_text((40, 50), "BODY", fontsize=18, color=(0, 0, 1))
    page.draw_rect(fitz.Rect(40, 80, 140, 180), color=(1, 0, 0), fill=(1, 0, 0), width=0)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), 0)
    pixmap.set_rect(pixmap.irect, (0, 180, 20))
    page.insert_image(fitz.Rect(180, 80, 260, 160), pixmap=pixmap)
    document.save(path)
    document.close()


def _placed_point(page_rect, source_w, source_h, x, y):
    scale = min(page_rect.width / source_w, page_rect.height / source_h)
    origin_x = (page_rect.width - source_w * scale) / 2
    origin_y = (page_rect.height - source_h * scale) / 2
    return origin_x + x * scale, origin_y + y * scale


def _sample(pixmap, x, y):
    px = min(pixmap.width - 1, max(0, int(round(x))))
    py = min(pixmap.height - 1, max(0, int(round(y))))
    index = (py * pixmap.width + px) * pixmap.n
    return tuple(pixmap.samples[index:index + 3])


def _is_gray(pixel):
    red, green, blue = pixel
    return abs(red - green) <= 8 and abs(green - blue) <= 8 and 40 < red < 230


def _has_strong_red(pixmap):
    step = pixmap.width * pixmap.n
    for y in range(pixmap.height):
        row = y * step
        for x in range(pixmap.width):
            index = row + x * pixmap.n
            red, green, blue = pixmap.samples[index], pixmap.samples[index + 1], pixmap.samples[index + 2]
            if red > 180 and green < 80 and blue < 80:
                return True
    return False


def _body_pixel(page):
    paper = fitz.paper_rect("a4")
    x, y = _placed_point(paper, 400, 400, 90, 130)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    return _sample(pixmap, x / paper.width * pixmap.width, y / paper.height * pixmap.height), pixmap


def test_grayscale_keeps_text_image_size_and_the_red_stamp(tmp_path):
    _require_font()
    source = tmp_path / "color.pdf"
    _write_color_pdf(source)
    before = source.read_bytes()
    colored = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証"))
    gray = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証", grayscale=True))
    try:
        assert source.read_bytes() == before
        color_fills = [item.get("fill") for item in colored[0].get_drawings() if item.get("fill")]
        assert any(fill[0] > 0.8 and fill[1] < 0.2 and fill[2] < 0.2 for fill in color_fills)
        page = gray[0]
        assert "BODY" in page.get_text("text")
        assert "甲第１号証" in page.get_text("text")
        assert len(_red_drawings(page)) == 1
        fills = [item.get("fill") for item in page.get_drawings() if item.get("fill")]
        assert fills
        assert all(abs(fill[0] - fill[1]) < 0.05 and abs(fill[1] - fill[2]) < 0.05 for fill in fills)
        image = page.get_images()[0]
        assert image[2] == 40
        assert image[3] == 40
        pixel, _pixmap = _body_pixel(page)
        assert _is_gray(pixel), pixel
    finally:
        colored.close()
        gray.close()


def test_grayscale_jpeg_preview_keeps_a_red_stamp_and_a_gray_body(tmp_path):
    _require_font()
    source = tmp_path / "color.pdf"
    _write_color_pdf(source)
    stamped = fitz.open(stream=render_stamped_page_jpeg(
        [str(source)], "甲第１号証", 0, zoom=1, grayscale=True,
    ), filetype="jpeg")
    piece = fitz.open(stream=render_piece_jpeg(
        [str(source)], 0, 0, 0, zoom=1, grayscale=True,
    ), filetype="jpeg")
    try:
        stamped_pixel, stamped_pixmap = _body_pixel(stamped[0])
        piece_pixel, piece_pixmap = _body_pixel(piece[0])
        assert _is_gray(stamped_pixel), stamped_pixel
        assert _has_strong_red(stamped_pixmap)
        assert _is_gray(piece_pixel), piece_pixel
        assert not _has_strong_red(piece_pixmap)
    finally:
        stamped.close()
        piece.close()


def test_stamp_offset_moves_the_frame_and_stays_on_the_page(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    base = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第２号証"))
    moved = _open_stamped(
        stamp_sources_to_pdf([str(source)], "甲第２号証", stamp_dx=-40, stamp_dy=55)
    )
    shoved = _open_stamped(
        stamp_sources_to_pdf([str(source)], "甲第２号証", stamp_dx=5000, stamp_dy=-5000)
    )
    try:
        base_rect = _red_drawings(base[0])[0]["rect"]
        moved_rect = _red_drawings(moved[0])[0]["rect"]
        assert abs((moved_rect.x0 - base_rect.x0) - (-40)) < 0.2
        assert abs((moved_rect.y0 - base_rect.y0) - 55) < 0.2
        assert "甲第２号証" in moved[0].get_text("text")

        page = shoved[0]
        rect = _red_drawings(page)[0]["rect"]
        assert rect.x0 >= page.rect.x0 - 0.1
        assert rect.y0 >= page.rect.y0 - 0.1
        assert rect.x1 <= page.rect.x1 + 0.1
        assert rect.y1 <= page.rect.y1 + 0.1
        assert abs(rect.x1 - page.rect.x1) < 1.5
        assert abs(rect.y0 - page.rect.y0) < 1.5
        frame = stamp_frame(5000, -5000)
        assert frame["dx"] != 5000
        assert frame["dy"] != -5000
        assert abs(rect.x0 - frame["x"]) < 0.2
        assert abs(rect.y0 - frame["y"]) < 0.2
    finally:
        base.close()
        moved.close()
        shoved.close()


def _word_mask(path, word, *, source=0, page=0):
    document = fitz.open(path)
    try:
        found = [item for item in document[page].get_text("words") if item[4] == word][0]
    finally:
        document.close()
    return SimpleNamespace(
        source=source,
        page=page,
        x=found[0],
        y=found[1],
        w=found[2] - found[0],
        h=found[3] - found[1],
    )


def _write_secret_pdf(path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((72, 100), "SECRET", fontsize=20)
    page.insert_text((72, 220), "VISIBLE", fontsize=20)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), 0)
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(72, 280, 160, 368), pixmap=pixmap)
    document.save(path)
    document.close()


def _pixel_on_output(data, box, dx, dy):
    document = fitz.open(stream=data, filetype="pdf")
    try:
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return _sample(pixmap, (box[0] + dx) * 2, (box[1] + dy) * 2)
    finally:
        document.close()


def test_mask_removes_text_blacks_image_pixels_and_keeps_the_source_file(tmp_path):
    _require_font()
    source = tmp_path / "secret.pdf"
    _write_secret_pdf(source)
    before = source.read_bytes()
    secret = _word_mask(source, "SECRET")
    image = SimpleNamespace(source=0, page=0, x=72, y=280, w=44, h=88)
    data = stamp_sources_to_pdf([str(source)], "甲第１号証", masks=(secret, image))
    assert source.read_bytes() == before
    opened = fitz.open(source)
    try:
        covered = output_mask_from_source(opened[0], 0, 0, image.x, image.y, image.w, image.h)
        spared = output_mask_from_source(opened[0], 0, 0, 120, 280, 40, 88)
    finally:
        opened.close()
    document = _open_stamped(data)
    try:
        text = document[0].get_text("text")
        assert "SECRET" not in text
        assert "VISIBLE" in text
        assert b"SECRET" not in data
        assert "甲第１号証" in text
        assert _pixel_on_output(data, covered, covered[2] / 2, covered[3] / 2) == (0, 0, 0)
        red = _pixel_on_output(data, spared, spared[2] / 2, spared[3] / 2)
        assert red[0] > 200 and red[1] < 40 and red[2] < 40
    finally:
        document.close()


def test_full_page_mask_keeps_the_stamp_and_rotation_still_covers_the_word(tmp_path):
    _require_font()
    source = tmp_path / "secret.pdf"
    _write_secret_pdf(source)
    secret = _word_mask(source, "SECRET")
    turned = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証", tilt=90, masks=(secret,)))
    covered = _open_stamped(stamp_sources_to_pdf(
        [str(source)],
        "甲第１号証",
        masks=(SimpleNamespace(source=0, page=0, x=0, y=0, w=400, h=500),),
    ))
    try:
        assert "SECRET" not in turned[0].get_text("text")
        assert "VISIBLE" in turned[0].get_text("text")
        assert "SECRET" not in covered[0].get_text("text")
        assert "VISIBLE" not in covered[0].get_text("text")
        assert "甲第１号証" in covered[0].get_text("text")
    finally:
        turned.close()
        covered.close()


def test_sideways_a3_stays_one_page_and_the_mask_still_covers_the_word(tmp_path):
    _require_font()
    source = tmp_path / "spread.pdf"
    document = fitz.open()
    page = document.new_page(width=1191, height=842)
    page.insert_text((40, 80), "LEFTSIDE")
    page.insert_text((1191 - 160, 80), "RIGHTSIDE")
    document.save(source)
    document.close()
    left = _word_mask(source, "LEFTSIDE")
    missing = SimpleNamespace(source=0, page=9, x=0, y=0, w=20, h=20)
    turned = _open_stamped(stamp_sources_to_pdf(
        [str(source)],
        "甲第３号証",
        tilt=90,
        split=True,
        masks=(left, missing),
    ))
    try:
        assert turned.page_count == 1
        text = turned[0].get_text("text")
        assert "LEFTSIDE" not in text
        assert "RIGHTSIDE" in text
        assert "甲第３号証" in text
    finally:
        turned.close()


def test_piece_jpeg_burns_the_mask_and_the_editor_preview_does_not(tmp_path):
    _require_font()
    source = tmp_path / "secret.pdf"
    _write_secret_pdf(source)
    image = SimpleNamespace(source=0, page=0, x=72, y=280, w=44, h=88)
    opened = fitz.open(source)
    try:
        box = output_mask_from_source(opened[0], 0, 0, image.x, image.y, image.w, image.h)
    finally:
        opened.close()
    plain = render_piece_jpeg([str(source)], 0, 0, 0, zoom=1)
    burned = render_piece_jpeg([str(source)], 0, 0, 0, zoom=1, masks=(image,))
    preview = render_stamped_page_jpeg([str(source)], "甲第１号証", 0, zoom=1, draw_stamp=False)

    def pixel(data):
        pixmap = fitz.Pixmap(data)
        return _sample(pixmap, box[0] + box[2] / 2, box[1] + box[3] / 2)

    assert pixel(burned) == (0, 0, 0)
    plain_pixel = pixel(plain)
    preview_pixel = pixel(preview)
    assert plain_pixel[0] > 200 and plain_pixel[1] < 40
    assert preview_pixel[0] > 200 and preview_pixel[1] < 40


def _word_box(page, word):
    for item in page.get_text("words"):
        if item[4] == word:
            return item[:4]
    return None


def test_page_trim_rejects_more_than_forty_percent():
    with pytest.raises(ValueError):
        page_trim(401, 0, 0, 0)
    assert page_trim(0, 0, 0, 0) is None
    with pytest.raises(ValueError):
        page_trim(10.0, 0, 0, 0)


def test_trim_drops_the_top_text_and_keeps_the_body_put(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 36), "EDGE")
    page.insert_text((72, 420), "BODY")
    document.save(source)
    document.close()
    plain = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証"))
    trimmed = _open_stamped(stamp_sources_to_pdf(
        [str(source)],
        "甲第１号証",
        trims={(0, 0, 0): PageTrim(top=200)},
    ))
    try:
        assert abs(trimmed[0].rect.width - plain[0].rect.width) < 0.1
        assert abs(trimmed[0].rect.height - 841.89) < 1
        assert "EDGE" in plain[0].get_text("text")
        assert "EDGE" not in trimmed[0].get_text("text")
        assert "BODY" in trimmed[0].get_text("text")
        before = _word_box(plain[0], "BODY")
        after = _word_box(trimmed[0], "BODY")
        assert before is not None and after is not None
        for index in range(4):
            assert abs(after[index] - before[index]) < 1.5
        assert "甲第１号証" in trimmed[0].get_text("text")
    finally:
        plain.close()
        trimmed.close()


def test_trim_top_after_clockwise_quarter_drops_the_source_left(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((12, 420), "LEFT")
    page.insert_text((200, 24), "TOP")
    document.save(source)
    document.close()
    turned = _open_stamped(stamp_sources_to_pdf(
        [str(source)],
        "甲第１号証",
        tilt=90,
        trims={(0, 0, 0): PageTrim(top=250)},
    ))
    try:
        text = turned[0].get_text("text")
        assert "LEFT" not in text
        assert "TOP" in text
    finally:
        turned.close()


def test_trim_follows_the_source_page_when_output_order_flips(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    first = document.new_page(width=595, height=842)
    first.insert_text((72, 36), "EDGE")
    first.insert_text((72, 420), "BODY")
    second = document.new_page(width=595, height=842)
    second.insert_text((72, 420), "NEXT")
    document.save(source)
    document.close()
    flipped = _open_stamped(stamp_sources_to_pdf(
        [str(source)],
        "甲第１号証",
        pages=[(0, 1, 0), (0, 0, 0)],
        trims={(0, 0, 0): PageTrim(top=200)},
    ))
    try:
        assert "NEXT" in flipped[0].get_text("text")
        assert "EDGE" not in flipped[0].get_text("text")
        assert "BODY" in flipped[1].get_text("text")
        assert "EDGE" not in flipped[1].get_text("text")
        assert "甲第１号証" in flipped[0].get_text("text")
        assert "甲第１号証" not in flipped[1].get_text("text")
    finally:
        flipped.close()


def test_piece_and_stamped_jpeg_drop_the_same_top_bar(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 40), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    page.draw_rect(fitz.Rect(250, 400, 290, 440), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    document.save(source)
    document.close()
    trims = {(0, 0, 0): PageTrim(top=200)}
    full = fitz.open(stream=render_piece_jpeg([str(source)], 0, 0, 0, zoom=1), filetype="jpeg")
    piece = fitz.open(stream=render_piece_jpeg([str(source)], 0, 0, 0, zoom=1, trims=trims), filetype="jpeg")
    stamped = fitz.open(stream=render_stamped_page_jpeg(
        [str(source)], "甲第１号証", 0, zoom=1, trims=trims,
    ), filetype="jpeg")
    try:
        full_box = _dark_bbox(full[0])
        piece_box = _dark_bbox(piece[0])
        stamped_box = _dark_bbox(stamped[0])
        assert full_box[1] < 20
        assert piece_box[1] > 150
        assert piece_box[2] < full_box[2] - 50
        assert abs(piece_box[1] - stamped_box[1]) < 4
        assert abs(piece_box[2] - stamped_box[2]) < 4
        assert abs(piece_box[3] - full_box[3]) < 4
    finally:
        full.close()
        piece.close()
        stamped.close()


def test_trim_keeps_a_mask_on_the_body_and_leaves_the_cut_band_white(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 36), "EDGE")
    page.insert_text((72, 420), "BODY")
    document.save(source)
    document.close()
    data = stamp_sources_to_pdf(
        [str(source)],
        "甲第１号証",
        trims={(0, 0, 0): PageTrim(top=200)},
        masks=(_word_mask(source, "EDGE"), _word_mask(source, "BODY")),
    )
    opened = _open_stamped(data)
    try:
        text = opened[0].get_text("text")
        assert "EDGE" not in text
        assert "BODY" not in text
        pixmap = opened[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        pixel = _sample(pixmap, 200, 8)
        assert pixel[0] > 240 and pixel[1] > 240 and pixel[2] > 240
    finally:
        opened.close()


def test_page_skew_is_tenths_of_a_degree():
    assert page_skew(0) is None
    assert page_skew(15) == 15
    assert page_skew(-100) == -100
    with pytest.raises(ValueError):
        page_skew(101)
    with pytest.raises(ValueError):
        page_skew(True)


def test_clockwise_skew_keeps_vector_text_and_leaves_the_stamp(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((260, 48), "TOPMARK")
    page.insert_text((260, 420), "BODY")
    document.save(source)
    document.close()
    plain = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証"))
    turned = _open_stamped(
        stamp_sources_to_pdf([str(source)], "甲第１号証", skews={(0, 0): 50})
    )
    try:
        assert turned[0].get_images() == []
        assert "TOPMARK" in turned[0].get_text("text")
        assert "BODY" in turned[0].get_text("text")
        before = _word_box(plain[0], "TOPMARK")
        after = _word_box(turned[0], "TOPMARK")
        assert before is not None and after is not None
        assert after[0] > before[0] + 2
        plain_stamp = _red_drawings(plain[0])[0]["rect"]
        turned_stamp = _red_drawings(turned[0])[0]["rect"]
        for index in range(4):
            assert abs(plain_stamp[index] - turned_stamp[index]) < 1.5
    finally:
        plain.close()
        turned.close()


def _write_scanned_page(path):
    """全面を1枚の画像にする。上の帯と本文の印は同じ部品になる。"""
    drawn = fitz.open()
    page = drawn.new_page(width=595, height=842)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1), width=0)
    page.draw_rect(fitz.Rect(0, 0, 595, 28), color=None, fill=(0, 0, 0), width=0)
    page.draw_rect(fitz.Rect(250, 400, 310, 450), color=None, fill=(0, 0, 0), width=0)
    pixmap = page.get_pixmap(alpha=False)
    document = fitz.open()
    image = document.new_page(width=595, height=842)
    image.insert_image(image.rect, pixmap=pixmap)
    document.save(path)
    document.close()
    drawn.close()


def _dark_in_rows(page, y0, y1):
    """赤い印を除き、指定した行範囲の暗い画素の数と外接を返す。"""
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    width, height, channels = pixmap.width, pixmap.height, pixmap.n
    samples = pixmap.samples
    start = max(0, int(y0))
    stop = min(height, int(y1))
    count = 0
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(start, stop):
        row = y * width * channels
        for x in range(width):
            index = row + x * channels
            red, green, blue = samples[index], samples[index + 1], samples[index + 2]
            if red > 180 and green < 80 and blue < 80:
                continue
            if max(red, green, blue) > 80:
                continue
            count += 1
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    box = None if count == 0 else (min_x, min_y, max_x, max_y)
    return count, box


def test_skew_trim_cuts_a_full_page_image_without_moving_the_body(tmp_path):
    _require_font()
    source = tmp_path / "scan.pdf"
    _write_scanned_page(source)
    for tenths, top in ((30, 100), (30, 400), (100, 100), (100, 400)):
        plain = _open_stamped(
            stamp_sources_to_pdf([str(source)], "甲第１号証", skews={(0, 0): tenths})
        )
        cropped = _open_stamped(
            stamp_sources_to_pdf(
                [str(source)],
                "甲第１号証",
                skews={(0, 0): tenths},
                trims={(0, 0, 0): PageTrim(top=top)},
            )
        )
        try:
            cut = plain[0].rect.height * top / 1000
            leaked, _box = _dark_in_rows(cropped[0], 0, cut - 2)
            before_count, before_box = _dark_in_rows(plain[0], 0, cut - 2)
            _below, body_before = _dark_in_rows(plain[0], 300, plain[0].rect.height)
            _kept, body_after = _dark_in_rows(cropped[0], 300, cropped[0].rect.height)
            assert before_count > 0
            assert leaked == 0
            assert body_before is not None and body_after is not None
            for index in range(4):
                assert abs(body_after[index] - body_before[index]) <= 1
        finally:
            plain.close()
            cropped.close()
    jpeg = fitz.open(
        stream=render_piece_jpeg(
            [str(source)],
            0,
            0,
            0,
            zoom=1,
            trims={(0, 0, 0): PageTrim(top=100)},
            skews={(0, 0): 100},
        ),
        filetype="jpeg",
    )
    try:
        cut = jpeg[0].rect.height * 100 / 1000
        leaked, _box = _dark_in_rows(jpeg[0], 0, cut - 2)
        assert leaked == 0
    finally:
        jpeg.close()


def test_skew_trim_cuts_the_output_top_without_rescaling_the_body(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 36), "EDGE")
    page.insert_text((72, 420), "BODY")
    document.save(source)
    document.close()
    skewed = _open_stamped(
        stamp_sources_to_pdf([str(source)], "甲第１号証", skews={(0, 0): 30})
    )
    cropped = _open_stamped(
        stamp_sources_to_pdf(
            [str(source)],
            "甲第１号証",
            skews={(0, 0): 30},
            trims={(0, 0, 0): PageTrim(top=200)},
        )
    )
    try:
        assert "EDGE" in skewed[0].get_text("text")
        assert "EDGE" not in cropped[0].get_text("text")
        assert "BODY" in cropped[0].get_text("text")
        before = _word_box(skewed[0], "BODY")
        after = _word_box(cropped[0], "BODY")
        assert before is not None and after is not None
        for index in range(4):
            assert abs(after[index] - before[index]) < 1.5
        assert abs(cropped[0].rect.width - skewed[0].rect.width) < 0.1
        assert abs(cropped[0].rect.height - skewed[0].rect.height) < 0.1
    finally:
        skewed.close()
        cropped.close()


def test_skew_keeps_a_mask_on_the_word(tmp_path):
    _require_font()
    source = tmp_path / "secret.pdf"
    _write_secret_pdf(source)
    secret = _word_mask(source, "SECRET")
    data = stamp_sources_to_pdf([str(source)], "甲第１号証", masks=(secret,), skews={(0, 0): 50})
    document = _open_stamped(data)
    try:
        text = document[0].get_text("text")
        assert "SECRET" not in text
        assert "VISIBLE" in text
        assert "甲第１号証" in text
    finally:
        document.close()


def test_bare_preview_omits_the_red_frame(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    stamped = render_stamped_page_jpeg([str(source)], "甲第１号証", 0, zoom=1)
    bare = render_stamped_page_jpeg([str(source)], "甲第１号証", 0, zoom=1, draw_stamp=False)
    assert stamped != bare
    document = fitz.open(stream=bare, filetype="jpeg")
    try:
        assert _red_drawings(document[0]) == []
    finally:
        document.close()


def _blue(color) -> bool:
    return bool(color) and len(color) >= 3 and color[2] > 0.8 and color[0] < 0.2 and color[1] < 0.2


def test_chosen_stamp_is_blue_18pt_gothic(tmp_path):
    _require_font()
    if not os.path.isfile(yu_gothic_path()):
        pytest.skip("游ゴシックがありません")
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    style = StampStyle((0, 0, 1), 18, "gothic")
    document = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証", style=style))
    try:
        page = document[0]
        drawings = [item for item in page.get_drawings() if _blue(item.get("color"))]
        assert len(drawings) == 1
        assert drawings[0].get("fill") in (None, ())
        span = _stamp_span(page, "甲第１号証")
        assert span["size"] == 18
        assert span["color"] == 255
        assert any("Gothic" in font[3] for font in page.get_fonts())
        assert abs(drawings[0]["rect"].x1 - (page.rect.width - STAMP_MARGIN_PT)) < 1.5
    finally:
        document.close()


def test_grayscale_keeps_the_chosen_blue_stamp(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _write_pdf(source, width=595, height=842, text="BODY")
    style = StampStyle((0, 0, 1), 11, "mincho")
    document = _open_stamped(stamp_sources_to_pdf([str(source)], "甲第１号証", grayscale=True, style=style))
    try:
        page = document[0]
        assert any(_blue(item.get("color")) for item in page.get_drawings())
        assert _stamp_span(page, "甲第１号証")["color"] == 255
    finally:
        document.close()
