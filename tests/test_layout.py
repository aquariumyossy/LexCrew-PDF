"""配置ファイルと、カードからの生成計画。"""
import json
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import default_layout, layout_to_json, load_layout, parse_layout, save_layout, store_path
from lexcrew_pdf.plan import jobs_from_layout
from lexcrew_pdf.session import Session


def _pdf(path: Path, text: str = "PAGE") -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_default_layout_has_six_cards():
    layout = default_layout()
    assert layout.series == "甲"
    assert [card.number for card in layout.cards] == [1, 2, 3, 4, 5, 6]
    assert layout.enabled_series == ("甲", "乙", "丙")


def test_layout_round_trip(tmp_path):
    session = Session(tmp_path)
    session.set_title(2, "契約書")
    loaded = load_layout(tmp_path)
    assert loaded == session.layout
    assert loaded.cards[1].slots[0].title == "契約書"
    raw = json.loads((tmp_path / "証拠" / "layout.json").read_text(encoding="utf-8"))
    assert "title" not in raw["cards"][1]
    assert raw["cards"][1]["slots"][0]["title"] == "契約書"


def test_inside_path_is_relative_and_outside_path_is_absolute(tmp_path):
    inside = tmp_path / "inside.pdf"
    outside_dir = tmp_path.parent / f"outside-{tmp_path.name}"
    outside_dir.mkdir(exist_ok=True)
    outside = outside_dir / "outside.pdf"
    _pdf(inside)
    _pdf(outside)
    assert not Path(store_path(tmp_path, inside)).is_absolute()
    assert Path(store_path(tmp_path, outside)).is_absolute()


def test_parent_segment_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲", "乙", "丙"],
            "cards": [{
                "number": 1,
                "title": "",
                "slots": [{"files": ["..\\secret.pdf"]}],
            }],
            "lastWritten": [],
        })


def test_load_layout_does_not_open_pdfs(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: opened.append(args))
    save_layout(tmp_path, default_layout())
    load_layout(tmp_path)
    assert opened == []


def test_series_change_keeps_the_number(tmp_path):
    source = tmp_path / "lease.pdf"
    _pdf(source, "LEASE")
    session = Session(tmp_path)
    session.add_file(3, 0, str(source))
    session.set_series("乙")
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].stamp == "乙第３号証"
    assert built.jobs[0].number == 3


def test_empty_branch_stays_one_file(tmp_path):
    source = tmp_path / "lease.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(3, 0, str(source))
    session.add_branch(3)
    built = jobs_from_layout(session.layout, tmp_path)
    assert len(built.jobs) == 1
    assert built.jobs[0].filename == "甲003-1：lease.pdf"
    assert built.jobs[0].stamp == "甲第３号証の１"
    assert session.view()["cards"][2]["slots"][0]["filename"] == "甲003-1：lease.pdf"
    view = session.delete_slot(3, 1)
    card = next(item for item in view["cards"] if item["number"] == 3)
    assert len(card["slots"]) == 1
    assert card["slots"][0]["filename"] == "甲003：lease.pdf"


def test_filled_branch_becomes_two_files(tmp_path):
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, "BODY")
    _pdf(branch, "BRANCH")
    session = Session(tmp_path)
    session.add_file(4, 0, str(body))
    session.add_branch(4)
    session.add_file(4, 1, str(branch))
    built = jobs_from_layout(session.layout, tmp_path)
    assert len(built.jobs) == 2
    assert built.jobs[0].filename.startswith("甲004-1：")
    assert built.jobs[1].filename.startswith("甲004-2：")
    assert built.jobs[0].stamp == "甲第４号証の１"
    assert built.jobs[1].stamp == "甲第４号証の２"


def test_card_field_shows_the_output_filename(tmp_path):
    source = tmp_path / "賃貸借契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(4, 0, str(source))
    assert session.view()["cards"][3]["slots"][0]["filename"] == "甲004：賃貸借契約書.pdf"
    session.add_branch(4)
    session.add_file(4, 1, str(source))
    slots = session.view()["cards"][3]["slots"]
    assert slots[0]["filename"] == "甲004-1：賃貸借契約書.pdf"
    assert slots[1]["filename"] == "甲004-2：賃貸借契約書.pdf"


def test_blank_title_uses_the_file_stem(tmp_path):
    source = tmp_path / "住宅賃貸借契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].filename == "甲001：住宅賃貸借契約書.pdf"


def test_empty_card_is_skipped(tmp_path):
    source = tmp_path / "a.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.number for job in built.jobs] == [1]


def test_natural_pages_are_omitted_from_json(tmp_path):
    source = tmp_path / "a.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    raw = json.loads((tmp_path / "証拠" / "layout.json").read_text(encoding="utf-8"))
    assert "pages" not in raw["cards"][0]
    assert "rotation" not in raw["cards"][0]


def test_branch_filename_uses_that_slots_file(tmp_path):
    first = tmp_path / "5.建物評価証明書.pdf"
    second = tmp_path / "3.賃貸人会社謄本.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.set_series("乙")
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    slots = session.view()["cards"][0]["slots"]
    assert slots[0]["filename"] == "乙001-1：5.建物評価証明書.pdf"
    assert slots[1]["filename"] == "乙001-2：3.賃貸人会社謄本.pdf"
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == [
        "乙001-1：5.建物評価証明書.pdf",
        "乙001-2：3.賃貸人会社謄本.pdf",
    ]
    session.set_title(1, "手入力", 1)
    slots = session.view()["cards"][0]["slots"]
    assert slots[0]["filename"] == "乙001-1：5.建物評価証明書.pdf"
    assert slots[1]["filename"] == "乙001-2：手入力.pdf"
    session.set_title(1, "", 1)
    assert session.layout.cards[0].slots[1].title == ""
    assert session.view()["cards"][0]["slots"][1]["filename"] == "乙001-2：3.賃貸人会社謄本.pdf"


def test_a_later_file_on_the_same_slot_keeps_the_first_name(tmp_path):
    first = tmp_path / "先頭.pdf"
    second = tmp_path / "次.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    assert session.layout.cards[0].slots[0].title == ""
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001：先頭.pdf"


def test_blank_title_follows_a_replaced_file_and_a_typed_title_stays(tmp_path):
    first = tmp_path / "古い.pdf"
    second = tmp_path / "新しい.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.replace_slot(1, 0, [str(second)])
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001：新しい.pdf"
    session.set_title(1, "固定")
    session.replace_slot(1, 0, [str(first)])
    assert session.layout.cards[0].slots[0].title == "固定"
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001：固定.pdf"


def test_legacy_card_title_copies_only_onto_slots_without_a_title(tmp_path):
    kept = tmp_path / "残す.pdf"
    added = tmp_path / "足した.pdf"
    _pdf(kept)
    _pdf(added)
    evidence = tmp_path / "証拠"
    evidence.mkdir()
    (evidence / "layout.json").write_text(
        json.dumps({
            "series": "甲",
            "labelTemplate": "甲第N号証",
            "enabledSeries": ["甲", "乙", "丙"],
            "cards": [{
                "number": 1,
                "title": "契約書",
                "slots": [
                    {"files": ["残す.pdf"]},
                    {"files": ["残す.pdf"], "title": ""},
                ],
            }],
            "lastWritten": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    session = Session(tmp_path)
    assert session.layout.cards[0].slots[0].title == "契約書"
    assert session.layout.cards[0].slots[1].title == ""
    slots = session.view()["cards"][0]["slots"]
    assert slots[0]["filename"] == "甲001-1：契約書.pdf"
    assert slots[1]["filename"] == "甲001-2：残す.pdf"
    session.add_branch(1)
    session.add_file(1, 2, str(added))
    slots = session.view()["cards"][0]["slots"]
    assert session.layout.cards[0].slots[2].title == ""
    assert slots[0]["filename"] == "甲001-1：契約書.pdf"
    assert slots[2]["filename"] == "甲001-3：足した.pdf"
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == [
        "甲001-1：契約書.pdf",
        "甲001-2：残す.pdf",
        "甲001-3：足した.pdf",
    ]


def test_set_title_rejects_a_missing_slot(tmp_path):
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="証拠の番号が不正です。"):
        session.set_title(1, "書名", 2)


def test_unreadable_branch_preserves_each_slots_filename(tmp_path):
    broken = tmp_path / "壊れ.pdf"
    other = tmp_path / "別.pdf"
    broken.write_bytes(b"not a pdf")
    _pdf(other)
    session = Session(tmp_path)
    session.add_file(1, 0, str(broken))
    session.add_branch(1)
    session.add_file(1, 1, str(other))
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs == ()
    assert built.preserve == ("甲001-1：壊れ.pdf", "甲001-2：別.pdf")


def test_branch_rotation_stays_on_that_slot(tmp_path):
    first = tmp_path / "の1.pdf"
    second = tmp_path / "の2.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    session.rotate(1, 0)
    slots = session.layout.cards[0].slots
    assert slots[0].rotation == 90
    assert slots[1].rotation == 0
    view = session.view()["cards"][0]["slots"]
    assert view[0]["rotation"] == 90
    assert view[1]["rotation"] == 0
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.rotation for job in built.jobs] == [90, 0]
    session.rotate(1, 1)
    assert session.layout.cards[0].slots[0].rotation == 90
    assert session.layout.cards[0].slots[1].rotation == 90
    session.add_branch(1)
    assert session.layout.cards[0].slots[2].rotation == 0
    session.set_title(1, "固定", 0)
    session.replace_slot(1, 0, [str(second)])
    assert session.layout.cards[0].slots[0].rotation == 90
    session.begin_edit(1, 1)
    assert session.edit_context()["rotation"] == 90
    session.finish_edit()


def test_legacy_card_rotation_copies_only_when_the_slot_has_no_key():
    layout = parse_layout({
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{
            "number": 1,
            "rotation": 90,
            "slots": [
                {"files": ["a.pdf"], "title": ""},
                {"files": ["b.pdf"], "title": "", "rotation": 0},
            ],
        }],
        "lastWritten": [],
    })
    assert layout.cards[0].slots[0].rotation == 90
    assert layout.cards[0].slots[1].rotation == 0


def test_zero_rotation_is_omitted_after_a_full_turn(tmp_path):
    session = Session(tmp_path)
    for _ in range(4):
        session.rotate(1)
    dumped = layout_to_json(session.layout)
    assert "rotation" not in dumped["cards"][0]
    assert "rotation" not in dumped["cards"][0]["slots"][0]
    assert session.layout.cards[0].slots[0].rotation == 0
