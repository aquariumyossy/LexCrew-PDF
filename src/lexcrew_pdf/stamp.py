"""原本PDFをA4縦へ収め、右上へ赤い証拠番号の枠を入れる。"""
from __future__ import annotations

import os
from pathlib import Path

import fitz

STAMP_FONT_SIZE = 11
STAMP_SAMPLE = "甲第１１号証の２"
STAMP_MARGIN_PT = 10 * 72 / 25.4
STAMP_PAD_X = 6
STAMP_BOX_HEIGHT = 22
STAMP_COLOR = (1, 0, 0)
_FONT_NAME = "kouStamp"


class StampFontMissing(FileNotFoundError):
    """游明朝が無いときは、埋め込まれない代替フォントへ落とさない。"""


def yu_mincho_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Fonts", "yumin.ttf")


def require_yu_mincho() -> str:
    path = yu_mincho_path()
    if not os.path.isfile(path):
        raise StampFontMissing(
            "游明朝（yumin.ttf）が見つからないため、証拠PDFを生成できません。"
        )
    return path


def open_source(path: str):
    """原本はメモリへ読んでから開く。ファイルを掴んだままだと、同じPDFを再度選べない。"""
    data = Path(path).read_bytes()
    document = fitz.open(stream=data, filetype="pdf")
    document._lex_bytes = data
    return document


def count_pdf_pages(paths: tuple[str, ...] | list[str]) -> int:
    total = 0
    for path in paths:
        document = open_source(path)
        try:
            total += document.page_count
        finally:
            document.close()
    return total


# A3 は 297mm × 420mm。短い辺が A4 の長い辺、長い辺が A4 の短い辺の2枚分。
_A3_SHORT_PT = 841.89
_A3_LONG_PT = 1190.55
_A3_TOLERANCE = 0.15


def viewer_rotate(tilt_clockwise: int = 0) -> int:
    """右回りチルトを show_pdf_page の角度にする。正の rotate は反時計回り。"""
    tilt = int(tilt_clockwise or 0) % 360
    if tilt not in (0, 90, 180, 270):
        raise ValueError("回転は90度単位です。")
    return (-tilt) % 360


def a3_split_axis(rect) -> str | None:
    """閲覧時の用紙が A3 なら、分ける方向を返す。A4 はそのまま。"""
    width = float(rect.width)
    height = float(rect.height)
    long_side = max(width, height)
    short_side = min(width, height)
    if abs(long_side - _A3_LONG_PT) > _A3_LONG_PT * _A3_TOLERANCE:
        return None
    if abs(short_side - _A3_SHORT_PT) > _A3_SHORT_PT * _A3_TOLERANCE:
        return None
    if width >= height:
        return "horizontal"
    return "vertical"


def a4_clips(rect, *, split: bool) -> list[fitz.Rect | None]:
    """分割するときは左→右、または上→下。A4 のページは切らない。"""
    if not split:
        return [None]
    axis = a3_split_axis(rect)
    if axis == "horizontal":
        mid = (rect.x0 + rect.x1) / 2
        return [
            fitz.Rect(rect.x0, rect.y0, mid, rect.y1),
            fitz.Rect(mid, rect.y0, rect.x1, rect.y1),
        ]
    if axis == "vertical":
        mid = (rect.y0 + rect.y1) / 2
        return [
            fitz.Rect(rect.x0, rect.y0, rect.x1, mid),
            fitz.Rect(rect.x0, mid, rect.x1, rect.y1),
        ]
    return [None]


def describe_source_pages(paths: tuple[str, ...] | list[str]) -> tuple[int, int, bool]:
    """原本のページ数、A4分割したときのページ数、A3が1枚でもあるか。"""
    raw, expanded, splittable, _refs = inspect_source_pages(paths, split=False)
    return raw, expanded, splittable


def inspect_source_pages(
    paths: tuple[str, ...] | list[str],
    *,
    split: bool,
) -> tuple[int, int, bool, list[tuple[int, int, int]]]:
    """原本を開き、分割の有無に合わせた (原本, ページ, 部分) の並びを返す。"""
    raw = 0
    expanded = 0
    splittable = False
    refs: list[tuple[int, int, int]] = []
    for source_index, path in enumerate(paths):
        document = open_source(path)
        try:
            for page_index in range(document.page_count):
                page = document[page_index]
                _bake_display_rotation(page)
                pieces = a4_clips(page.rect, split=True)
                raw += 1
                if len(pieces) > 1:
                    splittable = True
                expanded += len(pieces)
                if split and len(pieces) > 1:
                    refs.append((source_index, page_index, 1))
                    refs.append((source_index, page_index, 2))
                else:
                    refs.append((source_index, page_index, 0))
        finally:
            document.close()
    return raw, expanded, splittable, refs


class _PageFound(Exception):
    """プレビューで目的のページを載せたあと、残りの原本を開かない。"""


def stamp_sources_to_pdf(
    source_paths: list[str] | tuple[str, ...],
    label: str,
    *,
    tilt: int = 0,
    split: bool = False,
    pages: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...] | None = None,
) -> bytes:
    """原本を順にA4縦へ載せる。証拠番号は出力の1ページ目だけに押す。

    2ページ目以降は印を足さず、画像にも手を加えない。
    pages を渡したときは、その (原本, ページ, 部分) だけをその順で出す。
    """
    if not source_paths:
        raise ValueError("原本がありません。")
    font_path = require_yu_mincho()
    box_w, box_h = _stamp_box(font_path)
    output = fitz.open()
    try:
        placed = 0

        def place(source, index: int, clip) -> None:
            nonlocal placed
            page = _place_page(output, source, index, tilt, clip)
            if placed == 0:
                _draw_stamp(page, label, font_path, box_w, box_h)
            placed += 1

        _for_each_placement(source_paths, split, pages, place)
        if placed <= 0:
            raise ValueError("ページがありません。")
        return output.tobytes()
    finally:
        output.close()


def render_stamped_page_jpeg(
    source_paths: list[str] | tuple[str, ...],
    label: str,
    page_index: int,
    *,
    zoom: float,
    tilt: int = 0,
    split: bool = False,
    pages: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...] | None = None,
) -> bytes:
    """指定ページだけを印字してJPEGにする。甲号証フォルダへは書かない。"""
    if page_index < 0:
        raise IndexError("ページがありません。")
    font_path = require_yu_mincho()
    box_w, box_h = _stamp_box(font_path)
    output = fitz.open()
    try:
        seen = 0

        def place(source, index: int, clip) -> None:
            nonlocal seen
            if seen != page_index:
                seen += 1
                return
            page = _place_page(output, source, index, tilt, clip)
            if page_index == 0:
                _draw_stamp(page, label, font_path, box_w, box_h)
            raise _PageFound

        try:
            _for_each_placement(source_paths, split, pages, place)
        except _PageFound:
            pass
        else:
            raise IndexError("ページがありません。")
        pixmap = output[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("jpeg")
    finally:
        output.close()


def render_piece_jpeg(
    source_paths: list[str] | tuple[str, ...],
    source_index: int,
    page_index: int,
    part: int,
    *,
    zoom: float,
    tilt: int = 0,
) -> bytes:
    """編集用に1枚だけ載せる。証拠番号は最終の位置で決まるので、ここには押さない。"""
    if source_index < 0 or source_index >= len(source_paths):
        raise IndexError("ページがありません。")
    output = fitz.open()
    source = open_source(source_paths[source_index])
    try:
        if page_index < 0 or page_index >= source.page_count:
            raise IndexError("ページがありません。")
        _bake_display_rotation(source[page_index])
        clip = _clip_for_part(source[page_index].rect, part)
        _place_page(output, source, page_index, tilt, clip)
        pixmap = output[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("jpeg")
    finally:
        source.close()
        output.close()


def _for_each_placement(source_paths, split: bool, pages, visitor) -> None:
    if pages is None:
        for path in source_paths:
            source = open_source(path)
            try:
                if source.page_count <= 0:
                    raise ValueError("ページがありません。")
                for index in range(source.page_count):
                    _bake_display_rotation(source[index])
                    for clip in a4_clips(source[index].rect, split=split):
                        visitor(source, index, clip)
            finally:
                source.close()
        return
    opened: dict[int, fitz.Document] = {}
    try:
        for source_index, page_index, part in pages:
            source_index = int(source_index)
            page_index = int(page_index)
            part = int(part)
            if source_index < 0 or source_index >= len(source_paths):
                raise ValueError("原本のページが見つかりません。")
            source = opened.get(source_index)
            if source is None:
                source = open_source(source_paths[source_index])
                opened[source_index] = source
            if page_index < 0 or page_index >= source.page_count:
                raise ValueError("原本のページが見つかりません。")
            _bake_display_rotation(source[page_index])
            visitor(source, page_index, _clip_for_part(source[page_index].rect, part))
    finally:
        for source in opened.values():
            source.close()


def _clip_for_part(rect, part: int):
    if int(part) == 0:
        return None
    clips = a4_clips(rect, split=True)
    if len(clips) < 2:
        return None
    if int(part) == 1:
        return clips[0]
    return clips[1]


def _place_page(output, source, index: int, tilt: int, clip: fitz.Rect | None = None):
    _bake_display_rotation(source[index])
    page = output.new_page(width=_a4().width, height=_a4().height)
    page.show_pdf_page(
        page.rect,
        source,
        index,
        clip=clip,
        keep_proportion=True,
        rotate=viewer_rotate(tilt),
    )
    return page


def _bake_display_rotation(page) -> None:
    """閲覧時の向きを内容に焼き、/Rotate を 0 にする。原本ファイルは保存しない。

    show_pdf_page は回転ページの transformation_matrix から回転を落とす。
    縦長の用紙に /Rotate 90 が付いた横長の見開きは、角度を足すだけでは
    閲覧時の向きに戻らない。
    """
    if int(page.rotation or 0) % 360:
        page.remove_rotation()


def _a4() -> fitz.Rect:
    return fitz.paper_rect("a4")


def _stamp_box(font_path: str) -> tuple[float, float]:
    font = fitz.Font(fontfile=font_path)
    width = font.text_length(STAMP_SAMPLE, fontsize=STAMP_FONT_SIZE)
    return width + STAMP_PAD_X * 2, STAMP_BOX_HEIGHT


def _draw_stamp(page, label: str, font_path: str, box_w: float, box_h: float) -> None:
    right = page.rect.x1 - STAMP_MARGIN_PT
    top = page.rect.y0 + STAMP_MARGIN_PT
    rect = fitz.Rect(right - box_w, top, right, top + box_h)
    page.draw_rect(rect, color=STAMP_COLOR, width=1.0)
    page.insert_font(fontname=_FONT_NAME, fontfile=font_path)
    font = fitz.Font(fontfile=font_path)
    ascender = font.ascender * STAMP_FONT_SIZE
    descender = font.descender * STAMP_FONT_SIZE
    text_height = ascender - descender
    baseline = rect.y0 + (rect.height - text_height) / 2 + ascender
    text_width = font.text_length(label, fontsize=STAMP_FONT_SIZE)
    page.insert_text(
        fitz.Point(rect.x0 + (rect.width - text_width) / 2, baseline),
        label,
        fontname=_FONT_NAME,
        fontsize=STAMP_FONT_SIZE,
        color=STAMP_COLOR,
    )
