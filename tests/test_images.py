"""JPG と PNG を、PDF と同じカードの経路に乗せる。"""
import os
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import FILE_DIALOG_TYPES, require_source_file
from lexcrew_pdf.plan import jobs_from_layout
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import inspect_source_pages, open_source, stamp_sources_to_pdf, yu_mincho_path
from webview.util import parse_file_type


def _jpeg(path: Path, width: int, height: int, color=(220, 30, 30), *, dpi=96, orientation=1, mark=False) -> None:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, color)
    pix.set_dpi(dpi, dpi)
    if mark:
        for y in range(min(8, height)):
            for x in range(min(8, width)):
                pix.set_pixel(x, y, (0, 220, 0))
    raw = pix.tobytes("jpeg")
    if orientation != 1:
        payload = b"Exif\x00\x00" + bytes([
            0x49, 0x49, 0x2A, 0x00,
            0x08, 0x00, 0x00, 0x00,
            0x01, 0x00,
            0x12, 0x01, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, orientation, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
        ])
        length = len(payload) + 2
        raw = raw[:2] + b"\xff\xe1" + length.to_bytes(2, "big") + payload + raw[2:]
    path.write_bytes(raw)


def _png(path: Path, width: int, height: int, color=(20, 40, 200)) -> None:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, color)
    pix.set_dpi(96, 96)
    path.write_bytes(pix.tobytes("png"))


def _pdf(path: Path, texts=("PAGE",)) -> None:
    document = fitz.open()
    for text in texts:
        page = document.new_page(width=595, height=842)
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


def _image_box(page) -> fitz.Rect:
    info = page.get_image_info()
    assert info
    return fitz.Rect(info[0]["bbox"])


def test_file_dialog_accepts_pdf_jpg_and_png():
    description, extensions = parse_file_type(FILE_DIALOG_TYPES[0])
    assert "PDF" in description
    assert "画像" in description
    for suffix in ("*.pdf", "*.jpg", "*.jpeg", "*.png"):
        assert suffix in extensions


def test_unsupported_formats_have_a_japanese_message(tmp_path):
    heic = tmp_path / "写真.heic"
    heif = tmp_path / "写真.heif"
    gif = tmp_path / "memo.gif"
    missing = tmp_path / "無い.jpg"
    heic.write_bytes(b"heic")
    heif.write_bytes(b"heif")
    gif.write_bytes(b"gif")
    for path in (heic, heif):
        with pytest.raises(ValueError, match="HEICには対応していません"):
            require_source_file(path)
    with pytest.raises(ValueError, match="対応していない形式です。PDF、JPG、PNGを選んでください。"):
        require_source_file(gif)
    with pytest.raises(ValueError, match="ファイルが見つかりません"):
        require_source_file(missing)
    broken = tmp_path / "壊れ.jpg"
    broken.write_bytes(b"not a jpeg")
    with pytest.raises(ValueError, match="画像を開けません"):
        open_source(str(broken))


def test_small_image_is_centered_on_a4_without_upscaling(tmp_path):
    path = tmp_path / "小さい.jpg"
    _jpeg(path, 80, 40, dpi=96)
    document = open_source(str(path))
    try:
        page = document[0]
        assert page.rect.height > page.rect.width
        assert abs(page.rect.width - 595) < 1
        assert abs(page.rect.height - 842) < 1
        box = _image_box(page)
        # 80 x 40 px を 96 dpi のまま。1px を 1pt より大きくしない。
        assert box.width == pytest.approx(60, abs=0.6)
        assert box.height == pytest.approx(30, abs=0.6)
        assert box.width < page.rect.width / 2
        assert abs((box.x0 + box.x1) / 2 - page.rect.width / 2) < 1
        assert abs((box.y0 + box.y1) / 2 - page.rect.height / 2) < 1
        image = page.get_images(full=True)[0]
        assert image[2] == 80
        assert image[3] == 40
    finally:
        document.close()


def test_large_landscape_image_scales_down_to_a4(tmp_path):
    path = tmp_path / "広い.jpg"
    _jpeg(path, 1600, 800, dpi=72)
    document = open_source(str(path))
    try:
        page = document[0]
        box = _image_box(page)
        assert page.rect.height > page.rect.width
        assert box.width == pytest.approx(page.rect.width, abs=1)
        assert box.height == pytest.approx(297.5, abs=1.5)
        assert box.width < 1600
        image = page.get_images(full=True)[0]
        assert (image[2], image[3]) == (1600, 800)
        _raw, _expanded, splittable, refs, _spreads = inspect_source_pages([str(path)], split=True)
        assert splittable is False
        assert refs == [(0, 0, 0)]
    finally:
        document.close()


def test_exif_orientation_turns_a_wide_jpeg_upright(tmp_path):
    path = tmp_path / "回転.jpg"
    _jpeg(path, 120, 40, dpi=96, orientation=6, mark=True)
    document = open_source(str(path))
    try:
        page = document[0]
        assert page.rect.height > page.rect.width
        box = _image_box(page)
        assert box.height == pytest.approx(90, abs=0.8)
        assert box.width == pytest.approx(30, abs=0.8)
        assert box.height > box.width
        pixmap = page.get_pixmap(alpha=False)
        top_left = pixmap.pixel(int(box.x0) + 1, int(box.y0) + 1)
        top_right = pixmap.pixel(int(box.x1) - 2, int(box.y0) + 1)
        # 右へ 90 度。左上の緑は、表示の右上へ移る。
        assert top_right[1] > 180
        assert top_left[0] > 180
        image = page.get_images(full=True)[0]
        assert (image[2], image[3]) == (120, 40)
    finally:
        document.close()


def test_a4_landscape_image_stays_a_sheet_that_can_be_split(tmp_path):
    path = tmp_path / "見開き.jpg"
    _jpeg(path, 842, 595, dpi=72)
    document = open_source(str(path))
    try:
        page = document[0]
        assert page.rect.width > page.rect.height
        assert abs(page.rect.width - 842) < 1
        assert abs(page.rect.height - 595) < 1
        box = _image_box(page)
        assert box.width == pytest.approx(page.rect.width, abs=1.5)
        assert box.height == pytest.approx(page.rect.height, abs=1.5)
    finally:
        document.close()
    _raw, expanded, splittable, refs, _spreads = inspect_source_pages([str(path)], split=True)
    assert splittable is True
    assert expanded == 2
    assert refs == [(0, 0, 1), (0, 0, 2)]


def test_png_becomes_one_portrait_page(tmp_path):
    path = tmp_path / "縦.png"
    _png(path, 40, 100)
    document = open_source(str(path))
    try:
        page = document[0]
        assert page.rect.height > page.rect.width
        box = _image_box(page)
        assert box.height > box.width
        assert box.height == pytest.approx(75, abs=0.8)
        assert box.width < page.rect.width / 2
    finally:
        document.close()


def test_dropped_images_stay_in_order_with_pdfs(tmp_path):
    first = tmp_path / "あ.jpg"
    second = tmp_path / "い.png"
    third = tmp_path / "う.jpeg"
    pdf = tmp_path / "え.pdf"
    _jpeg(first, 30, 40, color=(200, 0, 0))
    _png(second, 30, 40)
    _jpeg(third, 30, 40, color=(0, 180, 0))
    _pdf(pdf, ("ONE", "TWO"))
    session = Session(tmp_path)
    session.drop_files(1, 0, None, [str(first), str(pdf), str(second)])
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["あ.jpg", "え.pdf", "い.png"]
    _raw, _expanded, _splittable, refs, _spreads = inspect_source_pages(
        [str(tmp_path / name) for name in names],
        split=False,
    )
    assert refs == [(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 0, 0)]

    session.drop_files(1, 0, 0, [str(third)])
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["う.jpeg", "え.pdf", "い.png"]
    session.drop_files(1, 0, None, [str(first), str(second)], replace=True)
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["あ.jpg", "い.png"]
    assert session.layout.cards[0].pages is None


def test_unsupported_drop_does_not_change_the_card(tmp_path):
    pdf = tmp_path / "契約.pdf"
    image = tmp_path / "写真.jpg"
    heic = tmp_path / "写真.heic"
    _pdf(pdf)
    _jpeg(image, 20, 20)
    heic.write_bytes(b"heic")
    session = Session(tmp_path)
    session.add_file(1, 0, str(pdf))
    with pytest.raises(ValueError, match="HEICには対応していません"):
        session.drop_files(1, 0, None, [str(image), str(heic)])
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["契約.pdf"]


def test_image_filename_drops_an_exhibit_number(tmp_path):
    source = tmp_path / "甲1 売買契約書.jpg"
    _jpeg(source, 40, 60)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001 売買契約書.pdf"
    branched = tmp_path / "乙3の1 納品書.png"
    _png(branched, 40, 60)
    session.add_branch(1)
    session.add_file(1, 1, str(branched))
    assert session.view()["cards"][0]["slots"][1]["title"] == ""
    assert jobs_from_layout(session.layout, tmp_path).jobs[0].filename == "甲001-1~2 売買契約書.pdf"


def test_image_can_be_rotated_masked_and_stamped(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    source = tmp_path / "写真.jpg"
    _jpeg(source, 200, 120, color=(220, 20, 20), dpi=72)
    opened = open_source(str(source))
    try:
        box = _image_box(opened[0])
    finally:
        opened.close()
    from lexcrew_pdf.layout import Mask

    mask = Mask(
        source=0,
        page=0,
        x=box.x0,
        y=box.y0,
        w=box.width,
        h=box.height,
    )
    plain = fitz.open(stream=stamp_sources_to_pdf([str(source)], "甲第１号証"), filetype="pdf")
    covered = fitz.open(stream=stamp_sources_to_pdf([str(source)], "甲第１号証", masks=(mask,)), filetype="pdf")
    turned = fitz.open(stream=stamp_sources_to_pdf([str(source)], "甲第１号証", tilt=90), filetype="pdf")
    try:
        assert plain.page_count == 1
        assert "甲第１号証" in plain[0].get_text()
        center = plain[0].get_pixmap(alpha=False).pixel(297, 421)
        assert center[0] > 150 and center[1] < 80
        masked = covered[0].get_pixmap(alpha=False).pixel(297, 421)
        assert max(masked) < 40
        assert "甲第１号証" in covered[0].get_text()
        assert turned.page_count == 1
        assert "甲第１号証" in turned[0].get_text()
    finally:
        plain.close()
        covered.close()
        turned.close()

    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.rotate(1)
    session.set_page_number_style(True, "#000000", 8, "mincho", "center")
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("甲001 *.pdf"))
    assert len(written) == 1
    output = fitz.open(written[0])
    try:
        assert output.page_count == 1
        assert "1 / 1" not in output[0].get_text().replace("\xa0", " ")
        assert "甲第１号証" in output[0].get_text()
    finally:
        output.close()
