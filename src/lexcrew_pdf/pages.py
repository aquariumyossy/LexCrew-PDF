"""ページ順。原本 PDF は書き換えない。枝番グループはスロットの数に合わせる。"""
from __future__ import annotations

GROUP_EXCLUDED = 0
GROUP_PRIMARY = 1

PageRef = tuple[int, int, int]


def natural_buckets(natural: list[PageRef], files_per_slot: list[int]) -> dict[int, list[PageRef]]:
    """原本順。各スロットのページは、そのスロットのグループに入る。"""
    max_group = max(1, len(files_per_slot))
    buckets: dict[int, list[PageRef]] = {group: [] for group in range(max_group + 1)}
    for ref in natural:
        slot = _slot_for_source(ref[0], files_per_slot)
        buckets[slot + 1].append(ref)
    return buckets


def arrange_pages(
    natural: list[PageRef],
    rows: list[dict],
    *,
    max_group: int,
) -> dict[int, list[PageRef]]:
    """保存した並びを、今の原本に合わせる。新しいページは本体の末尾に足す。"""
    buckets: dict[int, list[PageRef]] = {group: [] for group in range(max_group + 1)}
    natural_set = set(natural)
    seen: set[PageRef] = set()
    ordered = sorted(rows, key=lambda row: int(row.get("position") or 0))
    for row in ordered:
        key = (int(row["source_index"]), int(row["page_index"]), int(row["part"]))
        group = int(row["group_index"])
        if key not in natural_set or key in seen or group not in buckets:
            continue
        seen.add(key)
        buckets[group].append(key)
    for key in natural:
        if key not in seen:
            buckets[GROUP_PRIMARY].append(key)
    return buckets


def resolve_buckets(
    natural: list[PageRef],
    rows: list[dict],
    files_per_slot: list[int],
) -> dict[int, list[PageRef]]:
    """本体が空の指定は無視して、原本の並びに戻す。"""
    max_group = max(1, len(files_per_slot))
    if not rows:
        return natural_buckets(natural, files_per_slot)
    buckets = arrange_pages(natural, rows, max_group=max_group)
    if not buckets[GROUP_PRIMARY]:
        return natural_buckets(natural, files_per_slot)
    return buckets


def validate_page_assignment(
    natural: list[PageRef],
    submitted: list,
    *,
    max_group: int,
) -> list[dict]:
    """原本の全ページがちょうど一度ずつある並びだけを受け付ける。"""
    if not isinstance(submitted, list) or not submitted:
        raise ValueError("出すページは1枚残してください。")
    natural_set = set(natural)
    seen: set[PageRef] = set()
    stored: list[dict] = []
    allowed = set(range(max_group + 1))
    for index, row in enumerate(submitted):
        if not isinstance(row, dict):
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
        try:
            source = int(row.get("source"))
            page = int(row.get("page"))
            part = int(row.get("part"))
            group = int(row.get("group"))
        except (TypeError, ValueError):
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。") from None
        if part not in (0, 1, 2) or group not in allowed:
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
        key = (source, page, part)
        if key not in natural_set or key in seen:
            raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
        seen.add(key)
        stored.append({
            "source_index": source,
            "page_index": page,
            "part": part,
            "group_index": group,
            "position": index,
        })
    if seen != natural_set:
        raise ValueError("ページの指定が原本と合いません。画面を読み直してください。")
    primary = sum(1 for row in stored if row["group_index"] == GROUP_PRIMARY)
    if primary < 1:
        raise ValueError("出すページは1枚残してください。")
    return stored


def assignment_is_natural(natural: list[PageRef], stored: list[dict], files_per_slot: list[int]) -> bool:
    if any(row["group_index"] == GROUP_EXCLUDED for row in stored):
        return False
    expected = natural_buckets(natural, files_per_slot)
    for group, refs in expected.items():
        if group == GROUP_EXCLUDED:
            continue
        got = [
            (row["source_index"], row["page_index"], row["part"])
            for row in stored
            if row["group_index"] == group
        ]
        if got != refs:
            return False
    return True


def shift_source_indexes(rows: list[dict], insert_at: int) -> list[dict]:
    """スロットの末尾へファイルを足したとき、それ以降の原本番号をずらす。"""
    shifted: list[dict] = []
    for row in rows:
        source = int(row["source_index"])
        if source >= insert_at:
            source += 1
        shifted.append({**row, "source_index": source})
    return shifted


def _slot_for_source(source_index: int, files_per_slot: list[int]) -> int:
    remaining = source_index
    for slot, count in enumerate(files_per_slot):
        if remaining < count:
            return slot
        remaining -= count
    return max(0, len(files_per_slot) - 1)
