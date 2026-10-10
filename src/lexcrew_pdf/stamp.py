"""原本PDFをA4縦へ収め、右上へ証拠番号の枠を入れる。"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import fitz

STAMP_FONT_SIZE = 11
STAMP_SIZE_MIN = 8
STAMP_SIZE_MAX = 24
STAMP_SAMPLE = "甲第１１号証の２"
STAMP_MARGIN_PT = 10 * 72 / 25.4
STAMP_PAD_X = 6
STAMP_BOX_HEIGHT = 22
STAMP_COLOR = (1, 0, 0)
STAMP_FONTS = ("mincho", "gothic")
# 画面の色ボタンと同じ4色。これ以外の色は印にしない。
STAMP_PALETTE = (
    ("赤", "#ff0000", (1.0, 0.0, 0.0)),
    ("青", "#0000ff", (0.0, 0.0, 1.0)),
    ("緑", "#008000", (0.0, 128 / 255, 0.0)),
    ("黒", "#000000", (0.0, 0.0, 0.0)),
)
_STAMP_COLOR_BY_HEX = {hex_color: rgb for _label, hex_color, rgb in STAMP_PALETTE}
# 各辺は載せた画像の 40% まで。向かい合っても中に 20% 残る。
MAX_EDGE_PERMILLE = 400
# 右回り。十分の一度。カードの90度とは別に、見ている向きの面内だけ回す。
SKEW_TENTH_LIMIT = 100
_FONT_NAME = "kouStamp"


@dataclass(frozen=True)
class PageTrim:
    """用紙へ載せた画像の四辺。千分率。上は出力ページの上。"""

    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0

    def is_zero(self) -> bool:
        return not (self.top or self.right or self.bottom or self.left)


def page_trim(top: int, right: int, bottom: int, left: int) -> PageTrim | None:
    """四辺を千分率で受ける。すべて 0 なら保存しない印として None。"""
    values = (top, right, bottom, left)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("端の削りは0から40%です。")
    if any(value < 0 or value > MAX_EDGE_PERMILLE for value in values):
        raise ValueError("端の削りは0から40%です。")
    if all(value == 0 for value in values):
        return None
    return PageTrim(*values)


def trim_lookup(rows) -> dict[tuple[int, int, int], PageTrim]:
    """配置の行を、(原本, ページ, 部分) から四辺への辞書にする。"""
    found: dict[tuple[int, int, int], PageTrim] = {}
    for row in rows or ():
        parsed = page_trim(row.top, row.right, row.bottom, row.left)
        if parsed is None:
            continue
        found[(int(row.source), int(row.page), int(row.part))] = parsed
    return found


def page_skew(tenths: int) -> int | None:
    """右回りの十分の一度。0 は保存しない印として None。"""
    if isinstance(tenths, bool) or not isinstance(tenths, int):
        raise ValueError("傾きは-10度から10度です。")
    if tenths < -SKEW_TENTH_LIMIT or tenths > SKEW_TENTH_LIMIT:
        raise ValueError("傾きは-10度から10度です。")
    if tenths == 0:
        return None
    return tenths


def skew_ccw_degrees(tenths: int) -> float:
    """右回りの十分の一度を、show_pdf_page の反時計回りにする。"""
    return -(int(tenths) / 10.0)


def skew_lookup(rows) -> dict[tuple[int, int], int]:
    """配置の行を、(原本, ページ) から右回りの十分の一度への辞書にする。"""
    found: dict[tuple[int, int], int] = {}
    for row in rows or ():
        parsed = page_skew(row.tenths)
        if parsed is None:
            continue
        found[(int(row.source), int(row.page))] = parsed
    return found


class StampFontMissing(FileNotFoundError):
    """指定した印のフォントが無いときは、埋め込まれない代替へ落とさない。"""


@dataclass(frozen=True)
class StampFace:
    css_family: str
    missing_generate: str
    missing_place: str


@dataclass(frozen=True)
class StampStyle:
    """案件全体の印。色は赤、青、緑、黒。フォントは明朝かゴシック。"""

    color: tuple[float, float, float]
    size: int
    font: str

    def __post_init__(self) -> None:
        if self.color not in _STAMP_COLOR_BY_HEX.values():
            raise ValueError("色は赤、青、緑、黒から選んでください。")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or not STAMP_SIZE_MIN <= self.size <= STAMP_SIZE_MAX:
            raise ValueError("大きさは8から24です。")
        if self.font not in STAMP_FONTS:
            raise ValueError("フォントは明朝かゴシックです。")


DEFAULT_STAMP = StampStyle(STAMP_COLOR, STAMP_FONT_SIZE, "mincho")

_STAMP_FACE = {
    "mincho": StampFace(
        css_family='"Yu Mincho", "YuMincho", "游明朝", serif',
        missing_generate="游明朝（yumin.ttf）が見つからないため、証拠PDFを生成できません。",
        missing_place="游明朝（yumin.ttf）が見つからないため、証拠番号の位置を決められません。",
    ),
    "gothic": StampFace(
        css_family='"Yu Gothic Medium", "Yu Gothic", "游ゴシック", sans-serif',
        missing_generate="游ゴシック（YuGothM.ttc）が見つからないため、このフォントは使えません。",
        missing_place="游ゴシック（YuGothM.ttc）が見つからないため、証拠番号の位置を決められません。",
    ),
}


def yu_mincho_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Fonts", "yumin.ttf")


def yu_gothic_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Fonts", "YuGothM.ttc")


def _stamp_font_path(font: str) -> str:
    if font == "gothic":
        return yu_gothic_path()
    return yu_mincho_path()


def require_yu_mincho() -> str:
    return require_stamp_font(DEFAULT_STAMP)


def require_stamp_font(style: StampStyle | None = None, *, placing: bool = False) -> str:
    chosen = style or DEFAULT_STAMP
    path = _stamp_font_path(chosen.font)
    if os.path.isfile(path):
        return path
    face = _STAMP_FACE[chosen.font]
    message = face.missing_place if placing else face.missing_generate
    raise StampFontMissing(message)


def color_hex(color: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in color)


def stamp_style_from_json(raw) -> StampStyle:
    """配置ファイルの stamp。無い項目は初期値。壊れていれば配置全体を拒む。"""
    if raw is None:
        return DEFAULT_STAMP
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        color = _hex_color(raw["color"]) if "color" in raw else DEFAULT_STAMP.color
        size = _stamp_size(raw["size"]) if "size" in raw else DEFAULT_STAMP.size
        font = _stamp_font(raw["font"]) if "font" in raw else DEFAULT_STAMP.font
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    return StampStyle(color, size, font)


def stamp_style_from_request(color, size, font) -> StampStyle:
    return StampStyle(_hex_color(color), _stamp_size(size), _stamp_font(font))


def stamp_record(style: StampStyle) -> dict | None:
    if style == DEFAULT_STAMP:
        return None
    return {"color": color_hex(style.color), "size": style.size, "font": style.font}


def stamp_view(style: StampStyle) -> dict:
    return {"color": color_hex(style.color), "size": style.size, "font": style.font}


def _hex_color(value) -> tuple[float, float, float]:
    if not isinstance(value, str):
        raise ValueError("色は赤、青、緑、黒から選んでください。")
    color = _STAMP_COLOR_BY_HEX.get(value.strip().lower())
    if color is None:
        raise ValueError("色は赤、青、緑、黒から選んでください。")
    return color


def _stamp_size(value) -> int:
    if isinstance(value, bool):
        raise ValueError("大きさは8から24です。")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and STAMP_SIZE_MIN <= value <= STAMP_SIZE_MAX:
        return value
    raise ValueError("大きさは8から24です。")


def _stamp_font(value) -> str:
    if value not in STAMP_FONTS:
        raise ValueError("フォントは明朝かゴシックです。")
    return value


def _chosen_style(style: StampStyle | None) -> StampStyle:
    return style or DEFAULT_STAMP


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


# A3 は 297mm × 420mm。A4 は 210mm × 297mm。
# 見えている画像が、このどちらかの横長のときだけ左右に割る。
_A3_SHORT_PT = 841.89
_A3_LONG_PT = 1190.55
_A4_SHORT_PT = 595.28
_A4_LONG_PT = 841.89
_A3_TOLERANCE = 0.15


def viewer_rotate(tilt_clockwise: int = 0) -> int:
    """右回りチルトを show_pdf_page の角度にする。正の rotate は反時計回り。"""
    tilt = int(tilt_clockwise or 0) % 360
    if tilt not in (0, 90, 180, 270):
        raise ValueError("回転は90度単位です。")
    return (-tilt) % 360


def _near_side(side: float, target: float) -> bool:
    return abs(side - target) <= target * _A3_TOLERANCE


def _viewed_size(rect, tilt: int) -> tuple[float, float]:
    """右回りの90度単位を足した、見えている幅と高さ。"""
    width = float(rect.width)
    height = float(rect.height)
    if int(tilt or 0) % 360 in (90, 270):
        return height, width
    return width, height


def _landscape_sheet(width: float, height: float) -> bool:
    """横長の A3 か A4 か。縦の画像は割らない。"""
    if width < height:
        return False
    long_side, short_side = width, height
    a3 = _near_side(long_side, _A3_LONG_PT) and _near_side(short_side, _A3_SHORT_PT)
    a4 = _near_side(long_side, _A4_LONG_PT) and _near_side(short_side, _A4_SHORT_PT)
    return a3 or a4


def _viewed_halves(rect, tilt: int) -> list[fitz.Rect] | None:
    """見ている左半分、右半分を、原本の矩形で返す。

    右へ90度では、見ている左が原本の下、右が原本の上になる。
    """
    turn = int(tilt or 0) % 360
    width, height = _viewed_size(rect, turn)
    if not _landscape_sheet(width, height):
        return None
    if turn in (0, 180):
        mid = (rect.x0 + rect.x1) / 2
        left = fitz.Rect(rect.x0, rect.y0, mid, rect.y1)
        right = fitz.Rect(mid, rect.y0, rect.x1, rect.y1)
        if turn == 180:
            return [right, left]
        return [left, right]
    mid = (rect.y0 + rect.y1) / 2
    top = fitz.Rect(rect.x0, rect.y0, rect.x1, mid)
    bottom = fitz.Rect(rect.x0, mid, rect.x1, rect.y1)
    if turn == 90:
        return [bottom, top]
    return [top, bottom]


def a4_clips(rect, *, split: bool, tilt: int = 0) -> list[fitz.Rect | None]:
    """見えている横長の A3 か A4 を、左から右へ切る。それ以外は切らない。"""
    if not split:
        return [None]
    halves = _viewed_halves(rect, tilt)
    if halves is None:
        return [None]
    return halves


def describe_source_pages(paths: tuple[str, ...] | list[str]) -> tuple[int, int, bool]:
    """原本のページ数、分割したときのページ数、分割できるページが1枚でもあるか。"""
    raw, expanded, splittable, _refs, _spreads = inspect_source_pages(paths, split=False)
    return raw, expanded, splittable


def inspect_source_pages(
    paths: tuple[str, ...] | list[str],
    *,
    split: bool,
    tilts: list[int] | tuple[int, ...] | None = None,
) -> tuple[int, int, bool, list[tuple[int, int, int]], tuple[bool, ...]]:
    """原本を開き、分割の有無に合わせた (原本, ページ, 部分) の並びを返す。

    tilts は原本ごとの右回り角度。見えている画像が横長の A3 か A4 のページだけ割る。
    戻り値の最後は、原本ごとに分割できるページがあるか。
    """
    raw = 0
    expanded = 0
    splittable = False
    refs: list[tuple[int, int, int]] = []
    spreads: list[bool] = []
    for source_index, path in enumerate(paths):
        tilt = 0 if tilts is None or source_index >= len(tilts) else int(tilts[source_index] or 0)
        document = open_source(path)
        file_spread = False
        try:
            for page_index in range(document.page_count):
                page = document[page_index]
                _bake_display_rotation(page)
                pieces = a4_clips(page.rect, split=True, tilt=tilt)
                raw += 1
                if len(pieces) > 1:
                    splittable = True
                    file_spread = True
                expanded += len(pieces)
                if split and len(pieces) > 1:
                    refs.append((source_index, page_index, 1))
                    refs.append((source_index, page_index, 2))
                else:
                    refs.append((source_index, page_index, 0))
        finally:
            document.close()
        spreads.append(file_spread)
    return raw, expanded, splittable, refs, tuple(spreads)


class _PageFound(Exception):
    """プレビューで目的のページを載せたあと、残りの原本を開かない。"""


def stamp_sources_to_pdf(
    source_paths: list[str] | tuple[str, ...],
    label: str,
    *,
    tilt: int = 0,
    split: bool = False,
    pages: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...] | None = None,
    grayscale: bool = False,
    stamp_dx: int = 0,
    stamp_dy: int = 0,
    masks=(),
    trims: dict[tuple[int, int, int], PageTrim] | None = None,
    skews: dict[tuple[int, int], int] | None = None,
    style: StampStyle | None = None,
    parts=None,
) -> bytes:
    """原本を順にA4縦へ載せる。証拠番号は出力の1ページ目だけに押す。

    2ページ目以降には印を足さない。
    pages を渡したときは、その (原本, ページ, 部分) だけをその順で出す。
    parts を渡したときは、枝番ごとにその並びを続け、各枝番の先頭ページだけにその印を押す。
    枝番ごとの回転と印の位置は、その part の rotation、stamp_dx、stamp_dy を使う。
    grayscale のときは、載せたページをグレーにしてから印を押す。
    stamp_dx と stamp_dy は、右上の既定位置からの点。正は右と下。
    masks は原本ページ上の矩形。載せたあとに墨消し、そのあとで印を押す。
    trims は (原本, ページ, 部分) ごとの四辺。端はクリップで落とし、中身は拡大しない。
    skews は (原本, ページ) ごとの右回り十分の一度。分割した左右は同じ角度。印は回さない。
    style を省いたときは赤、11 ポイント、明朝。
    """
    if not source_paths:
        raise ValueError("原本がありません。")
    chosen = _chosen_style(style)
    font_path = require_stamp_font(chosen)
    box_w, box_h = _stamp_box(font_path, chosen)
    output = fitz.open()
    try:
        placed = 0

        def place_run(run_label: str, run_tilt: int, run_pages, run_dx: int, run_dy: int) -> None:
            nonlocal placed
            start = placed

            def place(source, source_index: int, index: int, clip, piece: int) -> None:
                nonlocal placed
                skew_tenths = _skew_for(skews, source_index, index)
                page, limit = _place_page(
                    output, source, index, run_tilt, clip, grayscale=grayscale,
                    trim=_trim_for(trims, source_index, index, piece),
                    skew_tenths=skew_tenths,
                )
                _redact_masks(
                    page, source[index], source_index, index, clip, run_tilt, masks,
                    limit=limit, skew_tenths=skew_tenths,
                )
                if placed == start:
                    _draw_stamp(page, run_label, font_path, box_w, box_h, run_dx, run_dy, chosen)
                placed += 1

            _for_each_placement(source_paths, split, run_pages, place, run_tilt)

        if parts:
            for run in parts:
                place_run(run.stamp, int(run.rotation), run.pages, int(run.stamp_dx), int(run.stamp_dy))
        else:
            place_run(label, tilt, pages, stamp_dx, stamp_dy)
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
    grayscale: bool = False,
    stamp_dx: int = 0,
    stamp_dy: int = 0,
    draw_stamp: bool = True,
    masks=(),
    trims: dict[tuple[int, int, int], PageTrim] | None = None,
    skews: dict[tuple[int, int], int] | None = None,
    style: StampStyle | None = None,
) -> bytes:
    """指定ページだけを印字してJPEGにする。甲号証フォルダへは書かない。"""
    if page_index < 0:
        raise IndexError("ページがありません。")
    chosen = _chosen_style(style)
    font_path = require_stamp_font(chosen)
    box_w, box_h = _stamp_box(font_path, chosen)
    output = fitz.open()
    try:
        seen = 0

        def place(source, source_index: int, index: int, clip, part: int) -> None:
            nonlocal seen
            if seen != page_index:
                seen += 1
                return
            skew_tenths = _skew_for(skews, source_index, index)
            page, limit = _place_page(
                output, source, index, tilt, clip, grayscale=grayscale,
                trim=_trim_for(trims, source_index, index, part),
                skew_tenths=skew_tenths,
            )
            _redact_masks(
                page, source[index], source_index, index, clip, tilt, masks,
                limit=limit, skew_tenths=skew_tenths,
            )
            if page_index == 0 and draw_stamp:
                _draw_stamp(page, label, font_path, box_w, box_h, stamp_dx, stamp_dy, chosen)
            raise _PageFound

        try:
            _for_each_placement(source_paths, split, pages, place, tilt)
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
    grayscale: bool = False,
    masks=(),
    trims: dict[tuple[int, int, int], PageTrim] | None = None,
    skews: dict[tuple[int, int], int] | None = None,
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
        clip = _clip_for_part(source[page_index].rect, part, tilt)
        skew_tenths = _skew_for(skews, source_index, page_index)
        page, limit = _place_page(
            output, source, page_index, tilt, clip, grayscale=grayscale,
            trim=_trim_for(trims, source_index, page_index, part),
            skew_tenths=skew_tenths,
        )
        _redact_masks(
            page, source[page_index], source_index, page_index, clip, tilt, masks,
            limit=limit, skew_tenths=skew_tenths,
        )
        pixmap = output[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("jpeg")
    finally:
        source.close()
        output.close()


def _for_each_placement(source_paths, split: bool, pages, visitor, tilt: int = 0) -> None:
    if pages is None:
        for source_index, path in enumerate(source_paths):
            source = open_source(path)
            try:
                if source.page_count <= 0:
                    raise ValueError("ページがありません。")
                for index in range(source.page_count):
                    _bake_display_rotation(source[index])
                    for part, clip in _indexed_clips(source[index].rect, split=split, tilt=tilt):
                        visitor(source, source_index, index, clip, part)
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
            visitor(
                source,
                source_index,
                page_index,
                _clip_for_part(source[page_index].rect, part, tilt),
                part,
            )
    finally:
        for source in opened.values():
            source.close()


def _indexed_clips(rect, *, split: bool, tilt: int = 0) -> list[tuple[int, fitz.Rect | None]]:
    clips = a4_clips(rect, split=split, tilt=tilt)
    if split and len(clips) > 1:
        return [(1, clips[0]), (2, clips[1])]
    return [(0, clips[0])]


def _clip_for_part(rect, part: int, tilt: int = 0):
    if int(part) == 0:
        return None
    clips = a4_clips(rect, split=True, tilt=tilt)
    if len(clips) < 2:
        return None
    if int(part) == 1:
        return clips[0]
    return clips[1]


def source_mask_from_output(
    source_page,
    part: int,
    tilt: int,
    output_rect,
    skew_tenths: int = 0,
) -> tuple[float, float, float, float] | None:
    """出力A4の矩形を、表示回転を焼いた原本ページの矩形にする。余白だけなら None。"""
    _bake_display_rotation(source_page)
    clip = _clip_for_part(source_page.rect, part, tilt)
    dest = fitz.open()
    try:
        page = dest.new_page(width=_a4().width, height=_a4().height)
        rotate, target = _mask_placement(page, source_page, clip, tilt, skew_tenths)
        mapped = _unmap_rect(
            fitz.Rect(output_rect) & page.rect,
            source_page,
            page,
            clip,
            rotate,
            target=target,
        )
    finally:
        dest.close()
    if mapped is None:
        return None
    limited = mapped & _shown_source_rect(source_page, clip)
    return _stored_rect(limited)


def output_mask_from_source(
    source_page,
    part: int,
    tilt: int,
    x: float,
    y: float,
    w: float,
    h: float,
    skew_tenths: int = 0,
):
    """原本ページの矩形を、今の回転と分割で出力A4へ投影する。その面に出ないときは None。"""
    _bake_display_rotation(source_page)
    clip = _clip_for_part(source_page.rect, part, tilt)
    dest = fitz.open()
    try:
        page = dest.new_page(width=_a4().width, height=_a4().height)
        rotate, target = _mask_placement(page, source_page, clip, tilt, skew_tenths)
        mapped = _map_stored_rect(source_page, page, clip, rotate, x, y, w, h, target=target)
    finally:
        dest.close()
    if mapped is None:
        return None
    return (round(mapped.x0, 2), round(mapped.y0, 2), round(mapped.width, 2), round(mapped.height, 2))


def _redact_masks(
    page,
    source_page,
    source_index: int,
    page_index: int,
    clip,
    tilt: int,
    masks,
    limit=None,
    skew_tenths: int = 0,
) -> None:
    rotate, target = _mask_placement(page, source_page, clip, tilt, skew_tenths)
    rects = []
    for mask in masks or ():
        if not hasattr(mask, "source") or not hasattr(mask, "page"):
            continue
        if int(mask.source) != int(source_index) or int(mask.page) != int(page_index):
            continue
        mapped = _map_stored_rect(
            source_page,
            page,
            clip,
            rotate,
            float(mask.x),
            float(mask.y),
            float(mask.w),
            float(mask.h),
            target=target,
        )
        if mapped is None:
            continue
        # 写像はトリム前の載せ方。削った帯は白紙のままにする。
        if limit is not None:
            mapped = mapped & limit
            if mapped.is_empty or mapped.width < 0.2 or mapped.height < 0.2:
                continue
        rects.append(mapped)
    if not rects:
        return
    for rect in rects:
        page.add_redact_annot(rect, fill=(0, 0, 0))
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_PIXELS,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )


def _shown_source_rect(source_page, clip):
    if clip is None:
        return fitz.Rect(source_page.rect)
    return fitz.Rect(source_page.rect) & fitz.Rect(clip)


def _mask_placement(dest_page, source_page, clip, tilt: int, skew_tenths: int):
    """墨消しを、載せたページと同じ回転と枠へ合わせる。

    傾きが無いときは、今までどおり用紙全体を枠にする。
    傾きがあるときは、90度だけで決めた画像枠へ小さい角度を足す。
    """
    card = viewer_rotate(tilt)
    if not int(skew_tenths or 0):
        return card, None
    full = source_page.rect if clip is None else fitz.Rect(clip)
    fitted = fitted_image_rect(dest_page.rect, full, card)
    return card + skew_ccw_degrees(int(skew_tenths)), fitted


def _fit_matrix(source_page, dest_page, clip, rotate: float, target=None) -> fitz.Matrix:
    # show_pdf_page の calc_matrix と同じ順。画面の枠と生成PDFが同じ範囲を覆う。
    shown = _shown_source_rect(source_page, clip)
    box = dest_page.rect if target is None else fitz.Rect(target)
    pdf_target = box * ~dest_page.transformation_matrix
    source = shown * ~source_page.transformation_matrix
    return _calc_matrix(source, pdf_target, rotate)


def _calc_matrix(source, target, rotate: float) -> fitz.Matrix:
    source_mid = (source.tl + source.br) / 2.0
    target_mid = (target.tl + target.br) / 2.0
    matrix = fitz.Matrix(1, 0, 0, 1, -source_mid.x, -source_mid.y) * fitz.Matrix(rotate)
    fitted = source * matrix
    scale = min(target.width / fitted.width, target.height / fitted.height)
    matrix *= fitz.Matrix(scale, scale)
    matrix *= fitz.Matrix(1, 0, 0, 1, target_mid.x, target_mid.y)
    return matrix


def _map_stored_rect(source_page, dest_page, clip, rotate: float, x: float, y: float, w: float, h: float, target=None):
    shown = _shown_source_rect(source_page, clip)
    if shown.is_empty:
        return None
    stored = fitz.Rect(x, y, x + w, y + h) & shown
    if stored.is_empty or stored.width < 0.2 or stored.height < 0.2:
        return None
    matrix = _fit_matrix(source_page, dest_page, clip, rotate, target=target)
    mapped = (stored * ~source_page.transformation_matrix) * matrix
    visual = mapped * dest_page.transformation_matrix
    visual &= dest_page.rect
    if visual.is_empty:
        return None
    return visual


def _unmap_rect(output_rect, source_page, dest_page, clip, rotate: float, target=None):
    shown = _shown_source_rect(source_page, clip)
    if shown.is_empty or output_rect.is_empty:
        return None
    matrix = _fit_matrix(source_page, dest_page, clip, rotate, target=target)
    pdf_out = fitz.Rect(output_rect) * ~dest_page.transformation_matrix
    back = (pdf_out * ~matrix) * source_page.transformation_matrix
    return back


def _stored_rect(rect) -> tuple[float, float, float, float] | None:
    if rect is None or rect.is_empty:
        return None
    x0 = round(float(rect.x0), 2)
    y0 = round(float(rect.y0), 2)
    x1 = round(float(rect.x1), 2)
    y1 = round(float(rect.y1), 2)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, round(x1 - x0, 2), round(y1 - y0, 2)


def _place_page(
    output,
    source,
    index: int,
    tilt: int,
    clip: fitz.Rect | None = None,
    *,
    grayscale: bool = False,
    trim: PageTrim | None = None,
    skew_tenths: int = 0,
):
    _bake_display_rotation(source[index])
    if int(skew_tenths or 0):
        page, limit = _place_skewed_page(output, source, index, tilt, clip, trim, int(skew_tenths))
    else:
        page = output.new_page(width=_a4().width, height=_a4().height)
        limit = None
        if trim is None or trim.is_zero():
            page.show_pdf_page(
                page.rect,
                source,
                index,
                clip=clip,
                keep_proportion=True,
                rotate=viewer_rotate(tilt),
            )
        else:
            full = source[index].rect if clip is None else fitz.Rect(clip)
            rotate = viewer_rotate(tilt)
            fitted = fitted_image_rect(page.rect, full, rotate)
            dest, placed = trimmed_placement(full, fitted, trim, rotate)
            limit = dest
            page.show_pdf_page(
                dest,
                source,
                index,
                clip=placed,
                keep_proportion=True,
                rotate=rotate,
            )
    if grayscale:
        # 印はこのあと選んだ色で描く。ここでグレーにしても印はグレーにしない。
        page.recolor(1)
    return page, limit


def _place_skewed_page(output, source, index: int, tilt: int, clip, trim: PageTrim | None, skew_tenths: int):
    """90度のあとで、見ている向きに小さく回す。

    配置枠は90度だけで決める。小さい角度を同じ枠へ収めると四隅が空く。
    その枠の上右下左を切る。原本側のクリップでは、回したあとの辺に沿わない。
    clip_to_rect は枠をまたぐ画像を残すので、同じ枠へ載せ直して画素を切る。
    """
    page = output.new_page(width=_a4().width, height=_a4().height)
    card = viewer_rotate(tilt)
    full = source[index].rect if clip is None else fitz.Rect(clip)
    fitted = fitted_image_rect(page.rect, full, card)
    rotate = card + skew_ccw_degrees(skew_tenths)
    limit = None if trim is None or trim.is_zero() else _output_trim_rect(fitted, trim)
    if limit is None:
        page.show_pdf_page(
            fitted,
            source,
            index,
            clip=clip,
            keep_proportion=True,
            rotate=rotate,
        )
        return page, None
    work = fitz.open()
    try:
        held = work.new_page(width=page.rect.width, height=page.rect.height)
        held.show_pdf_page(
            fitted,
            source,
            index,
            clip=clip,
            keep_proportion=True,
            rotate=rotate,
        )
        page.show_pdf_page(limit, work, 0, clip=limit, keep_proportion=True, rotate=0)
    finally:
        work.close()
    return page, limit


def _output_trim_rect(fitted: fitz.Rect, trim: PageTrim) -> fitz.Rect:
    """回したあとの配置枠を、出力の上右下左で縮める。中身の倍率は変えない。"""
    dest = fitz.Rect(
        fitted.x0 + fitted.width * trim.left / 1000,
        fitted.y0 + fitted.height * trim.top / 1000,
        fitted.x1 - fitted.width * trim.right / 1000,
        fitted.y1 - fitted.height * trim.bottom / 1000,
    )
    if dest.width <= 1 or dest.height <= 1:
        raise ValueError("端の削りは0から40%です。")
    return dest


def _skew_for(skews, source_index: int, page_index: int) -> int:
    if not skews:
        return 0
    found = skews.get((int(source_index), int(page_index)))
    return 0 if found is None else int(found)


def fitted_image_rect(content: fitz.Rect, clip: fitz.Rect, rotate_ccw: int) -> fitz.Rect:
    """縦横比を保って content の中央へ収めた矩形。トリミング前の画像枠。"""
    width = float(clip.width)
    height = float(clip.height)
    if int(rotate_ccw) % 180:
        width, height = height, width
    if width <= 0 or height <= 0 or content.width <= 0 or content.height <= 0:
        return content
    factor = min(content.width / width, content.height / height)
    placed_w = width * factor
    placed_h = height * factor
    x = content.x0 + (content.width - placed_w) / 2
    y = content.y0 + (content.height - placed_h) / 2
    return fitz.Rect(x, y, x + placed_w, y + placed_h)


def image_box_fractions(clip_width: float, clip_height: float, tilt: int) -> dict[str, float]:
    """トリミング前の画像枠を、A4 用紙に対する割合で返す。"""
    page = _a4()
    fitted = fitted_image_rect(
        page,
        fitz.Rect(0, 0, float(clip_width), float(clip_height)),
        viewer_rotate(tilt),
    )
    return {
        "x": (fitted.x0 - page.x0) / page.width,
        "y": (fitted.y0 - page.y0) / page.height,
        "w": fitted.width / page.width,
        "h": fitted.height / page.height,
    }


def image_box_for_piece(page, part: int, tilt: int) -> dict[str, float]:
    """編集画面のバーを置く枠。表示回転はメモリ上のページへ焼く。"""
    _bake_display_rotation(page)
    clip = _clip_for_part(page.rect, part, tilt)
    shown = page.rect if clip is None else fitz.Rect(clip)
    return image_box_fractions(float(shown.width), float(shown.height), tilt)


def trimmed_placement(
    clip: fitz.Rect,
    fitted: fitz.Rect,
    trim: PageTrim,
    rotate_ccw: int,
) -> tuple[fitz.Rect, fitz.Rect]:
    """出力の四辺と同じ割合だけ、原本クリップと配置枠を縮める。

    縮尺は辺ごとにトリミング前と同じままになる。
    """
    src_top, src_right, src_bottom, src_left = _source_insets(trim, rotate_ccw)
    clip_w = float(clip.width)
    clip_h = float(clip.height)
    placed = fitz.Rect(
        clip.x0 + clip_w * src_left / 1000,
        clip.y0 + clip_h * src_top / 1000,
        clip.x1 - clip_w * src_right / 1000,
        clip.y1 - clip_h * src_bottom / 1000,
    )
    fit_w = float(fitted.width)
    fit_h = float(fitted.height)
    dest = fitz.Rect(
        fitted.x0 + fit_w * trim.left / 1000,
        fitted.y0 + fit_h * trim.top / 1000,
        fitted.x1 - fit_w * trim.right / 1000,
        fitted.y1 - fit_h * trim.bottom / 1000,
    )
    if placed.width <= 1 or placed.height <= 1 or dest.width <= 1 or dest.height <= 1:
        raise ValueError("端の削りは0から40%です。")
    return dest, placed


def _source_insets(trim: PageTrim, rotate_ccw: int) -> tuple[int, int, int, int]:
    """出力の上右下左を、原本クリップの上右下左へ戻す。

    show_pdf_page の rotate は反時計回り。右へ 90 度は 270 で、用紙の上は原本の左。
    """
    edges = (trim.top, trim.right, trim.bottom, trim.left)
    order = {
        0: (0, 1, 2, 3),
        90: (3, 0, 1, 2),
        180: (2, 3, 0, 1),
        270: (1, 2, 3, 0),
    }[int(rotate_ccw) % 360]
    return edges[order[0]], edges[order[1]], edges[order[2]], edges[order[3]]


def _trim_for(trims, source_index: int, page_index: int, part: int) -> PageTrim | None:
    if not trims:
        return None
    found = trims.get((int(source_index), int(page_index), int(part)))
    if found is None or found.is_zero():
        return None
    return found


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


def a4_points() -> tuple[float, float]:
    page = _a4()
    return float(page.width), float(page.height)


def _stamp_box(font_path: str, style: StampStyle | None = None) -> tuple[float, float]:
    chosen = _chosen_style(style)
    scale = chosen.size / STAMP_FONT_SIZE
    font = fitz.Font(fontfile=font_path)
    width = font.text_length(STAMP_SAMPLE, fontsize=chosen.size)
    return width + STAMP_PAD_X * scale * 2, STAMP_BOX_HEIGHT * scale


def clamp_stamp_offset(dx: int, dy: int, *, box_w: float, box_h: float) -> tuple[int, int, float, float, float, float]:
    """既定の左上からの点を、枠全体が用紙に収まる整数へ収める。

    戻り値は dx, dy, 既定の左上, 収めたあとの左上。
    """
    page = _a4()
    origin_x = page.x1 - STAMP_MARGIN_PT - box_w
    origin_y = page.y0 + STAMP_MARGIN_PT
    min_dx = math.ceil(page.x0 - origin_x - 1e-6)
    max_dx = math.floor((page.x1 - box_w) - origin_x + 1e-6)
    min_dy = math.ceil(page.y0 - origin_y - 1e-6)
    max_dy = math.floor((page.y1 - box_h) - origin_y + 1e-6)
    clamped_dx = min(max(int(dx), int(min_dx)), int(max_dx))
    clamped_dy = min(max(int(dy), int(min_dy)), int(max_dy))
    return (
        clamped_dx,
        clamped_dy,
        origin_x,
        origin_y,
        origin_x + clamped_dx,
        origin_y + clamped_dy,
    )


def stamp_frame(dx: int = 0, dy: int = 0, style: StampStyle | None = None) -> dict | None:
    """編集画面がつまみを置くための枠。選んだフォントが無いときは None。"""
    chosen = _chosen_style(style)
    try:
        font_path = require_stamp_font(chosen)
    except StampFontMissing:
        return None
    box_w, box_h = _stamp_box(font_path, chosen)
    page = _a4()
    clamped_dx, clamped_dy, origin_x, origin_y, x, y = clamp_stamp_offset(
        dx,
        dy,
        box_w=box_w,
        box_h=box_h,
    )
    return {
        "pageWidth": float(page.width),
        "pageHeight": float(page.height),
        "boxWidth": float(box_w),
        "boxHeight": float(box_h),
        "originX": float(origin_x),
        "originY": float(origin_y),
        "x": float(x),
        "y": float(y),
        "dx": clamped_dx,
        "dy": clamped_dy,
        "color": color_hex(chosen.color),
        "fontSize": chosen.size,
        "font": chosen.font,
        "borderWidth": chosen.size / STAMP_FONT_SIZE,
        "fontFamily": _STAMP_FACE[chosen.font].css_family,
    }


def _stamp_rect(box_w: float, box_h: float, dx: int, dy: int) -> fitz.Rect:
    _dx, _dy, _origin_x, _origin_y, x, y = clamp_stamp_offset(dx, dy, box_w=box_w, box_h=box_h)
    return fitz.Rect(x, y, x + box_w, y + box_h)


def _draw_stamp(
    page,
    label: str,
    font_path: str,
    box_w: float,
    box_h: float,
    dx: int = 0,
    dy: int = 0,
    style: StampStyle | None = None,
) -> None:
    chosen = _chosen_style(style)
    rect = _stamp_rect(box_w, box_h, dx, dy)
    page.draw_rect(rect, color=chosen.color, width=chosen.size / STAMP_FONT_SIZE)
    page.insert_font(fontname=_FONT_NAME, fontfile=font_path)
    font = fitz.Font(fontfile=font_path)
    ascender = font.ascender * chosen.size
    descender = font.descender * chosen.size
    text_height = ascender - descender
    baseline = rect.y0 + (rect.height - text_height) / 2 + ascender
    text_width = font.text_length(label, fontsize=chosen.size)
    page.insert_text(
        fitz.Point(rect.x0 + (rect.width - text_width) / 2, baseline),
        label,
        fontname=_FONT_NAME,
        fontsize=chosen.size,
        color=chosen.color,
    )
