"""カードの状態。起動時の表示は配置だけを使い、PDF は開かない。"""
from __future__ import annotations

import base64
import ctypes
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path

from .names import branch_number, display_label, document_title, output_filename
from .layout import (
    OUTPUT_DIR_NAME,
    Card,
    Layout,
    Mask,
    PageRow,
    Skew,
    Slot,
    Trim,
    adopt_output_directory,
    default_layout,
    layout_path,
    load_layout,
    save_layout,
    store_path,
    with_next_series,
    with_series,
)
from .pages import assignment_is_natural, shift_source_indexes


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


def downloads_dir() -> Path:
    """この PC のダウンロードフォルダ。移動されていても、その場所を返す。"""
    try:
        folder_id = _GUID.from_buffer_copy(uuid.UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le)
        allocated = ctypes.c_wchar_p()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        found = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(allocated))
        text = allocated.value
        if allocated:
            ole32.CoTaskMemFree(ctypes.cast(allocated, ctypes.c_void_p))
        if found == 0 and text:
            return Path(text)
    except (AttributeError, OSError, ValueError):
        pass
    return Path.home() / "Downloads"


@dataclass(frozen=True)
class OpenEditor:
    number: int
    slot_index: int


def _locked(method):
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return call


def _clamp_zoom(value: float) -> float:
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        return 1.15
    if zoom < 0.2:
        return 0.2
    if zoom > 4:
        return 4
    return zoom


def directory_available(folder: Path, timeout: float = 3) -> bool:
    text = str(folder)
    if text.startswith("\\\\"):
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(folder.is_dir)
        try:
            return bool(future.result(timeout=timeout))
        except Exception:
            return False
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    try:
        return folder.is_dir()
    except OSError:
        return False


class Session:
    def __init__(self, folder: Path | str | None = None) -> None:
        self.layout = default_layout()
        self.folder: Path | None = None
        self.notice = ""
        self.card_errors: dict[int, str] = {}
        self.open_editor: OpenEditor | None = None
        self._lock = threading.RLock()
        if folder is not None:
            self._use_output_folder(Path(folder))

    @_locked
    def view(self) -> dict:
        output = self.folder / OUTPUT_DIR_NAME if self.folder else None
        editing = self.open_editor
        return {
            "folder": str(self.folder) if self.folder else "",
            "outputDir": str(output) if output else "",
            "series": self.layout.series,
            "labelTemplate": self.layout.label_template,
            "grayscale": self.layout.grayscale,
            "stamp": _stamp_view(self.layout.stamp),
            "enabledSeries": list(self.layout.enabled_series),
            "canAddSeries": len(self.layout.enabled_series) < 5,
            "message": self.notice,
            "editor": None if editing is None else {"number": editing.number, "slot": editing.slot_index},
            "cards": [self._card_view(card) for card in self.layout.cards],
        }

    @_locked
    def begin_edit(self, number: int, slot_index: int) -> dict:
        number = int(number)
        slot_index = int(slot_index)
        card = self._card(number)
        _check_slot(card, slot_index)
        if not card.slots[slot_index].files:
            raise ValueError("プレビューできるPDFがありません。")
        self.open_editor = OpenEditor(number, slot_index)
        return self.view()

    @_locked
    def finish_edit(self) -> dict:
        self.open_editor = None
        return self.view()

    @_locked
    def editor_identity(self) -> dict | None:
        editing = self.open_editor
        if editing is None:
            return None
        return {"number": editing.number, "slot": editing.slot_index}

    @_locked
    def edit_context(self) -> dict:
        editing = self.open_editor
        if editing is None:
            raise ValueError("編集は開いていません。")
        card = self._card(editing.number)
        slot = card.slots[editing.slot_index]
        from .stamp import a4_points, stamp_frame

        width, height = a4_points()
        return {
            "number": editing.number,
            "slot": editing.slot_index,
            "label": display_label(self.layout.label_template, card.number, editing.slot_index, len(card.slots)),
            "rotation": slot.rotation,
            "split": card.split_a4,
            "pageWidth": width,
            "pageHeight": height,
            "stampFrame": stamp_frame(slot.stamp_dx, slot.stamp_dy, self.layout.stamp),
        }

    @_locked
    def ensure_editable(self, number: int) -> None:
        self._guard(int(number))

    def _guard(self, number: int) -> None:
        editing = self.open_editor
        if editing is not None and editing.number == number:
            raise ValueError("このカードは編集中です。")

    def _use_output_folder(self, folder: Path) -> None:
        if not directory_available(folder):
            self.notice = directory_message()
            return
        self.folder = folder
        try:
            adopt_output_directory(folder)
        except OSError:
            self.notice = f"保存先を {OUTPUT_DIR_NAME} に移せません。"
            return
        if not layout_path(folder).is_file():
            return
        try:
            loaded = load_layout(folder)
        except (OSError, ValueError):
            self.notice = "配置ファイルを読めません。"
            return
        if loaded is None:
            self.notice = "配置ファイルを読めません。"
            return
        self.layout = loaded
        self.card_errors = {}

    @_locked
    def add_card(self) -> dict:
        number = max((card.number for card in self.layout.cards), default=0) + 1
        self.layout = self._with_cards(self.layout.cards + (_empty(number),))
        self._persist()
        return self.view()

    @_locked
    def delete_slot(self, number: int, slot_index: int) -> dict:
        """枝番カードを消す。最後の1枚なら証拠番号ごと消し、後ろの番号を詰める。"""
        number = int(number)
        self._guard(number)
        card = self._card(number)
        if slot_index < 0 or slot_index >= len(card.slots):
            raise ValueError("証拠の番号が不正です。")
        if len(card.slots) == 1:
            self._remove_evidence(number)
            editing = self.open_editor
            if editing is not None and editing.number > number:
                self.open_editor = OpenEditor(editing.number - 1, editing.slot_index)
            return self.view()
        self._put(_without_slot(card, slot_index))
        return self.view()

    @_locked
    def move_slot(self, number: int, slot_index: int, before_number: int | None = None) -> dict:
        """証拠番号の境目へ動かす。枝番を動かすと、そのスロットは枝番なしの番号になる。"""
        number = int(number)
        slot_index = int(slot_index)
        self._guard(number)
        card = self._card(number)
        _check_slot(card, slot_index)
        if before_number is not None:
            before_number = int(before_number)
            self._card(before_number)
        if len(card.slots) == 1 and before_number == number:
            return self.view()

        editing = self.open_editor
        cards = list(self.layout.cards)
        src = next(index for index, item in enumerate(cards) if item.number == number)
        marks = [item.number for item in cards]
        errors = {item.number: self.card_errors.get(item.number, "") for item in cards}
        if len(card.slots) == 1:
            moved = cards.pop(src)
            moved_mark = marks.pop(src)
            dest = _insert_at(cards, before_number)
            if dest == src:
                return self.view()
            cards.insert(dest, moved)
            marks.insert(dest, moved_mark)
        else:
            pulled, remainder = _extract_slot(card, slot_index)
            cards[src] = remainder
            dest = _insert_at(cards, before_number)
            cards.insert(dest, pulled)
            marks.insert(dest, None)
        renumbered = tuple(_replace(item, number=index) for index, item in enumerate(cards, start=1))
        self.card_errors = {
            index: errors[mark]
            for index, mark in enumerate(marks, start=1)
            if mark is not None and errors.get(mark)
        }
        if editing is not None:
            self.open_editor = OpenEditor(marks.index(editing.number) + 1, editing.slot_index)
        self.layout = self._with_cards(renumbered)
        self._persist()
        return self.view()

    @_locked
    def set_series(self, series: str) -> dict:
        self.layout = with_series(self.layout, series)
        self._persist()
        return self.view()

    @_locked
    def set_grayscale(self, enabled: bool) -> dict:
        self.layout = Layout(
            series=self.layout.series,
            enabled_series=self.layout.enabled_series,
            cards=self.layout.cards,
            last_written=self.layout.last_written,
            label_template=self.layout.label_template,
            grayscale=enabled is True,
            stamp=self.layout.stamp,
        )
        self._persist()
        return self.view()

    @_locked
    def set_stamp_style(self, color, size, font) -> dict:
        from .stamp import require_stamp_font, stamp_style_from_request

        style = stamp_style_from_request(color, size, font)
        require_stamp_font(style)
        if style == self.layout.stamp:
            return self.view()
        self.layout = replace(self.layout, stamp=style)
        self._persist()
        return self.view()

    @_locked
    def clear(self) -> dict:
        """作業中の配置を起動直後に戻す。生成済みPDFと出力フォルダは残す。"""
        self.open_editor = None
        self.card_errors = {}
        self.layout = default_layout()
        self._persist()
        return self.view()

    @_locked
    def add_series_choice(self) -> dict:
        self.layout = with_next_series(self.layout)
        self._persist()
        return self.view()

    @_locked
    def add_branch(self, number: int) -> dict:
        self._guard(int(number))
        card = self._card(number)
        self._put(_replace(card, slots=card.slots + (Slot(()),)))
        return self.view()

    @_locked
    def set_title(self, number: int, title: str, slot_index: int = 0) -> dict:
        self._guard(int(number))
        card = self._card(number)
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        slots = list(card.slots)
        slots[slot_index] = replace(slots[slot_index], title=str(title or ""))
        self._put(_replace(card, slots=tuple(slots)))
        return self.view()

    @_locked
    def rotate(self, number: int, slot_index: int = 0) -> dict:
        self._guard(int(number))
        card = self._card(number)
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        slots = list(card.slots)
        slot = slots[slot_index]
        slots[slot_index] = replace(slot, rotation=(slot.rotation + 90) % 360)
        self._put(_replace(card, slots=tuple(slots)))
        return self.view()

    @_locked
    def set_split(self, number: int, split: bool) -> dict:
        self._guard(int(number))
        card = self._card(number)
        if bool(split) == card.split_a4:
            return self.view()
        self._put(_replace(card, split_a4=bool(split), pages=None, trims=(), skews=()))
        return self.view()

    @_locked
    def set_stamp_offset(self, number: int, slot_index: int, dx: int, dy: int) -> dict:
        from .stamp import StampFontMissing, require_stamp_font, stamp_frame

        card = self._card(int(number))
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        require_stamp_font(self.layout.stamp, placing=True)
        frame = stamp_frame(_point(dx), _point(dy), self.layout.stamp)
        if frame is None:
            raise StampFontMissing("証拠番号の位置を決められません。")
        slots = list(card.slots)
        slots[slot_index] = replace(slots[slot_index], stamp_dx=frame["dx"], stamp_dy=frame["dy"])
        self._put(_replace(card, slots=tuple(slots)))
        return {"dx": frame["dx"], "dy": frame["dy"], "stampFrame": frame}

    @_locked
    def add_file(self, number: int, slot_index: int, file_path: str) -> dict:
        self._guard(int(number))
        card = self._card(number)
        stored = self._store(file_path)
        slots = list(card.slots)
        slot = slots[slot_index]
        insert_at = sum(len(item.files) for item in slots[:slot_index]) + len(slot.files)
        slots[slot_index] = replace(slot, files=slot.files + (stored,))
        pages = _shift(card.pages, insert_at)
        masks = _shift_sources(card.masks, insert_at)
        trims = _shift_sources(card.trims, insert_at)
        skews = _shift_sources(card.skews, insert_at)
        self._put(_replace(card, slots=tuple(slots), pages=pages, masks=masks, trims=trims, skews=skews))
        return self.view()

    @_locked
    def replace_file(self, number: int, slot_index: int, file_index: int, file_path: str) -> dict:
        self._guard(int(number))
        card = self._card(number)
        stored = self._store(file_path)
        slots = list(card.slots)
        files = list(slots[slot_index].files)
        files[file_index] = stored
        flat = sum(len(item.files) for item in slots[:slot_index]) + file_index
        slots[slot_index] = replace(slots[slot_index], files=tuple(files))
        masks = _drop_sources(card.masks, flat, 1, 1)
        trims = _drop_sources(card.trims, flat, 1, 1)
        skews = _drop_sources(card.skews, flat, 1, 1)
        self._put(_replace(card, slots=tuple(slots), pages=None, masks=masks, trims=trims, skews=skews))
        return self.view()

    @_locked
    def replace_slot(self, number: int, slot_index: int, paths: list[str]) -> dict:
        self._guard(int(number))
        if not paths:
            return self.view()
        card = self._card(number)
        stored = tuple(self._store(path) for path in paths)
        slots = list(card.slots)
        start = sum(len(item.files) for item in slots[:slot_index])
        old_count = len(slots[slot_index].files)
        slots[slot_index] = replace(slots[slot_index], files=stored)
        masks = _drop_sources(card.masks, start, old_count, len(stored))
        trims = _drop_sources(card.trims, start, old_count, len(stored))
        skews = _drop_sources(card.skews, start, old_count, len(stored))
        self._put(_replace(card, slots=tuple(slots), pages=None, masks=masks, trims=trims, skews=skews))
        return self.view()

    @_locked
    def drop_files(self, number: int, slot_index: int, file_index: int | None, paths: list[str], replace: bool = False) -> dict:
        self._guard(int(number))
        if not paths:
            return self.view()
        if replace:
            return self.replace_slot(number, slot_index, paths)
        if file_index is None:
            for path in paths:
                self.add_file(number, slot_index, path)
            return self.view()
        self.replace_file(number, slot_index, file_index, paths[0])
        for path in paths[1:]:
            self.add_file(number, slot_index, path)
        return self.view()

    @_locked
    def editor(self, number: int, slot_index: int = 0) -> dict:
        """枝番カードの編集は、その枝番の出すページと、その原本の除くページだけ。"""
        card = self._card(number)
        _check_slot(card, slot_index)
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        group = slot_index + 1
        start, end = _slot_source_span(files_per_slot, slot_index)
        shown = list(buckets.get(group) or [])
        hidden = [ref for ref in buckets.get(0) or [] if start <= ref[0] < end]
        tilt = card.slots[slot_index].rotation
        boxes = _image_boxes(self._paths(card), shown + hidden, tilt)
        return {
            "number": number,
            "slot": slot_index,
            "masks": _project_masks(
                self._paths(card),
                card.masks,
                shown,
                tilt,
                card.skews,
            ),
            "columns": [
                {
                    "group": group,
                    "title": "出すページ",
                    "pages": [_piece(ref, group, card.trims, boxes, card.skews) for ref in shown],
                },
                {
                    "group": 0,
                    "title": "除くページ",
                    "pages": [_piece(ref, 0, card.trims, boxes, card.skews) for ref in hidden],
                },
            ],
        }

    @_locked
    def set_pages(self, number: int, submitted: list, slot_index: int = 0) -> dict:
        card = self._card(number)
        _check_slot(card, slot_index)
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        group = slot_index + 1
        editable = _editable_keys(buckets, files_per_slot, slot_index)
        parsed = _parse_slot_pages(submitted, editable, group)
        current = _current_assignment(card, buckets)
        merged = [item for item in current if item[0] not in editable] + parsed
        self._store_assignment(card, natural, files_per_slot, merged)
        return self.view()

    @_locked
    def add_mask(
        self,
        number: int,
        slot_index: int,
        source: int,
        page: int,
        part: int,
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> dict:
        from .stamp import open_source, source_mask_from_output

        card = self._card(int(number))
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        source = int(source)
        page = int(page)
        part = int(part)
        if part not in (0, 1, 2):
            raise ValueError("マスキングの範囲が不正です。")
        paths = self._paths(card)
        if source < 0 or source >= len(paths):
            raise ValueError("原本のページが見つかりません。")
        left, top, width, height = _output_span(x, y, w, h)
        document = open_source(paths[source])
        try:
            if page < 0 or page >= document.page_count:
                raise ValueError("原本のページが見つかりません。")
            stored = source_mask_from_output(
                document[page],
                part,
                card.slots[slot_index].rotation,
                (left, top, left + width, top + height),
                _skew_tenths(card, source, page),
            )
        finally:
            document.close()
        if stored is None:
            raise ValueError("マスキングできる範囲がありません。")
        mask = Mask(source=source, page=page, x=stored[0], y=stored[1], w=stored[2], h=stored[3])
        card = _replace(card, masks=card.masks + (mask,))
        self._put(card)
        return {"masks": self._mask_views(card, slot_index)}

    @_locked
    def remove_mask(
        self,
        number: int,
        slot_index: int,
        source: int,
        page: int,
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> dict:
        card = self._card(int(number))
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        key = _mask_identity(int(source), int(page), x, y, w, h)
        kept = []
        removed = False
        for mask in card.masks:
            if not removed and _mask_identity(mask.source, mask.page, mask.x, mask.y, mask.w, mask.h) == key:
                removed = True
                continue
            kept.append(mask)
        card = _replace(card, masks=tuple(kept))
        self._put(card)
        return {"masks": self._mask_views(card, slot_index)}

    @_locked
    def set_trim(
        self,
        number: int,
        slot_index: int,
        source: int,
        page: int,
        part: int,
        top: int,
        right: int,
        bottom: int,
        left: int,
    ) -> dict:
        from .stamp import page_trim

        card = self._card(int(number))
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        key = (_whole(source), _whole(page), _whole(part))
        if key[2] not in (0, 1, 2):
            raise ValueError("原本のページが見つかりません。")
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        if key not in _editable_keys(buckets, files_per_slot, slot_index):
            raise ValueError("原本のページが見つかりません。")
        parsed = page_trim(top, right, bottom, left)
        kept = [row for row in card.trims if (row.source, row.page, row.part) != key]
        if parsed is not None:
            kept.append(Trim(
                source=key[0],
                page=key[1],
                part=key[2],
                top=parsed.top,
                right=parsed.right,
                bottom=parsed.bottom,
                left=parsed.left,
            ))
        card = _replace(card, trims=tuple(kept))
        self._put(card)
        edges = parsed
        return {
            "trim": {
                "top": 0 if edges is None else edges.top,
                "right": 0 if edges is None else edges.right,
                "bottom": 0 if edges is None else edges.bottom,
                "left": 0 if edges is None else edges.left,
            },
        }

    @_locked
    def set_skew(
        self,
        number: int,
        slot_index: int,
        source: int,
        page: int,
        tenths: int,
    ) -> dict:
        from .stamp import page_skew

        card = self._card(int(number))
        slot_index = int(slot_index)
        _check_slot(card, slot_index)
        source = _whole(source)
        page = _whole(page)
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        editable = _editable_keys(buckets, files_per_slot, slot_index)
        if not any(ref[0] == source and ref[1] == page for ref in editable):
            raise ValueError("原本のページが見つかりません。")
        parsed = page_skew(tenths)
        kept = [row for row in card.skews if (row.source, row.page) != (source, page)]
        if parsed is not None:
            kept.append(Skew(source=source, page=page, tenths=parsed))
        card = _replace(card, skews=tuple(kept))
        self._put(card)
        return {
            "skewTenths": 0 if parsed is None else parsed,
            "masks": self._mask_views(card, slot_index),
        }

    def _mask_views(self, card: Card, slot_index: int) -> list[dict]:
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        return _project_masks(
            self._paths(card),
            card.masks,
            list(buckets.get(slot_index + 1) or []),
            card.slots[slot_index].rotation,
            card.skews,
        )

    @_locked
    def reset_pages(self, number: int, slot_index: int = 0) -> dict:
        card = self._card(number)
        _check_slot(card, slot_index)
        if card.pages is None:
            return self.view()
        natural, files_per_slot = self._natural(card)
        buckets = _resolved(card, natural, files_per_slot)
        group = slot_index + 1
        current_group = {ref: found for found, refs in buckets.items() for ref in refs}
        home = {ref: _home_slot(ref[0], files_per_slot) for ref in natural}
        reset_keys = {
            ref for ref in natural
            if home[ref] == slot_index or current_group.get(ref) == group
        }
        by_group: dict[int, list] = {index: [] for index in range(len(card.slots) + 1)}
        for key, found in _current_assignment(card, buckets):
            if key in reset_keys:
                continue
            by_group[found].append(key)
        for ref in natural:
            if ref in reset_keys:
                by_group[home[ref] + 1].append(ref)
        merged = []
        for found in list(range(1, len(card.slots) + 1)) + [0]:
            merged.extend((key, found) for key in by_group[found])
        self._store_assignment(card, natural, files_per_slot, merged)
        return self.view()

    def _store_assignment(self, card: Card, natural, files_per_slot, merged) -> None:
        stored = [
            {
                "source_index": key[0],
                "page_index": key[1],
                "part": key[2],
                "group_index": group,
                "position": index,
            }
            for index, (key, group) in enumerate(merged)
        ]
        if assignment_is_natural(natural, stored, files_per_slot):
            pages = None
        else:
            pages = tuple(
                PageRow(
                    source=row["source_index"],
                    page=row["page_index"],
                    part=row["part"],
                    group=row["group_index"],
                    position=row["position"],
                )
                for row in stored
            )
        self._put(_replace(card, pages=pages))

    def media(self, number: int) -> dict:
        """ファイルがあるカードだけ、表示のあとでページ数とサムネイルを数える。"""
        from .names import stamp_label
        from .pages import resolve_buckets
        from .stamp import inspect_source_pages, render_piece_jpeg, render_stamped_page_jpeg, skew_lookup, trim_lookup

        with self._lock:
            card = self._card(int(number))
            paths = self._paths(card)
            counts = [len(slot.files) for slot in card.slots]
            evidence_number = card.number
            split = card.split_a4
            rotations = [slot.rotation for slot in card.slots]
            offsets = [(slot.stamp_dx, slot.stamp_dy) for slot in card.slots]
            page_rows = _rows(card.pages)
            template = self.layout.label_template
            grayscale = self.layout.grayscale
            style = self.layout.stamp
            masks = card.masks
            trims = card.trims
            skews = card.skews
        trim_map = trim_lookup(trims)
        skew_map = skew_lookup(skews)
        empty_slots = [{"index": index, "pageCount": 0, "thumb": ""} for index in range(len(counts))]
        if not paths:
            return {"number": evidence_number, "pageCount": 0, "splittable": False, "thumb": "", "slots": empty_slots}
        _raw, _expanded, splittable, natural = inspect_source_pages(paths, split=split)
        buckets = resolve_buckets(list(natural), page_rows, counts)
        slots = []
        cursor = 0
        first_thumb = ""
        for index, count in enumerate(counts):
            end = cursor + count
            source_refs = [ref for ref in natural if cursor <= ref[0] < end]
            output_refs = list(buckets.get(index + 1) or [])
            thumb = ""
            if output_refs:
                stamp_dx, stamp_dy = offsets[index]
                jpeg = render_stamped_page_jpeg(
                    paths,
                    stamp_label(template, evidence_number, branch_number(index, len(counts))),
                    0,
                    zoom=0.48,
                    tilt=rotations[index],
                    split=split,
                    pages=tuple(output_refs),
                    grayscale=grayscale,
                    stamp_dx=stamp_dx,
                    stamp_dy=stamp_dy,
                    masks=masks,
                    style=style,
                    trims=trim_map,
                    skews=skew_map,
                )
                thumb = base64.b64encode(jpeg).decode("ascii")
            elif source_refs:
                source, page, part = source_refs[0]
                jpeg = render_piece_jpeg(
                    paths, source, page, part, zoom=0.48, tilt=rotations[index],
                    grayscale=grayscale, masks=masks, trims=trim_map, skews=skew_map,
                )
                thumb = base64.b64encode(jpeg).decode("ascii")
            if thumb and not first_thumb:
                first_thumb = thumb
            slots.append({"index": index, "pageCount": len(output_refs), "thumb": thumb})
            cursor = end
        return {
            "number": evidence_number,
            "pageCount": sum(slot["pageCount"] for slot in slots),
            "splittable": splittable,
            "thumb": first_thumb,
            "slots": slots,
        }

    def preview(self, number: int, slot_index: int, page_index: int, zoom: float = 1.15, bare: bool = False) -> dict:
        from .plan import jobs_from_layout
        from .stamp import render_stamped_page_jpeg, skew_lookup, trim_lookup

        with self._lock:
            folder = self.folder if self.folder is not None else Path(".")
            layout = self.layout
            card = self._card(int(number))
            _check_slot(card, int(slot_index))
            tilt = card.slots[int(slot_index)].rotation
            split = card.split_a4
        built = jobs_from_layout(layout, folder)
        job = next(
            (item for item in built.jobs if item.number == int(number) and item.slot_index == int(slot_index)),
            None,
        )
        if job is None:
            raise ValueError("プレビューできるPDFがありません。")
        pages = tuple(job.pages) if job.pages is not None else None
        jpeg = render_stamped_page_jpeg(
            job.sources,
            job.stamp,
            int(page_index),
            zoom=_clamp_zoom(zoom),
            tilt=tilt,
            split=split,
            pages=pages,
            grayscale=layout.grayscale,
            stamp_dx=job.stamp_dx,
            stamp_dy=job.stamp_dy,
            draw_stamp=not bare,
            # 編集画面の黒は要素が描く。ここに焼くと、X で外した直後に下の画像が残る。
            masks=(),
            style=layout.stamp,
            trims=trim_lookup(job.trims),
            skews=skew_lookup(job.skews),
        )
        return {
            "image": base64.b64encode(jpeg).decode("ascii"),
            "pageCount": len(pages) if pages is not None else _job_page_count(job),
            "label": job.stamp,
        }

    def piece(self, number: int, source: int, page: int, part: int, zoom: float = 0.45, slot_index: int | None = None) -> dict:
        from .stamp import render_piece_jpeg, skew_lookup, trim_lookup

        with self._lock:
            card = self._card(int(number))
            paths = self._paths(card)
            if slot_index is None:
                tilt = _rotation_for_source(card, int(source))
            else:
                slot_index = int(slot_index)
                _check_slot(card, slot_index)
                tilt = card.slots[slot_index].rotation
            grayscale = self.layout.grayscale
            masks = card.masks
            trims = trim_lookup(card.trims)
            skews = skew_lookup(card.skews)
        jpeg = render_piece_jpeg(
            paths,
            int(source),
            int(page),
            int(part),
            zoom=_clamp_zoom(zoom),
            tilt=tilt,
            grayscale=grayscale,
            masks=masks,
            trims=trims,
            skews=skews,
        )
        return {"image": base64.b64encode(jpeg).decode("ascii")}

    def generate(self) -> dict:
        from .plan import jobs_from_layout
        from .stamp import StampFontMissing
        from .write import write_jobs

        with self._lock:
            if self.folder is None:
                return {"ok": False, **self.view(), "message": directory_message()}
            folder = self.folder
            layout = self.layout
            last_written = layout.last_written
            grayscale = layout.grayscale
            style = layout.stamp
        built = jobs_from_layout(layout, folder)
        try:
            result = write_jobs(
                folder,
                built.jobs,
                last_written=last_written,
                preserve=built.preserve,
                grayscale=grayscale,
                style=style,
            )
        except StampFontMissing as exc:
            return {"ok": False, **self.view(), "message": str(exc)}
        with self._lock:
            self.card_errors = {row["number"]: row["message"] for row in built.errors}
            for row in result["errors"]:
                number = _number_for_filename(built.jobs, row["filename"])
                if number is not None:
                    self.card_errors[number] = row["message"]
            self.layout = Layout(
                series=self.layout.series,
                enabled_series=self.layout.enabled_series,
                cards=self.layout.cards,
                last_written=result["keep"],
                label_template=self.layout.label_template,
                grayscale=self.layout.grayscale,
                stamp=self.layout.stamp,
            )
            self._persist()
            written = len(result["written"])
            failed = len(result["errors"]) + len(built.errors)
            if written and failed:
                message = f"{written}件を {folder / OUTPUT_DIR_NAME} に保存しました。{failed}件は保存できませんでした。"
            elif failed:
                message = "保存できませんでした。"
            elif not written:
                message = "保存するPDFがありません。"
            else:
                message = f"{written}件を {folder / OUTPUT_DIR_NAME} に保存しました。"
            return {
                "ok": failed == 0,
                "written": result["written"],
                "errors": result["errors"],
                **self.view(),
                "message": message,
            }

    def _card_view(self, card: Card) -> dict:
        slot_count = len(card.slots)
        slots = []
        for index, slot in enumerate(card.slots):
            slots.append({
                "index": index,
                "label": display_label(self.layout.label_template, card.number, index, slot_count),
                "filename": self._slot_filename(card, index),
                "title": slot.title,
                "rotation": slot.rotation,
                "files": [{"index": file_index, "name": Path(stored).name, "stored": stored} for file_index, stored in enumerate(slot.files)],
            })
        return {
            "number": card.number,
            "label": display_label(self.layout.label_template, card.number, 0, 1) if slot_count == 1 else display_label(self.layout.label_template, card.number, 0, slot_count),
            "title": card.slots[0].title,
            "rotation": card.slots[0].rotation,
            "splitA4": card.split_a4,
            "slots": slots,
            "hasFile": any(slot.files for slot in card.slots),
            "message": self.card_errors.get(card.number, ""),
        }

    def _slot_filename(self, card: Card, slot_index: int) -> str:
        slot = card.slots[slot_index]
        first = slot.files[0] if slot.files else None
        title = document_title(slot.title, first)
        branch = branch_number(slot_index, len(card.slots))
        return output_filename(self.layout.label_template, card.number, branch, title)

    def _card(self, number: int) -> Card:
        for card in self.layout.cards:
            if card.number == number:
                return card
        raise ValueError("証拠の番号が不正です。")

    def _remove_evidence(self, number: int) -> None:
        kept = [card for card in self.layout.cards if card.number != number]
        renumbered = tuple(_replace(card, number=index) for index, card in enumerate(kept, start=1))
        shifted: dict[int, str] = {}
        for new_number, card in enumerate(kept, start=1):
            message = self.card_errors.get(card.number)
            if message:
                shifted[new_number] = message
        self.card_errors = shifted
        self.layout = self._with_cards(renumbered)
        self._persist()

    def _put(self, card: Card) -> None:
        cards = tuple(card if item.number == card.number else item for item in self.layout.cards)
        self.layout = self._with_cards(cards)
        self._persist()

    def _with_cards(self, cards: tuple[Card, ...]) -> Layout:
        return Layout(
            series=self.layout.series,
            enabled_series=self.layout.enabled_series,
            cards=cards,
            last_written=self.layout.last_written,
            label_template=self.layout.label_template,
            grayscale=self.layout.grayscale,
            stamp=self.layout.stamp,
        )

    def _persist(self) -> None:
        if self.folder is not None:
            save_layout(self.folder, self.layout)

    def _store(self, file_path: str) -> str:
        if self.folder is None:
            path = Path(file_path)
            if path.suffix.lower() != ".pdf" or not path.is_file():
                raise ValueError("PDFを選んでください。")
            return str(path.resolve())
        return store_path(self.folder, Path(file_path))

    def _paths(self, card: Card) -> tuple[str, ...]:
        folder = self.folder or Path(".")
        from .layout import resolve_stored_path

        stored = [item for slot in card.slots for item in slot.files]
        return tuple(str(resolve_stored_path(folder, item)) for item in stored)

    def _natural(self, card: Card) -> tuple[list[tuple[int, int, int]], list[int]]:
        from .stamp import inspect_source_pages

        paths = self._paths(card)
        _raw, _expanded, _splittable, natural = inspect_source_pages(paths, split=card.split_a4)
        return list(natural), [len(slot.files) for slot in card.slots]


def _whole(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("原本のページが見つかりません。")
    return value


def _point(value) -> int:
    if isinstance(value, bool):
        raise ValueError("印の位置の指定が不正です。")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError("印の位置の指定が不正です。")


def directory_message() -> str:
    return "フォルダを確認できません。"


def _stamp_view(style) -> dict:
    from .stamp import stamp_view

    return stamp_view(style)


def _empty(number: int) -> Card:
    return Card(number=number, split_a4=False, slots=(Slot(()),), pages=None)


def _extract_slot(card: Card, slot_index: int) -> tuple[Card, Card]:
    start = sum(len(slot.files) for slot in card.slots[:slot_index])
    removed = len(card.slots[slot_index].files)
    pulled = Card(
        number=card.number,
        split_a4=card.split_a4,
        slots=(card.slots[slot_index],),
        pages=_pages_for_extracted_slot(card.pages, start, removed),
        masks=_sources_in_span(card.masks, start, removed),
        trims=_sources_in_span(card.trims, start, removed),
        skews=_sources_in_span(card.skews, start, removed),
    )
    return pulled, _without_slot(card, slot_index)


def _pages_for_extracted_slot(pages, start: int, removed: int):
    if not pages:
        return None
    adjusted = []
    for row in pages:
        if not start <= row.source < start + removed:
            continue
        adjusted.append(PageRow(
            source=row.source - start,
            page=row.page,
            part=row.part,
            group=0 if row.group == 0 else 1,
            position=len(adjusted),
        ))
    return tuple(adjusted) or None


def _insert_at(cards: list[Card], before_number: int | None) -> int:
    if before_number is None:
        return len(cards)
    for index, card in enumerate(cards):
        if card.number == before_number:
            return index
    raise ValueError("証拠の番号が不正です。")


def _without_slot(card: Card, slot_index: int) -> Card:
    start = sum(len(slot.files) for slot in card.slots[:slot_index])
    removed = len(card.slots[slot_index].files)
    deleted_group = slot_index + 1
    slots = card.slots[:slot_index] + card.slots[slot_index + 1 :]
    return _replace(
        card,
        slots=slots,
        pages=_pages_after_slot_removed(card.pages, start, removed, deleted_group, len(slots)),
        masks=_drop_sources(card.masks, start, removed, 0),
        trims=_drop_sources(card.trims, start, removed, 0),
        skews=_drop_sources(card.skews, start, removed, 0),
    )


def _pages_after_slot_removed(pages, start: int, removed: int, deleted_group: int, slots_left: int):
    if not pages:
        return None
    adjusted = []
    for row in pages:
        if start <= row.source < start + removed:
            continue
        source = row.source - removed if row.source >= start + removed else row.source
        group = row.group
        if group == deleted_group:
            continue
        if slots_left == 1:
            if group != 0:
                group = 1
        elif group > deleted_group:
            group -= 1
        adjusted.append(PageRow(source=source, page=row.page, part=row.part, group=group, position=len(adjusted)))
    return tuple(adjusted) or None


def _replace(card: Card, **changes) -> Card:
    data = {
        "number": card.number,
        "split_a4": card.split_a4,
        "slots": card.slots,
        "pages": card.pages,
        "masks": card.masks,
        "trims": card.trims,
        "skews": card.skews,
    }
    data.update(changes)
    return Card(**data)


def _shift_sources(rows, insert_at: int):
    if not rows:
        return rows
    return tuple(
        replace(row, source=row.source + 1) if row.source >= insert_at else row
        for row in rows
    )


def _sources_in_span(rows, start: int, count: int):
    return tuple(
        replace(row, source=row.source - start)
        for row in rows
        if start <= row.source < start + count
    )


def _drop_sources(rows, start: int, old_count: int, new_count: int):
    if not rows:
        return rows
    delta = new_count - old_count
    kept = []
    for row in rows:
        if start <= row.source < start + old_count:
            continue
        source = row.source + delta if row.source >= start + old_count else row.source
        kept.append(row if source == row.source else replace(row, source=source))
    return tuple(kept)


def _output_span(x, y, w, h) -> tuple[float, float, float, float]:
    values = []
    for value in (x, y, w, h):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("マスキングの範囲が不正です。")
        values.append(float(value))
    left, top, width, height = values
    if width < 0:
        left += width
        width = -width
    if height < 0:
        top += height
        height = -height
    if width < 4 or height < 4:
        raise ValueError("マスキングできる範囲がありません。")
    return left, top, width, height


def _mask_identity(source, page, x, y, w, h) -> tuple:
    return (int(source), int(page), round(float(x), 2), round(float(y), 2), round(float(w), 2), round(float(h), 2))


def _skew_tenths(card: Card, source: int, page: int) -> int:
    found = next((row.tenths for row in card.skews if row.source == source and row.page == page), 0)
    return int(found)


def _project_masks(paths, masks, refs, tilt: int, skews=()) -> list[dict]:
    from .stamp import open_source, output_mask_from_source

    if not masks or not refs:
        return []
    opened = {}
    views = []
    try:
        for source, page, part in refs:
            wanted = [mask for mask in masks if mask.source == int(source) and mask.page == int(page)]
            if not wanted or int(source) < 0 or int(source) >= len(paths):
                continue
            document = opened.get(int(source))
            if document is None:
                document = open_source(paths[int(source)])
                opened[int(source)] = document
            if int(page) < 0 or int(page) >= document.page_count:
                continue
            tenths = next((row.tenths for row in skews if row.source == int(source) and row.page == int(page)), 0)
            for mask in wanted:
                box = output_mask_from_source(
                    document[int(page)], int(part), tilt, mask.x, mask.y, mask.w, mask.h, int(tenths),
                )
                if box is None:
                    continue
                views.append({
                    "source": mask.source,
                    "page": mask.page,
                    "part": int(part),
                    "x": box[0],
                    "y": box[1],
                    "w": box[2],
                    "h": box[3],
                    "sx": mask.x,
                    "sy": mask.y,
                    "sw": mask.w,
                    "sh": mask.h,
                })
    finally:
        for document in opened.values():
            document.close()
    return views


def _shift(pages: tuple[PageRow, ...] | None, insert_at: int) -> tuple[PageRow, ...] | None:
    if not pages:
        return pages
    rows = shift_source_indexes(
        [
            {
                "source_index": row.source,
                "page_index": row.page,
                "part": row.part,
                "group_index": row.group,
                "position": row.position,
            }
            for row in pages
        ],
        insert_at,
    )
    return tuple(
        PageRow(
            source=row["source_index"],
            page=row["page_index"],
            part=row["part"],
            group=row["group_index"],
            position=row["position"],
        )
        for row in rows
    )


def _rotation_for_source(card: Card, source: int) -> int:
    cursor = 0
    for slot in card.slots:
        count = len(slot.files)
        if cursor <= source < cursor + count:
            return slot.rotation
        cursor += count
    return card.slots[0].rotation


def _check_slot(card: Card, slot_index: int) -> None:
    if slot_index < 0 or slot_index >= len(card.slots):
        raise ValueError("証拠の番号が不正です。")


def _resolved(card: Card, natural, files_per_slot):
    from .pages import resolve_buckets

    return resolve_buckets(list(natural), _rows(card.pages), files_per_slot)


def _slot_source_span(files_per_slot: list[int], slot_index: int) -> tuple[int, int]:
    start = sum(files_per_slot[:slot_index])
    return start, start + files_per_slot[slot_index]


def _home_slot(source_index: int, files_per_slot: list[int]) -> int:
    remaining = source_index
    for slot, count in enumerate(files_per_slot):
        if remaining < count:
            return slot
        remaining -= count
    return max(0, len(files_per_slot) - 1)


def _editable_keys(buckets, files_per_slot: list[int], slot_index: int) -> set[tuple[int, int, int]]:
    group = slot_index + 1
    start, end = _slot_source_span(files_per_slot, slot_index)
    keys = {ref for ref in buckets.get(group) or []}
    keys.update(ref for ref in buckets.get(0) or [] if start <= ref[0] < end)
    return keys


def _parse_slot_pages(submitted: list, editable: set[tuple[int, int, int]], group: int) -> list[tuple[tuple[int, int, int], int]]:
    if not isinstance(submitted, list) or not submitted:
        raise ValueError("出すページは1枚残してください。")
    parsed = []
    seen: set[tuple[int, int, int]] = set()
    output_count = 0
    for row in submitted:
        if not isinstance(row, dict):
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
        try:
            key = (int(row.get("source")), int(row.get("page")), int(row.get("part")))
            chosen = int(row.get("group"))
        except (TypeError, ValueError):
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。") from None
        if key not in editable or key in seen or chosen not in (0, group) or key[2] not in (0, 1, 2):
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
        seen.add(key)
        if chosen == group:
            output_count += 1
        parsed.append((key, chosen))
    if seen != editable:
        raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
    if output_count < 1:
        raise ValueError("出すページは1枚残してください。")
    return parsed


def _current_assignment(card: Card, buckets) -> list[tuple[tuple[int, int, int], int]]:
    if card.pages:
        return [((row.source, row.page, row.part), row.group) for row in card.pages]
    ordered = []
    for group in range(1, len(card.slots) + 1):
        ordered.extend((ref, group) for ref in buckets.get(group) or [])
    ordered.extend((ref, 0) for ref in buckets.get(0) or [])
    return ordered


def _rows(pages: tuple[PageRow, ...] | None) -> list[dict]:
    if not pages:
        return []
    return [
        {
            "source_index": row.source,
            "page_index": row.page,
            "part": row.part,
            "group_index": row.group,
            "position": row.position,
        }
        for row in pages
    ]


def _piece(ref: tuple[int, int, int], group: int, trims, boxes, skews=()) -> dict:
    source, page, part = ref
    found = next(
        (row for row in trims if row.source == source and row.page == page and row.part == part),
        None,
    )
    angle = next((row.tenths for row in skews if row.source == source and row.page == page), 0)
    payload = {
        "source": source,
        "page": page,
        "part": part,
        "group": group,
        "trim": {
            "top": 0 if found is None else found.top,
            "right": 0 if found is None else found.right,
            "bottom": 0 if found is None else found.bottom,
            "left": 0 if found is None else found.left,
        },
        "skewTenths": int(angle),
    }
    box = boxes.get((source, page, part))
    if box is not None:
        payload["imageBox"] = box
    return payload


def _image_boxes(paths, refs, tilt: int) -> dict:
    from .stamp import image_box_for_piece, open_source

    opened = {}
    boxes = {}
    try:
        for source, page, part in refs:
            source = int(source)
            page = int(page)
            part = int(part)
            if source < 0 or source >= len(paths):
                continue
            document = opened.get(source)
            if document is None:
                document = open_source(paths[source])
                opened[source] = document
            if page < 0 or page >= document.page_count:
                continue
            boxes[(source, page, part)] = image_box_for_piece(document[page], part, tilt)
    finally:
        for document in opened.values():
            document.close()
    return boxes


def _job_page_count(job) -> int:
    if job.pages is not None:
        return len(job.pages)
    from .stamp import inspect_source_pages

    _raw, _expanded, _splittable, natural = inspect_source_pages(job.sources, split=job.split_a4)
    return len(natural)


def _number_for_filename(jobs, filename: str) -> int | None:
    for job in jobs:
        if job.filename == filename:
            return job.number
    return None
