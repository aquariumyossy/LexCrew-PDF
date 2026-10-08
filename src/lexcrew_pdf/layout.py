"""指定フォルダの配置。PDF はここでは開かない。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .names import INITIAL_SERIES, SERIES, canonical_template, check_series, filename_prefix

LAYOUT_NAME = "layout.json"
OUTPUT_DIR_NAME = "証拠"


@dataclass(frozen=True)
class Slot:
    files: tuple[str, ...]
    title: str = ""
    rotation: int = 0


@dataclass(frozen=True)
class PageRow:
    source: int
    page: int
    part: int
    group: int
    position: int


@dataclass(frozen=True)
class Card:
    number: int
    split_a4: bool
    slots: tuple[Slot, ...]
    pages: tuple[PageRow, ...] | None


@dataclass(frozen=True)
class Layout:
    series: str
    enabled_series: tuple[str, ...]
    cards: tuple[Card, ...]
    last_written: tuple[str, ...]
    label_template: str


def default_layout() -> Layout:
    return Layout(
        series="甲",
        enabled_series=INITIAL_SERIES,
        cards=tuple(_empty_card(number) for number in range(1, 7)),
        last_written=(),
        label_template="甲第N号証",
    )


def layout_path(folder: Path) -> Path:
    return folder / OUTPUT_DIR_NAME / LAYOUT_NAME


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
    cards = tuple(_parse_card(item) for item in cards_raw)
    numbers = [card.number for card in cards]
    if len(numbers) != len(set(numbers)):
        raise ValueError("配置ファイルを読めません。")
    last = raw.get("lastWritten") or []
    if not isinstance(last, list):
        raise ValueError("配置ファイルを読めません。")
    last_written = tuple(_check_output_name(str(name)) for name in last)
    return Layout(
        series=series,
        enabled_series=enabled_series,
        cards=cards,
        last_written=last_written,
        label_template=label_template,
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
        cards.append(item)
    return {
        "series": layout.series,
        "labelTemplate": layout.label_template,
        "enabledSeries": list(layout.enabled_series),
        "cards": cards,
        "lastWritten": list(layout.last_written),
    }


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
    return Layout(
        series=filename_prefix(template),
        enabled_series=layout.enabled_series,
        cards=layout.cards,
        last_written=layout.last_written,
        label_template=template,
    )


def with_next_series(layout: Layout) -> Layout:
    """初期の甲乙丙のあと、丁、次に戊を一度ずつ足す。"""
    enabled = list(layout.enabled_series)
    for series in SERIES:
        if series not in enabled:
            enabled.append(series)
            return Layout(
                series=layout.series,
                enabled_series=tuple(enabled),
                cards=layout.cards,
                last_written=layout.last_written,
                label_template=layout.label_template,
            )
    return layout


def _empty_card(number: int) -> Card:
    return Card(number=number, split_a4=False, slots=(Slot(()),), pages=None)


def _parse_card(raw: dict) -> Card:
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
    slots = tuple(_parse_slot(item, legacy_title, legacy_rotation) for item in slots_raw)
    pages_raw = raw.get("pages", None)
    pages = None if pages_raw is None else tuple(_parse_page(item, index) for index, item in enumerate(pages_raw))
    return Card(
        number=number,
        split_a4=split_a4,
        slots=slots,
        pages=pages,
    )


def _slot_json(slot: Slot) -> dict:
    item = {"files": list(slot.files), "title": slot.title}
    if slot.rotation:
        item["rotation"] = slot.rotation
    return item


def _parse_slot(raw: dict, legacy_title: str, legacy_rotation: int) -> Slot:
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
    return Slot(stored, title, rotation)


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
