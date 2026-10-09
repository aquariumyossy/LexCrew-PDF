"""カードから、印字が受け取る生成ジョブを作る。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .layout import Card, Layout, PageRow, Slot, resolve_stored_path
from .names import (
    branch_number,
    display_label,
    document_title,
    filename_stem_token,
    output_filename,
    stamp_label,
)
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
    warnings: tuple[dict, ...] = ()


@dataclass(frozen=True)
class MergeChoice:
    """PDF を開かずに決める、枝番を1ファイルにするかどうか。"""

    filename: str = ""
    token: str = ""
    included: tuple[int, ...] = ()
    warning: str = ""


def jobs_from_layout(layout: Layout, folder: Path) -> PlanBuild:
    jobs: list[OutputJob] = []
    errors: list[dict] = []
    preserve: list[str] = []
    warnings: list[dict] = []
    for card in layout.cards:
        built, card_errors, card_preserve, card_warnings = _jobs_for_card(
            layout.label_template,
            card,
            folder,
            separator=layout.filename_separator,
            merge_branches=layout.merge_branches,
        )
        jobs.extend(built)
        errors.extend(card_errors)
        preserve.extend(card_preserve)
        warnings.extend(card_warnings)
    return PlanBuild(
        jobs=tuple(jobs),
        errors=tuple(errors),
        preserve=tuple(preserve),
        warnings=tuple(warnings),
    )


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
) -> tuple[list[OutputJob], list[dict], list[str], list[dict]]:
    flat = _flat_files(card)
    if not flat:
        return [], [], [], []
    resolved = tuple(str(resolve_stored_path(folder, stored)) for stored in flat)
    files_per_slot = [len(slot.files) for slot in card.slots]
    try:
        _raw, _expanded, _splittable, natural = inspect_source_pages(resolved, split=card.split_a4)
    except Exception as exc:
        return [], [_card_error(card, f"原本を開けません。{exc}")], _fallback_names(
            series, card, files_per_slot, separator=separator, merge_branches=merge_branches,
        ), []
    if not natural:
        return [], [_card_error(card, "ページがありません。")], _fallback_names(
            series, card, files_per_slot, separator=separator, merge_branches=merge_branches,
        ), []
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
    # 印の番号はカードの枝番のまま。空の枝番や、出すページの無い枝番で番号が飛ぶときは、
    # 1~3 のような範囲にせず、枝番ごとに出す。カードを消せば番号は詰まる。
    if merge_branches and len(jobs) >= 2 and all(job.pages is not None for job in jobs):
        indexes = [job.slot_index for job in jobs]
        if indexes == list(range(indexes[0], indexes[-1] + 1)):
            return [_merged_job(series, card, jobs, separator)], [], [], []
        missing = [index for index in range(indexes[0], indexes[-1] + 1) if index not in indexes]
        return jobs, [], [], [{
            "number": card.number,
            "message": branch_gap_warning(series, card, missing),
        }]
    return jobs, [], [], []


def file_merge_choice(series: str, card: Card, separator: str, merge_branches: bool) -> MergeChoice:
    """ファイルのある枝番だけで合体を決める。原本は開かない。"""
    if not merge_branches or len(card.slots) < 2:
        return MergeChoice()
    filled = [index for index, slot in enumerate(card.slots) if slot.files]
    if len(filled) < 2:
        return MergeChoice()
    expected = list(range(filled[0], filled[-1] + 1))
    if filled != expected:
        missing = [index for index in expected if index not in set(filled)]
        return MergeChoice(warning=branch_gap_warning(series, card, missing))
    slot_count = len(card.slots)
    start = branch_number(filled[0], slot_count)
    end = branch_number(filled[-1], slot_count)
    title = merged_document_title(card)
    return MergeChoice(
        filename=output_filename(
            series, card.number, start, title, separator=separator, branch_end=end,
        ),
        token=filename_stem_token(series, card.number, start, end),
        included=tuple(filled),
    )


def merged_document_title(card: Card) -> str:
    """まとめた PDF の書名。親（最初の枝番）の書名を優先し、空なら後の枝番へ落ちる。"""
    first = card.slots[0]
    title = document_title(first.title, first.files[0] if first.files else None)
    if title:
        return title
    for slot in card.slots[1:]:
        title = document_title(slot.title, slot.files[0] if slot.files else None)
        if title:
            return title
    return ""


def branch_gap_warning(series: str, card: Card, missing: list[int]) -> str:
    """番号が飛ぶのでまとめない、という案内。印の番号は付け替えない。"""
    slot_count = len(card.slots)
    empty = []
    excluded = []
    for index in missing:
        label = display_label(series, card.number, index, slot_count)
        if card.slots[index].files:
            excluded.append(label)
        else:
            empty.append(label)
    parts = []
    if empty:
        parts.append(f"{_and_join(empty)}にPDFが無い")
    if excluded:
        parts.append(f"{_and_join(excluded)}に出すページが無い")
    reason = "、".join(parts)
    if excluded and not empty:
        tail = "その枝番を削除すると、残った番号が詰まります。"
    else:
        tail = "空の枝番を削除すると番号が詰まります。"
    return f"{reason}ため、まとめて出力しません。{tail}"


def _and_join(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]}と{labels[1]}"
    return "、".join(labels[:-1]) + "と" + labels[-1]


def _merged_job(series: str, card: Card, jobs: list[OutputJob], separator: str) -> OutputJob:
    """同じ号証の枝番を、1つの PDF にする。印は各枝番の先頭ページ。"""
    slot_count = len(card.slots)
    first = jobs[0]
    last = jobs[-1]
    start = branch_number(first.slot_index, slot_count)
    end = branch_number(last.slot_index, slot_count)
    title = merged_document_title(card)
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
            title,
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
        title=title,
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
    choice = file_merge_choice(series, card, separator, merge_branches)
    if choice.filename:
        return [choice.filename]
    slot_count = len(card.slots)
    names = []
    for slot_index, count in enumerate(files_per_slot):
        if not count:
            continue
        names.append(output_filename(
            series,
            card.number,
            branch_number(slot_index, slot_count),
            _slot_document_title(card.slots[slot_index]),
            separator=separator,
        ))
    return names


def _card_error(card: Card, message: str) -> dict:
    titled = next((slot for slot in card.slots if slot.title.strip() or slot.files), card.slots[0])
    return {"number": card.number, "title": _slot_document_title(titled), "message": message}


def _tsv_cell(value: str) -> str:
    return (value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
