"""ページ順。通知書の固定書名は出さない。"""
import pytest

from lexcrew_pdf.pages import (
    arrange_pages,
    resolve_buckets,
    validate_page_assignment,
)


def _row(page, group, position, source=0, part=0):
    return {
        "source_index": source,
        "page_index": page,
        "part": part,
        "group_index": group,
        "position": position,
    }


def test_new_pages_append_to_the_primary_group_and_stale_refs_drop():
    buckets = arrange_pages(
        [(0, 0, 0), (0, 1, 0), (0, 2, 0)],
        [_row(1, 1, 0), _row(9, 1, 1), _row(0, 0, 2)],
        max_group=2,
    )
    assert buckets[1] == [(0, 1, 0), (0, 2, 0)]
    assert buckets[0] == [(0, 0, 0)]
    assert buckets[2] == []


def test_a_plan_that_excludes_every_page_is_ignored():
    natural = [(0, 0, 0), (0, 1, 0)]
    buckets = resolve_buckets(natural, [_row(0, 0, 0), _row(1, 0, 1)], [1])
    assert buckets[1] == natural
    assert buckets[0] == []


def test_group_four_keeps_a_page_and_empty_middle_groups_do_not():
    natural = [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)]
    rows = [
        _row(0, 1, 0),
        _row(1, 4, 1),
        _row(2, 1, 2),
        _row(3, 1, 3),
    ]
    buckets = arrange_pages(natural, rows, max_group=4)
    assert buckets[4] == [(0, 1, 0)]
    assert buckets[2] == []
    assert buckets[3] == []
    assert (0, 1, 0) not in buckets[1]


def test_empty_body_is_rejected():
    natural = [(0, 0, 0), (0, 1, 0)]
    submitted = [
        {"source": 0, "page": 0, "part": 0, "group": 2},
        {"source": 0, "page": 1, "part": 0, "group": 2},
    ]
    with pytest.raises(ValueError, match="出すページは1枚残してください"):
        validate_page_assignment(natural, submitted, max_group=2)


def test_empty_branch_group_is_allowed():
    natural = [(0, 0, 0), (0, 1, 0)]
    submitted = [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 1},
    ]
    stored = validate_page_assignment(natural, submitted, max_group=3)
    assert all(row["group_index"] == 1 for row in stored)


def test_reorder_is_accepted():
    natural = [(0, 0, 0), (0, 1, 0)]
    submitted = [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ]
    stored = validate_page_assignment(natural, submitted, max_group=1)
    assert [(row["page_index"], row["position"]) for row in stored] == [(1, 0), (0, 1)]
