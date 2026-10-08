"""カードから、印字が受け取る生成ジョブを作る。"""
from __future__ import annotations

from dataclasses import dataclass

from .layout import Card, Layout, PageRow, Slot, resolve_stored_path
from .names import document_title, output_filename, stamp_label
from .pages import GROUP_PRIMARY, resolve_buckets
from .stamp import inspect_source_pages


@dataclass(frozen=True)
class OutputJob:
    number: int
    sources: tuple[str, ...]
    stamp: str
    filename: str
    rotation: int
    split_a4: bool
    pages: tuple[tuple[int, int, int], ...] | None
    slot_index: int = 0


@dataclass(frozen=True)
class PlanBuild:
    jobs: tuple[OutputJob, ...]
    errors: tuple[dict, ...]
    preserve: tuple[str, ...]


def jobs_from_layout(layout: Layout, folder: Path) -> PlanBuild:
    jobs: list[OutputJob] = []
    errors: list[dict] = []
    preserve: list[str] = []
    for card in layout.cards:
        built, card_errors, card_preserve = _jobs_for_card(layout.label_template, card, folder)
        jobs.extend(built)
        errors.extend(card_errors)
        preserve.extend(card_preserve)
    return PlanBuild(jobs=tuple(jobs), errors=tuple(errors), preserve=tuple(preserve))


def _jobs_for_card(series: str, card: Card, folder: Path) -> tuple[list[OutputJob], list[dict], list[str]]:
    flat = _flat_files(card)
    if not flat:
        return [], [], []
    resolved = tuple(str(resolve_stored_path(folder, stored)) for stored in flat)
    files_per_slot = [len(slot.files) for slot in card.slots]
    try:
        _raw, _expanded, _splittable, natural = inspect_source_pages(resolved, split=card.split_a4)
    except Exception as exc:
        return [], [_card_error(card, f"原本を開けません。{exc}")], _fallback_names(series, card, files_per_slot)
    if not natural:
        return [], [_card_error(card, "ページがありません。")], _fallback_names(series, card, files_per_slot)
    rows = _page_rows(card.pages)
    buckets = resolve_buckets(list(natural), rows, files_per_slot)
    branch_groups = [group for group in range(2, len(card.slots) + 1) if buckets.get(group)]
    branched = bool(branch_groups)
    jobs: list[OutputJob] = []
    for group in range(GROUP_PRIMARY, len(card.slots) + 1):
        refs = list(buckets.get(group) or [])
        if not refs:
            continue
        branch = group if branched else None
        pages: tuple[tuple[int, int, int], ...] | None
        if branch is None and refs == list(natural) and not buckets.get(0):
            pages = None
        else:
            pages = tuple(refs)
        slot = card.slots[group - 1]
        jobs.append(OutputJob(
            number=card.number,
            sources=resolved,
            stamp=stamp_label(series, card.number, branch),
            filename=output_filename(series, card.number, branch, _slot_document_title(slot)),
            rotation=slot.rotation,
            split_a4=card.split_a4,
            pages=pages,
            slot_index=group - 1,
        ))
    return jobs, [], []


def _flat_files(card: Card) -> tuple[str, ...]:
    files: list[str] = []
    for slot in card.slots:
        files.extend(slot.files)
    return tuple(files)


def _slot_document_title(slot: Slot) -> str:
    first = slot.files[0] if slot.files else None
    return document_title(slot.title, first)


def _page_rows(pages: tuple[PageRow, ...] | None) -> list[dict]:
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


def _fallback_names(series: str, card: Card, files_per_slot: list[int]) -> list[str]:
    if not any(files_per_slot[1:]):
        return [output_filename(series, card.number, None, _slot_document_title(card.slots[0]))]
    names = []
    for slot_index, count in enumerate(files_per_slot):
        if count:
            names.append(output_filename(series, card.number, slot_index + 1, _slot_document_title(card.slots[slot_index])))
    return names


def _card_error(card: Card, message: str) -> dict:
    titled = next((slot for slot in card.slots if slot.title.strip() or slot.files), card.slots[0])
    return {"number": card.number, "title": _slot_document_title(titled), "message": message}


