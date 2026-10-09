"""指定フォルダの配置。PDF はここでは開かない。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from .names import (
    DEFAULT_SEPARATOR,
    INITIAL_SERIES,
    SERIES,
    canonical_template,
    check_separator,
    check_series,
    filename_prefix,
)
from .stamp import DEFAULT_STAMP, StampStyle, stamp_record, stamp_style_from_json

LAYOUT_NAME = "layout.json"
OUTPUT_DIR_NAME = "LexCrew-PDF-Downloads"
LEGACY_OUTPUT_DIR_NAMES = ("LexCrew-PDF", "証拠")


@dataclass(frozen=True)
class Slot:
    files: tuple[str, ...]
    title: str = ""
    rotation: int = 0
    stamp_dx: int = 0
    stamp_dy: int = 0


@dataclass(frozen=True)
class PageRow:
    source: int
    page: int
    part: int
    group: int
    position: int


@dataclass(frozen=True)
class Mask:
    source: int
    page: int
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Trim:
    source: int
    page: int
    part: int
    top: int
    right: int
    bottom: int
    left: int


@dataclass(frozen=True)
class Skew:
    """原本ページの面内傾き。十分の一度。分割した左右は同じ行。"""

    source: int
    page: int
    tenths: int


@dataclass(frozen=True)
class Card:
    number: int
    split_a4: bool
    slots: tuple[Slot, ...]
    pages: tuple[PageRow, ...] | None
    masks: tuple[Mask, ...] = ()
    trims: tuple[Trim, ...] = ()
    skews: tuple[Skew, ...] = ()


@dataclass(frozen=True)
class Layout:
    series: str
    enabled_series: tuple[str, ...]
    cards: tuple[Card, ...]
    last_written: tuple[str, ...]
    label_template: str
    grayscale: bool = False
    stamp: StampStyle = DEFAULT_STAMP
    filename_separator: str = DEFAULT_SEPARATOR
    merge_branches: bool = True


def default_layout() -> Layout:
    return Layout(
        series="甲",
        enabled_series=INITIAL_SERIES,
        cards=tuple(_empty_card(number) for number in range(1, 7)),
        last_written=(),
        label_template="甲第N号証",
        grayscale=False,
        stamp=DEFAULT_STAMP,
        filename_separator=DEFAULT_SEPARATOR,
        merge_branches=True,
    )


def layout_path(folder: Path) -> Path:
    return folder / OUTPUT_DIR_NAME / LAYOUT_NAME


def adopt_output_directory(parent: Path) -> None:
    """古い出力フォルダを LexCrew-PDF-Downloads へ移す。アプリ本体は改名しない。"""
    dest = parent / OUTPUT_DIR_NAME
    if dest.exists():
        return
    for name in LEGACY_OUTPUT_DIR_NAMES:
        legacy = parent / name
        if not legacy.is_dir():
            continue
        if _is_application_directory(legacy):
            if (legacy / LAYOUT_NAME).is_file():
                _lift_output_out_of_application(legacy, dest)
                return
            continue
        legacy.rename(dest)
        return


def _is_application_directory(path: Path) -> bool:
    return any((
        (path / "LexCrew-PDF.bat").is_file(),
        (path / "起動.bat").is_file(),
        (path / "runtime" / "python.exe").is_file(),
        (path / "src" / "lexcrew_pdf" / "__init__.py").is_file(),
    ))


def _written_pdf_names(layout_file: Path) -> tuple[str, ...]:
    try:
        raw = json.loads(layout_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    last = raw.get("lastWritten") if isinstance(raw, dict) else None
    if not isinstance(last, list):
        return ()
    names = []
    for item in last:
        if not isinstance(item, str):
            continue
        if item != Path(item).name or ".." in item or not item.endswith(".pdf"):
            continue
        names.append(item)
    return tuple(names)


def _lift_output_out_of_application(app: Path, dest: Path) -> None:
    layout = app / LAYOUT_NAME
    names = _written_pdf_names(layout)
    dest.mkdir()
    try:
        for name in names:
            source = app / name
            if source.is_file():
                os.replace(source, dest / name)
        for leftover in list(app.glob("*.writing")):
            if leftover.is_file() and leftover.parent == app:
                os.replace(leftover, dest / leftover.name)
        os.replace(layout, dest / LAYOUT_NAME)
    except OSError:
        if dest.is_dir() and not any(dest.iterdir()):
            dest.rmdir()
        raise


def load_layout(folder: Path) -> Layout | None:
    """配置ファイルだけを読む。フォルダ内の PDF は開かない。"""
    path = layout_path(folder)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_layout(raw)


def save_layout(folder: Path, layout: Layout) -> None:
    path = layout_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(
        json.dumps(layout_to_json(layout), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_layout(raw: dict) -> Layout:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    enabled = raw.get("enabledSeries") or list(INITIAL_SERIES)
    if not isinstance(enabled, list) or not enabled:
        raise ValueError("配置ファイルを読めません。")
    enabled_series = tuple(check_series(str(item)) for item in enabled)
    template_raw = raw.get("labelTemplate")
    if template_raw:
        try:
            label_template = canonical_template(str(template_raw))
        except ValueError:
            raise ValueError("配置ファイルを読めません。") from None
        series = filename_prefix(label_template)
    else:
        series = check_series(str(raw.get("series") or "甲"))
        if series not in enabled_series:
            raise ValueError("配置ファイルを読めません。")
        label_template = f"{series}第N号証"
    cards_raw = raw.get("cards")
    if not isinstance(cards_raw, list):
        raise ValueError("配置ファイルを読めません。")
    stamp = stamp_style_from_json(raw.get("stamp"))
    cards = tuple(_parse_card(item, stamp) for item in cards_raw)
    numbers = [card.number for card in cards]
    if len(numbers) != len(set(numbers)):
        raise ValueError("配置ファイルを読めません。")
    last = raw.get("lastWritten") or []
    if not isinstance(last, list):
        raise ValueError("配置ファイルを読めません。")
    last_written = tuple(_check_output_name(str(name)) for name in last)
    if "grayscale" in raw and raw.get("grayscale") is not True and raw.get("grayscale") is not False:
        raise ValueError("配置ファイルを読めません。")
    if "filenameSeparator" in raw:
        try:
            filename_separator = check_separator(raw.get("filenameSeparator"))
        except ValueError:
            raise ValueError("配置ファイルを読めません。") from None
    else:
        filename_separator = DEFAULT_SEPARATOR
    if "mergeBranches" in raw and raw.get("mergeBranches") is not True and raw.get("mergeBranches") is not False:
        raise ValueError("配置ファイルを読めません。")
    # キーが無い古い配置は、枝番をまとめて出す。明示した false だけ分ける。
    if "mergeBranches" not in raw:
        merge_branches = True
    else:
        merge_branches = raw.get("mergeBranches") is True
    return Layout(
        series=series,
        enabled_series=enabled_series,
        cards=cards,
        last_written=last_written,
        label_template=label_template,
        grayscale=raw.get("grayscale") is True,
        stamp=stamp,
        filename_separator=filename_separator,
        merge_branches=merge_branches,
    )


def layout_to_json(layout: Layout) -> dict:
    cards = []
    for card in layout.cards:
        item: dict = {
            "number": card.number,
            "slots": [_slot_json(slot) for slot in card.slots],
        }
        if card.split_a4:
            item["splitA4"] = True
        if card.pages is not None:
            item["pages"] = [
                {
                    "source": row.source,
                    "page": row.page,
                    "part": row.part,
                    "group": row.group,
                    "position": row.position,
                }
                for row in card.pages
            ]
        if card.masks:
            item["masks"] = [
                {
                    "source": mask.source,
                    "page": mask.page,
                    "x": mask.x,
                    "y": mask.y,
                    "w": mask.w,
                    "h": mask.h,
                }
                for mask in card.masks
            ]
        if card.trims:
            item["trims"] = [
                {
                    "source": row.source,
                    "page": row.page,
                    "part": row.part,
                    "top": row.top,
                    "right": row.right,
                    "bottom": row.bottom,
                    "left": row.left,
                }
                for row in card.trims
            ]
        if card.skews:
            item["skews"] = [
                {"source": row.source, "page": row.page, "tenths": row.tenths}
                for row in card.skews
            ]
        cards.append(item)
    payload = {
        "series": layout.series,
        "labelTemplate": layout.label_template,
        "enabledSeries": list(layout.enabled_series),
        "cards": cards,
        "lastWritten": list(layout.last_written),
    }
    if layout.grayscale:
        payload["grayscale"] = True
    if layout.filename_separator != DEFAULT_SEPARATOR:
        payload["filenameSeparator"] = layout.filename_separator
    if not layout.merge_branches:
        payload["mergeBranches"] = False
    record = stamp_record(layout.stamp)
    if record is not None:
        payload["stamp"] = record
    return payload


def store_path(folder: Path, file_path: Path) -> str:
    """指定フォルダの中は相対パス、外は絶対パス。`..` は拒否する。"""
    if not file_path.is_file():
        raise ValueError("PDFが見つかりません。")
    if file_path.suffix.lower() != ".pdf":
        raise ValueError("PDFを選んでください。")
    folder_resolved = folder.resolve()
    resolved = file_path.resolve()
    try:
        relative = resolved.relative_to(folder_resolved)
    except ValueError:
        return str(resolved)
    if ".." in relative.parts:
        raise ValueError("ファイルの場所が不正です。")
    return str(relative)


def resolve_stored_path(folder: Path, stored: str) -> Path:
    _reject_escape(stored)
    path = Path(stored)
    if path.is_absolute():
        return path
    return folder / path


def with_series(layout: Layout, series: str) -> Layout:
    template = canonical_template(series)
    return replace(
        layout,
        series=filename_prefix(template),
        label_template=template,
    )


def with_next_series(layout: Layout) -> Layout:
    """初期の甲乙丙のあと、丁、次に戊を一度ずつ足す。"""
    enabled = list(layout.enabled_series)
    for series in SERIES:
        if series not in enabled:
            enabled.append(series)
            return replace(layout, enabled_series=tuple(enabled))
    return layout


def _empty_card(number: int) -> Card:
    return Card(number=number, split_a4=False, slots=(Slot(()),), pages=None)


def _parse_card(raw: dict, stamp: StampStyle) -> Card:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        number = int(raw.get("number"))
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    if number < 1:
        raise ValueError("配置ファイルを読めません。")
    legacy_title = str(raw.get("title") or "") if "title" in raw else ""
    legacy_rotation = int(raw.get("rotation") or 0)
    if legacy_rotation not in (0, 90, 180, 270):
        raise ValueError("回転は90度単位です。")
    split_a4 = bool(raw.get("splitA4") or False)
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list) or not slots_raw:
        raise ValueError("配置ファイルを読めません。")
    slots = tuple(_parse_slot(item, legacy_title, legacy_rotation, stamp) for item in slots_raw)
    pages_raw = raw.get("pages", None)
    pages = None if pages_raw is None else tuple(_parse_page(item, index) for index, item in enumerate(pages_raw))
    masks_raw = raw.get("masks", [])
    if not isinstance(masks_raw, list):
        raise ValueError("配置ファイルを読めません。")
    trims_raw = raw.get("trims", [])
    if not isinstance(trims_raw, list):
        raise ValueError("配置ファイルを読めません。")
    trims = tuple(_parse_trim(item) for item in trims_raw)
    trim_keys = [(row.source, row.page, row.part) for row in trims]
    if len(trim_keys) != len(set(trim_keys)):
        raise ValueError("配置ファイルを読めません。")
    skews_raw = raw.get("skews", [])
    if not isinstance(skews_raw, list):
        raise ValueError("配置ファイルを読めません。")
    skews = tuple(_parse_skew(item) for item in skews_raw)
    skew_keys = [(row.source, row.page) for row in skews]
    if len(skew_keys) != len(set(skew_keys)):
        raise ValueError("配置ファイルを読めません。")
    return Card(
        number=number,
        split_a4=split_a4,
        slots=slots,
        pages=pages,
        masks=tuple(_parse_mask(item) for item in masks_raw),
        trims=trims,
        skews=skews,
    )


def _slot_json(slot: Slot) -> dict:
    item = {"files": list(slot.files), "title": slot.title}
    if slot.rotation:
        item["rotation"] = slot.rotation
    if slot.stamp_dx or slot.stamp_dy:
        item["stampDx"] = slot.stamp_dx
        item["stampDy"] = slot.stamp_dy
    return item


def _parse_slot(raw: dict, legacy_title: str, legacy_rotation: int, stamp: StampStyle) -> Slot:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    files = raw.get("files") or []
    if not isinstance(files, list):
        raise ValueError("配置ファイルを読めません。")
    stored = tuple(_check_stored_file(str(item)) for item in files)
    # キーが無い古い配置だけ、カードの書名と回転を引き継ぐ。空の書名と回転 0 は空のまま。
    if "title" in raw:
        title = str(raw.get("title") or "")
    else:
        title = legacy_title
    if "rotation" in raw:
        rotation = int(raw.get("rotation") or 0)
        if rotation not in (0, 90, 180, 270):
            raise ValueError("回転は90度単位です。")
    else:
        rotation = legacy_rotation
    stamp_dx = _parse_point(raw, "stampDx")
    stamp_dy = _parse_point(raw, "stampDy")
    stamp_dx, stamp_dy = _stored_offset(stamp_dx, stamp_dy, stamp)
    return Slot(stored, title, rotation, stamp_dx, stamp_dy)


def _parse_point(raw: dict, key: str) -> int:
    if key not in raw or raw[key] is None:
        return 0
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("配置ファイルを読めません。")
    return value


def _stored_offset(dx: int, dy: int, stamp: StampStyle) -> tuple[int, int]:
    if dx == 0 and dy == 0:
        return 0, 0
    from .stamp import stamp_frame

    frame = stamp_frame(dx, dy, stamp)
    if frame is None:
        return dx, dy
    return int(frame["dx"]), int(frame["dy"])


def _parse_trim(raw: dict) -> Trim:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        source = int(raw.get("source"))
        page = int(raw.get("page"))
        part = int(raw.get("part"))
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    if source < 0 or page < 0 or part not in (0, 1, 2):
        raise ValueError("配置ファイルを読めません。")
    from .stamp import page_trim

    try:
        parsed = page_trim(raw.get("top"), raw.get("right"), raw.get("bottom"), raw.get("left"))
    except ValueError:
        raise ValueError("配置ファイルを読めません。") from None
    if parsed is None:
        raise ValueError("配置ファイルを読めません。")
    return Trim(
        source=source,
        page=page,
        part=part,
        top=parsed.top,
        right=parsed.right,
        bottom=parsed.bottom,
        left=parsed.left,
    )


def _parse_skew(raw: dict) -> Skew:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        source = int(raw.get("source"))
        page = int(raw.get("page"))
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    if source < 0 or page < 0:
        raise ValueError("配置ファイルを読めません。")
    from .stamp import page_skew

    tenths = raw.get("tenths")
    if isinstance(tenths, bool) or not isinstance(tenths, int):
        raise ValueError("配置ファイルを読めません。")
    try:
        parsed = page_skew(tenths)
    except ValueError:
        raise ValueError("配置ファイルを読めません。") from None
    if parsed is None:
        raise ValueError("配置ファイルを読めません。")
    return Skew(source=source, page=page, tenths=parsed)


def _parse_mask(raw: dict) -> Mask:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        source = int(raw.get("source"))
        page = int(raw.get("page"))
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    if source < 0 or page < 0:
        raise ValueError("配置ファイルを読めません。")
    x = _parse_length(raw, "x")
    y = _parse_length(raw, "y")
    width = _parse_length(raw, "w")
    height = _parse_length(raw, "h")
    if width <= 0 or height <= 0:
        raise ValueError("配置ファイルを読めません。")
    return Mask(source=source, page=page, x=x, y=y, w=width, h=height)


def _parse_length(raw: dict, key: str) -> float:
    if key not in raw:
        raise ValueError("配置ファイルを読めません。")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("配置ファイルを読めません。")
    return round(float(value), 2)


def _parse_page(raw: dict, index: int) -> PageRow:
    if not isinstance(raw, dict):
        raise ValueError("配置ファイルを読めません。")
    try:
        source = int(raw.get("source"))
        page = int(raw.get("page"))
        part = int(raw.get("part"))
        group = int(raw.get("group"))
        position = int(raw.get("position") if raw.get("position") is not None else index)
    except (TypeError, ValueError):
        raise ValueError("配置ファイルを読めません。") from None
    if part not in (0, 1, 2) or group < 0 or source < 0 or page < 0:
        raise ValueError("配置ファイルを読めません。")
    return PageRow(source=source, page=page, part=part, group=group, position=position)


def _check_stored_file(stored: str) -> str:
    _reject_escape(stored)
    return stored


def _check_output_name(name: str) -> str:
    if name != Path(name).name or not name.endswith(".pdf") or ".." in name:
        raise ValueError("配置ファイルを読めません。")
    return name


def _reject_escape(stored: str) -> None:
    if not stored or ".." in Path(stored).parts:
        raise ValueError("ファイルの場所が不正です。")
