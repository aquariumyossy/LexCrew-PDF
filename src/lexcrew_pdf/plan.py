"""カードから、印字が受け取る生成ジョブを作る。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .layout import Card, Layout, PageRow, Slot, resolve_stored_path
from .names import (
    branch_number,
    display_label,
    document_title,
    exhibit_number,
    filename_stem_token,
    output_filename,
    shown_number,
    stamp_label,
)
from .pages import GROUP_PRIMARY, resolve_buckets
from .stamp import inspect_source_pages


@dataclass(frozen=True)
class OutputPart:
    """合体した PDF の、一つの枝番。先頭ページだけに、この印を押す。"""

    stamp: str
    exhibit: str
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
    exhibit: str = ""
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
            merge_branches=layout.merge_branches,
            shown=shown_number(layout.first_number, card.number),
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
                        exhibit=part.exhibit,
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


def _jobs_for_card(
    series: str,
    card: Card,
    folder: Path,
    *,
    merge_branches: bool,
    shown: int,
) -> tuple[list[OutputJob], list[dict], list[str], list[dict]]:
    flat = _flat_files(card)
    if not flat:
        return [], [], [], []
    resolved = tuple(str(resolve_stored_path(folder, stored)) for stored in flat)
    files_per_slot = [len(slot.files) for slot in card.slots]
    try:
        tilts = [slot.rotation for slot in card.slots for _stored in slot.files]
        _raw, _expanded, _splittable, natural, _spreads = inspect_source_pages(
            resolved, split=card.split_a4, tilts=tilts,
        )
    except Exception as exc:
        return [], [_card_error(card, f"原本を開けません。{exc}")], _fallback_names(
            series, card, files_per_slot, merge_branches=merge_branches, shown=shown,
        ), []
    if not natural:
        return [], [_card_error(card, "ページがありません。")], _fallback_names(
            series, card, files_per_slot, merge_branches=merge_branches, shown=shown,
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
            stamp=stamp_label(series, shown, branch),
            exhibit=exhibit_number(series, shown, branch),
            filename=output_filename(series, shown, branch, title),
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
    page_counts = [
        len(list(buckets.get(group) or []))
        for group in range(GROUP_PRIMARY, len(card.slots) + 1)
    ]
    if merge_branches and len(jobs) >= 2 and all(job.pages is not None for job in jobs):
        indexes = [job.slot_index for job in jobs]
        if slots_share_one_file(page_counts):
            return [_merged_job(series, card, jobs, shown)], [], [], []
        missing = [index for index in range(indexes[0], indexes[-1] + 1) if index not in indexes]
        return jobs, [], [], [{
            "number": card.number,
            "message": branch_gap_warning(series, card, missing, shown),
        }]
    return jobs, [], [], []


def slots_share_one_file(page_counts: list[int]) -> bool:
    """出すページのある枝番が隣り合っているとき、1つの PDF にまとまる。"""
    present = [index for index, count in enumerate(page_counts) if count > 0]
    if len(present) < 2:
        return False
    return present == list(range(present[0], present[-1] + 1))


def page_label(
    page_counts: list[int],
    slot_index: int,
    page_index: int,
) -> tuple[int, int] | None:
    """この枝番の中の何ページ目か。1ページの枝番は None。まとめた PDF でも枝番ごとに数える。"""
    slot_index = int(slot_index)
    page_index = int(page_index)
    if slot_index < 0 or slot_index >= len(page_counts) or page_index < 0:
        return None
    total = int(page_counts[slot_index])
    if page_index >= total or total < 2:
        return None
    return page_index + 1, total


def file_merge_choice(series: str, card: Card, merge_branches: bool, shown: int) -> MergeChoice:
    """ファイルのある枝番だけで合体を決める。原本は開かない。"""
    if not merge_branches or len(card.slots) < 2:
        return MergeChoice()
    filled = [index for index, slot in enumerate(card.slots) if slot.files]
    if len(filled) < 2:
        return MergeChoice()
    expected = list(range(filled[0], filled[-1] + 1))
    if filled != expected:
        missing = [index for index in expected if index not in set(filled)]
        return MergeChoice(warning=branch_gap_warning(series, card, missing, shown))
    slot_count = len(card.slots)
    start = branch_number(filled[0], slot_count)
    end = branch_number(filled[-1], slot_count)
    title = merged_document_title(card)
    return MergeChoice(
        filename=output_filename(series, shown, start, title, branch_end=end),
        token=filename_stem_token(series, shown, start, end),
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


def branch_gap_warning(series: str, card: Card, missing: list[int], shown: int) -> str:
    """番号が飛ぶのでまとめない、という案内。印の番号は付け替えない。"""
    slot_count = len(card.slots)
    empty = []
    excluded = []
    for index in missing:
        label = display_label(series, shown, index, slot_count)
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


def _merged_job(series: str, card: Card, jobs: list[OutputJob], shown: int) -> OutputJob:
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
            exhibit=job.exhibit,
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
        exhibit=first.exhibit,
        filename=output_filename(series, shown, start, title, branch_end=end),
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
    merge_branches: bool,
    shown: int,
) -> list[str]:
    choice = file_merge_choice(series, card, merge_branches, shown)
    if choice.filename:
        return [choice.filename]
    slot_count = len(card.slots)
    names = []
    for slot_index, count in enumerate(files_per_slot):
        if not count:
            continue
        names.append(output_filename(
            series,
            shown,
            branch_number(slot_index, slot_count),
            _slot_document_title(card.slots[slot_index]),
        ))
    return names


def _card_error(card: Card, message: str) -> dict:
    return {"number": card.number, "message": message}
