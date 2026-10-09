"""カードから、印字が受け取る生成ジョブを作る。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .layout import Card, Layout, PageRow, Slot, resolve_stored_path
from .names import branch_number, document_title, output_filename, stamp_label
from .pages import GROUP_PRIMARY, resolve_buckets
from .stamp import inspect_source_pages


@dataclass(frozen=True)
class OutputPart:
    """合体した PDF の、一つの枝番。先頭ページだけに、この印を押す。"""

    stamp: str
    title: str
    pages: tuple[tuple[int, int, int], ...]
    rotation: int
    stamp_dx: int
    stamp_dy: int
    slot_index: int


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
    stamp_dx: int = 0
    stamp_dy: int = 0
    masks: tuple = ()
    trims: tuple = ()
    skews: tuple = ()
    title: str = ""
    parts: tuple[OutputPart, ...] = ()


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
        built, card_errors, card_preserve = _jobs_for_card(
            layout.label_template,
            card,
            folder,
            separator=layout.filename_separator,
            merge_branches=layout.merge_branches,
        )
        jobs.extend(built)
        errors.extend(card_errors)
        preserve.extend(card_preserve)
    return PlanBuild(jobs=tuple(jobs), errors=tuple(errors), preserve=tuple(preserve))


def slot_job(jobs, number: int, slot_index: int) -> OutputJob | None:
    """プレビュー用に、その枝番だけのジョブを返す。合体していても枝番は分かれない。"""
    number = int(number)
    slot_index = int(slot_index)
    for job in jobs:
        if job.number != number:
            continue
        if job.parts:
            for part in job.parts:
                if part.slot_index == slot_index:
                    return replace(
                        job,
                        stamp=part.stamp,
                        rotation=part.rotation,
                        pages=part.pages,
                        slot_index=part.slot_index,
                        stamp_dx=part.stamp_dx,
                        stamp_dy=part.stamp_dy,
                        title=part.title,
                        parts=(),
                    )
            continue
        if job.slot_index == slot_index:
            return job
    return None


def evidence_tsv(jobs) -> str:
    """号証と書名。タブ区切りで、出力する枝番ごとに1行。"""
    rows = []
    for job in jobs:
        chunks = job.parts if job.parts else (job,)
        for chunk in chunks:
            rows.append(f"{_tsv_cell(chunk.stamp)}\t{_tsv_cell(chunk.title)}")
    return "\n".join(rows)


def _jobs_for_card(
    series: str,
    card: Card,
    folder: Path,
    *,
    separator: str,
    merge_branches: bool,
) -> tuple[list[OutputJob], list[dict], list[str]]:
    flat = _flat_files(card)
    if not flat:
        return [], [], []
    resolved = tuple(str(resolve_stored_path(folder, stored)) for stored in flat)
    files_per_slot = [len(slot.files) for slot in card.slots]
    try:
        _raw, _expanded, _splittable, natural = inspect_source_pages(resolved, split=card.split_a4)
    except Exception as exc:
        return [], [_card_error(card, f"原本を開けません。{exc}")], _fallback_names(
            series, card, files_per_slot, separator=separator, merge_branches=merge_branches,
        )
    if not natural:
        return [], [_card_error(card, "ページがありません。")], _fallback_names(
            series, card, files_per_slot, separator=separator, merge_branches=merge_branches,
        )
    rows = _page_rows(card.pages)
    buckets = resolve_buckets(list(natural), rows, files_per_slot)
    jobs: list[OutputJob] = []
    for group in range(GROUP_PRIMARY, len(card.slots) + 1):
        refs = list(buckets.get(group) or [])
        if not refs:
            continue
        branch = branch_number(group - 1, len(card.slots))
        pages: tuple[tuple[int, int, int], ...] | None
        if refs == list(natural) and not buckets.get(0):
            pages = None
        else:
            pages = tuple(refs)
        slot = card.slots[group - 1]
        title = _slot_document_title(slot)
        jobs.append(OutputJob(
            number=card.number,
            sources=resolved,
            stamp=stamp_label(series, card.number, branch),
            filename=output_filename(series, card.number, branch, title, separator=separator),
            rotation=slot.rotation,
            split_a4=card.split_a4,
            pages=pages,
            slot_index=group - 1,
            stamp_dx=slot.stamp_dx,
            stamp_dy=slot.stamp_dy,
            masks=card.masks,
            trims=card.trims,
            skews=card.skews,
            title=title,
        ))
    if merge_branches and len(jobs) >= 2 and all(job.pages is not None for job in jobs):
        return [_merged_job(series, card, jobs, separator)], [], []
    return jobs, [], []


def _merged_job(series: str, card: Card, jobs: list[OutputJob], separator: str) -> OutputJob:
    """同じ号証の枝番を、1つの PDF にする。印は各枝番の先頭ページ。"""
    slot_count = len(card.slots)
    first = jobs[0]
    last = jobs[-1]
    start = branch_number(first.slot_index, slot_count)
    end = branch_number(last.slot_index, slot_count)
    parts = tuple(
        OutputPart(
            stamp=job.stamp,
            title=job.title,
            pages=job.pages,
            rotation=job.rotation,
            stamp_dx=job.stamp_dx,
            stamp_dy=job.stamp_dy,
            slot_index=job.slot_index,
        )
        for job in jobs
    )
    return OutputJob(
        number=card.number,
        sources=first.sources,
        stamp=first.stamp,
        filename=output_filename(
            series,
            card.number,
            start,
            first.title,
            separator=separator,
            branch_end=end,
        ),
        rotation=first.rotation,
        split_a4=card.split_a4,
        pages=None,
        slot_index=first.slot_index,
        stamp_dx=first.stamp_dx,
        stamp_dy=first.stamp_dy,
        masks=card.masks,
        trims=card.trims,
        skews=card.skews,
        title=first.title,
        parts=parts,
    )


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


def _fallback_names(
    series: str,
    card: Card,
    files_per_slot: list[int],
    *,
    separator: str,
    merge_branches: bool,
) -> list[str]:
    slot_count = len(card.slots)
    filled = []
    names = []
    for slot_index, count in enumerate(files_per_slot):
        if not count:
            continue
        filled.append(slot_index)
        names.append(output_filename(
            series,
            card.number,
            branch_number(slot_index, slot_count),
            _slot_document_title(card.slots[slot_index]),
            separator=separator,
        ))
    if merge_branches and len(filled) >= 2:
        return [output_filename(
            series,
            card.number,
            branch_number(filled[0], slot_count),
            _slot_document_title(card.slots[filled[0]]),
            separator=separator,
            branch_end=branch_number(filled[-1], slot_count),
        )]
    return names


def _card_error(card: Card, message: str) -> dict:
    titled = next((slot for slot in card.slots if slot.title.strip() or slot.files), card.slots[0])
    return {"number": card.number, "title": _slot_document_title(titled), "message": message}


def _tsv_cell(value: str) -> str:
    return (value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
