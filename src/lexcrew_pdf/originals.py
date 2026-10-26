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
    return _is_inside(path, originals_dir())


def remember_case(folder: Path) -> None:
    """この出力フォルダの配置を、複製を消す前の参照確認に使う。"""
    root = originals_dir().parent
    root.mkdir(parents=True, exist_ok=True)
    registry = _registry_path()
    cases = _read_cases()
    if cases is None:
        cases = []
    text = str(folder.resolve())
    if text in cases:
        return
    cases.append(text)
    temporary = registry.with_name(registry.name + ".writing")
    temporary.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, registry)


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
            copied = copy_original(resolve_stored_path(folder, stored))
            created.append(str(copied))
            mapping[stored] = str(copied)
    except Exception:
        release_copies(created)
        raise
    if not mapping:
        return layout
    return _map_stored(layout, mapping)


def release_copies(stored_paths, *, live: tuple[str, ...] | list[str] = ()) -> None:
    """他のカードや別案件の配置が参照していない複製だけを消す。"""
    if _read_cases() is None and _registry_path().exists():
        return
    live_keys = _keys(live)
    root = originals_dir().resolve()
    saved = _saved_references()
    for stored in stored_paths:
        path = _resolved_stored(None, stored)
        if path is None or not _is_inside(path, root):
            continue
        keys = _keys((stored, str(path)))
        if keys & live_keys or keys & saved:
            continue
        if path.is_file():
            path.unlink()
        parent = path.parent
        if parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


def _registry_path() -> Path:
    return originals_dir().parent / "cases.json"


def _read_cases() -> list[str] | None:
    registry = _registry_path()
    if not registry.is_file():
        return []
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return list(raw)


def _saved_references() -> set[str]:
    found: set[str] = set()
    cases = _read_cases() or []
    for case in cases:
        folder = Path(case)
        layout_file = folder / OUTPUT_DIR_NAME / LAYOUT_NAME
        if not layout_file.is_file():
            continue
        try:
            raw = json.loads(layout_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        cards = raw.get("cards") if isinstance(raw, dict) else None
        if not isinstance(cards, list):
            continue
        for card in cards:
            slots = card.get("slots") if isinstance(card, dict) else None
            if not isinstance(slots, list):
                continue
            for slot in slots:
                files = slot.get("files") if isinstance(slot, dict) else None
                if not isinstance(files, list):
                    continue
                for item in files:
                    if not isinstance(item, str):
                        continue
                    found.update(_keys((item,)))
                    resolved = _resolved_stored(folder, item)
                    if resolved is not None:
                        found.add(str(resolved))
    return found


def _resolved_stored(folder: Path | None, stored: str) -> Path | None:
    try:
        if folder is not None and not stored.replace("/", "\\").startswith("\\\\"):
            path = resolve_stored_path(folder, stored)
        else:
            path = Path(stored)
        return path.resolve()
    except (OSError, ValueError):
        return None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


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
