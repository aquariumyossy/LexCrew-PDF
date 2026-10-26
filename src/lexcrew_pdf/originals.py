"""原本の複製。カードはここを読み、元のファイルを動かしても壊れない。"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

from .layout import (
    LAYOUT_NAME,
    OUTPUT_DIR_NAME,
    Layout,
    OriginalState,
    check_original,
    require_source_file,
    resolve_stored_path,
)


def originals_dir() -> Path:
    """利用者ごとの原本置き場。テストは LEXCREW_ORIGINALS で差し替える。"""
    override = os.environ.get("LEXCREW_ORIGINALS", "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "LexCrew-PDF" / "originals"
    return Path.home() / ".local" / "share" / "LexCrew-PDF" / "originals"


def copy_original(source: Path) -> Path:
    """原本を複製する。ファイル名は残し、置き場の中で名前が重ならないようにする。"""
    require_source_file(source)
    name = source.name
    if not name or name in {".", ".."} or name != Path(name).name:
        raise ValueError("ファイルの場所が不正です。")
    dest_dir = originals_dir() / uuid.uuid4().hex
    dest_dir.mkdir(parents=True, exist_ok=False)
    dest = dest_dir / name
    try:
        shutil.copyfile(source, dest)
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    return dest.resolve()


def is_stored_copy(folder: Path | None, stored: str) -> bool:
    path = _resolved_stored(folder, stored)
    if path is None:
        return False
    return _is_app_copy(path)


def remember_case(folder: Path) -> None:
    """この出力フォルダの配置を、複製を消す前の参照確認に使う。"""
    try:
        cases = _read_cases()
        if cases is None:
            return
        root = originals_dir().parent
        root.mkdir(parents=True, exist_ok=True)
        registry = _registry_path()
        text = str(folder.resolve())
        if text in cases:
            return
        cases.append(text)
        temporary = registry.with_name(registry.name + ".writing")
        temporary.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, registry)
    except OSError:
        return


def adopt_originals(folder: Path, layout: Layout) -> Layout:
    """古い配置の、まだ残っている原本を複製へ切り替える。無い原本のパスはそのまま残す。"""
    mapping: dict[str, str] = {}
    created: list[str] = []
    try:
        for stored in _iter_stored(layout):
            if stored in mapping or is_stored_copy(folder, stored):
                continue
            if check_original(folder, stored) is not OriginalState.PRESENT:
                continue
            try:
                copied = copy_original(resolve_stored_path(folder, stored))
            except OSError:
                # 権限で読めない原本は「無い」にしない。パスを残し、他の原本は複製する。
                continue
            created.append(str(copied))
            mapping[stored] = str(copied)
    except Exception:
        release_copies(created)
        raise
    if not mapping:
        return layout
    return _map_stored(layout, mapping)


def release_copies(stored_paths, *, live: tuple[str, ...] | list[str] = ()) -> None:
    """他のカードや別案件の配置が参照していない、このアプリが作った複製だけを消す。"""
    saved = _saved_references()
    if saved is None:
        return
    live_keys = _keys(live)
    for stored in stored_paths:
        path = _resolved_stored(None, stored)
        if path is None or not _is_app_copy(path):
            continue
        keys = _keys((stored, str(path)))
        if keys & live_keys or keys & saved:
            continue
        try:
            exists = path.is_file()
        except OSError:
            return
        if exists:
            path.unlink()
        parent = path.parent
        if parent != originals_dir().resolve() and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


def _registry_path() -> Path:
    return originals_dir().parent / "cases.json"


def _read_cases() -> list[str] | None:
    registry = _registry_path()
    try:
        exists = registry.is_file()
    except OSError:
        return None
    if not exists:
        return []
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return list(raw)


def _saved_references() -> set[str] | None:
    """台帳か、どれかの配置が読めないときは None。そのときは複製を消さない。"""
    found: set[str] = set()
    cases = _read_cases()
    if cases is None:
        return None
    for case in cases:
        folder = Path(case)
        layout_file = folder / OUTPUT_DIR_NAME / LAYOUT_NAME
        try:
            exists = layout_file.is_file()
        except OSError:
            return None
        if not exists:
            continue
        try:
            raw = json.loads(layout_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        cards = raw.get("cards")
        if not isinstance(cards, list):
            return None
        for card in cards:
            if not isinstance(card, dict):
                return None
            slots = card.get("slots")
            if not isinstance(slots, list):
                return None
            for slot in slots:
                if not isinstance(slot, dict):
                    return None
                files = slot.get("files")
                if files is None:
                    continue
                if not isinstance(files, list):
                    return None
                for item in files:
                    if not isinstance(item, str):
                        return None
                    found.update(_keys((item,)))
                    resolved = _resolved_stored(folder, item)
                    if resolved is not None:
                        found.add(str(resolved))
    return found


_APP_COPY_HEX = frozenset("0123456789abcdef")


def _is_app_copy(path: Path) -> bool:
    """このアプリが copy_original で作ったファイルだけ。uuid の1段下のファイル。"""
    try:
        relative = path.resolve().relative_to(originals_dir().resolve())
    except (OSError, ValueError):
        return False
    parts = relative.parts
    if len(parts) != 2:
        return False
    folder_name = parts[0]
    return len(folder_name) == 32 and all(char in _APP_COPY_HEX for char in folder_name)


def _resolved_stored(folder: Path | None, stored: str) -> Path | None:
    try:
        if folder is not None and not stored.replace("/", "\\").startswith("\\\\"):
            path = resolve_stored_path(folder, stored)
        else:
            path = Path(stored)
        return path.resolve()
    except (OSError, ValueError):
        return None


def _keys(paths) -> set[str]:
    found: set[str] = set()
    for item in paths:
        found.add(item)
        resolved = _resolved_stored(None, item)
        if resolved is not None:
            found.add(str(resolved))
    return found


def _iter_stored(layout: Layout):
    for card in layout.cards:
        for slot in card.slots:
            yield from slot.files


def _map_stored(layout: Layout, mapping: dict[str, str]) -> Layout:
    cards = []
    for card in layout.cards:
        slots = []
        changed = False
        for slot in card.slots:
            files = tuple(mapping.get(item, item) for item in slot.files)
            if files != slot.files:
                changed = True
                slots.append(replace(slot, files=files))
            else:
                slots.append(slot)
        cards.append(replace(card, slots=tuple(slots)) if changed else card)
    return replace(layout, cards=tuple(cards))
