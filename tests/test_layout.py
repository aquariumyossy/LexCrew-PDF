"""配置ファイルと、カードからの生成計画。"""
import json
import os
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import (
    default_layout,
    layout_to_json,
    load_layout,
    parse_layout,
    save_layout,
    store_path,
    with_next_series,
    with_series,
)
from lexcrew_pdf.plan import jobs_from_layout
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import DEFAULT_STAMP, color_hex, stamp_frame, stamp_sources_to_pdf, yu_mincho_path
from lexcrew_pdf.write import write_jobs


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
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
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
    assert built.jobs[0].filename == "甲003-1 lease.pdf"
    assert built.jobs[0].stamp == "甲第３号証の１"
    assert session.view()["cards"][2]["slots"][0]["filename"] == "甲003-1 lease.pdf"
    view = session.delete_slot(3, 1)
    card = next(item for item in view["cards"] if item["number"] == 3)
    assert len(card["slots"]) == 1
    assert card["slots"][0]["filename"] == "甲003 lease.pdf"


def test_filled_branch_becomes_two_files(tmp_path):
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, "BODY")
    _pdf(branch, "BRANCH")
    session = Session(tmp_path)
    session.set_merge_branches(False)
    session.add_file(4, 0, str(body))
    session.add_branch(4)
    session.add_file(4, 1, str(branch))
    built = jobs_from_layout(session.layout, tmp_path)
    assert len(built.jobs) == 2
    assert built.jobs[0].filename.startswith("甲004-1 ")
    assert built.jobs[1].filename.startswith("甲004-2 ")
    assert built.jobs[0].stamp == "甲第４号証の１"
    assert built.jobs[1].stamp == "甲第４号証の２"


def test_card_field_shows_the_output_filename(tmp_path):
    source = tmp_path / "賃貸借契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(4, 0, str(source))
    assert session.view()["cards"][3]["slots"][0]["filename"] == "甲004 賃貸借契約書.pdf"
    session.add_branch(4)
    session.add_file(4, 1, str(source))
    slots = session.view()["cards"][3]["slots"]
    assert slots[0]["filename"] == "甲004-1~2 賃貸借契約書.pdf"
    assert slots[1]["filename"] == "甲004-1~2 賃貸借契約書.pdf"
    assert slots[0]["outputNote"] == "→ 甲004-1~2 に含めて出力"
    assert slots[1]["outputNote"] == "→ 甲004-1~2 に含めて出力"


def test_blank_title_uses_the_file_stem(tmp_path):
    source = tmp_path / "住宅賃貸借契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].filename == "甲001 住宅賃貸借契約書.pdf"


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
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
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
    assert slots[0]["filename"] == "乙001-1~2 5.建物評価証明書.pdf"
    assert slots[1]["filename"] == "乙001-1~2 5.建物評価証明書.pdf"
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].filename == "乙001-1~2 5.建物評価証明書.pdf"
    assert [part.title for part in built.jobs[0].parts] == ["5.建物評価証明書", "3.賃貸人会社謄本"]
    session.set_title(1, "手入力", 1)
    slots = session.view()["cards"][0]["slots"]
    assert slots[0]["filename"] == "乙001-1~2 5.建物評価証明書.pdf"
    assert slots[1]["title"] == "手入力"
    session.set_merge_branches(False)
    slots = session.view()["cards"][0]["slots"]
    assert slots[0]["filename"] == "乙001-1 5.建物評価証明書.pdf"
    assert slots[1]["filename"] == "乙001-2 手入力.pdf"
    session.set_title(1, "", 1)
    assert session.layout.cards[0].slots[1].title == ""
    assert session.view()["cards"][0]["slots"][1]["filename"] == "乙001-2 3.賃貸人会社謄本.pdf"


def test_a_later_file_on_the_same_slot_keeps_the_first_name(tmp_path):
    first = tmp_path / "先頭.pdf"
    second = tmp_path / "次.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    assert session.layout.cards[0].slots[0].title == ""
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001 先頭.pdf"


def test_blank_title_follows_a_replaced_file_and_a_typed_title_stays(tmp_path):
    first = tmp_path / "古い.pdf"
    second = tmp_path / "新しい.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.replace_slot(1, 0, [str(second)])
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001 新しい.pdf"
    session.set_title(1, "固定")
    session.replace_slot(1, 0, [str(first)])
    assert session.layout.cards[0].slots[0].title == "固定"
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001 固定.pdf"


def test_legacy_card_title_copies_only_onto_slots_without_a_title(tmp_path):
    kept = tmp_path / "残す.pdf"
    added = tmp_path / "足した.pdf"
    _pdf(kept)
    _pdf(added)
    evidence = tmp_path / "LexCrew-PDF-Downloads"
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
    assert slots[0]["filename"] == "甲001-1~2 契約書.pdf"
    assert slots[1]["filename"] == "甲001-1~2 契約書.pdf"
    session.add_branch(1)
    session.add_file(1, 2, str(added))
    slots = session.view()["cards"][0]["slots"]
    assert session.layout.cards[0].slots[2].title == ""
    assert slots[0]["filename"] == "甲001-1~3 契約書.pdf"
    assert slots[2]["filename"] == "甲001-1~3 契約書.pdf"
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].filename == "甲001-1~3 契約書.pdf"
    assert [part.title for part in built.jobs[0].parts] == ["契約書", "残す", "足した"]


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
    assert built.preserve == ("甲001-1~2 壊れ.pdf",)
    session.set_merge_branches(False)
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.preserve == ("甲001-1 壊れ.pdf", "甲001-2 別.pdf")


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
    assert [part.rotation for part in built.jobs[0].parts] == [90, 0]
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


def test_grayscale_is_omitted_when_off_and_kept_across_series(tmp_path, monkeypatch):
    assert default_layout().grayscale is False
    assert "grayscale" not in layout_to_json(default_layout())
    missing = {
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
        "lastWritten": [],
    }
    assert parse_layout(missing).grayscale is False
    saved = replace(default_layout(), grayscale=True)
    dumped = layout_to_json(saved)
    assert dumped["grayscale"] is True
    assert parse_layout(dumped).grayscale is True
    assert with_series(saved, "乙").grayscale is True
    assert with_next_series(saved).grayscale is True
    save_layout(tmp_path, saved)
    assert load_layout(tmp_path).grayscale is True
    with pytest.raises(ValueError):
        parse_layout({**missing, "grayscale": "yes"})

    source = tmp_path / "a.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    assert session.set_grayscale(True)["grayscale"] is True
    assert load_layout(tmp_path).grayscale is True
    session.set_series("乙")
    assert session.layout.grayscale is True
    seen = {}

    def fake_write(folder, jobs, *, last_written, preserve=(), grayscale=False, style=None):
        seen["grayscale"] = grayscale
        name = jobs[0].filename
        return {"written": [{"filename": name, "stampLabel": jobs[0].stamp}], "errors": [], "keep": (name,)}

    monkeypatch.setattr("lexcrew_pdf.write.write_jobs", fake_write)
    session.generate()
    assert seen["grayscale"] is True
    assert session.layout.grayscale is True
    session.set_grayscale(False)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "grayscale" not in raw


def test_stamp_style_is_omitted_when_default_and_survives_series_changes(tmp_path, monkeypatch):
    assert "stamp" not in layout_to_json(default_layout())
    missing = {
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
        "lastWritten": [],
    }
    assert parse_layout(missing).stamp == DEFAULT_STAMP
    uppercase = parse_layout({**missing, "stamp": {"color": "#FF0000"}})
    assert uppercase.stamp == DEFAULT_STAMP
    assert "stamp" not in layout_to_json(uppercase)
    green = parse_layout({**missing, "stamp": {"color": "#008000"}})
    assert layout_to_json(green)["stamp"]["color"] == "#008000"
    black = parse_layout({**missing, "stamp": {"color": "#000000"}})
    assert color_hex(black.stamp.color) == "#000000"
    partial = parse_layout({**missing, "stamp": {"size": 16.0}})
    assert (partial.stamp.size, partial.stamp.font) == (16, "mincho")
    assert layout_to_json(partial)["stamp"] == {"color": "#ff0000", "size": 16, "font": "mincho"}
    blue = parse_layout({**missing, "stamp": {"color": "#0000ff", "size": 18, "font": "gothic"}})
    assert with_series(blue, "乙").stamp == blue.stamp
    assert with_next_series(blue).stamp.font == "gothic"
    for broken in (
        {"stamp": "red"},
        {"stamp": {"color": "red"}},
        {"stamp": {"color": "#112233"}},
        {"stamp": {"size": True}},
        {"stamp": {"size": 7}},
        {"stamp": {"font": "comic"}},
    ):
        with pytest.raises(ValueError, match="配置ファイルを読めません。"):
            parse_layout({**missing, **broken})
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")
    source = tmp_path / "a.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_stamp_offset(1, 0, -40, 55)
    view = session.set_stamp_style("#0000ff", 18, "mincho")
    assert view["stamp"] == {"color": "#0000ff", "size": 18, "font": "mincho"}
    assert session.layout.cards[0].slots[0].stamp_dx == -40
    assert load_layout(tmp_path).stamp.size == 18
    session.set_series("乙")
    session.set_grayscale(True)
    assert session.layout.stamp.size == 18
    assert session.layout.grayscale is True
    seen = {}

    def fake_write(folder, jobs, *, last_written, preserve=(), grayscale=False, style=None):
        seen["style"] = style
        name = jobs[0].filename
        return {"written": [{"filename": name, "stampLabel": jobs[0].stamp}], "errors": [], "keep": (name,)}

    monkeypatch.setattr("lexcrew_pdf.write.write_jobs", fake_write)
    session.generate()
    assert seen["style"].size == 18
    assert session.layout.stamp.font == "mincho"
    session.set_stamp_style("#ff0000", 11, "mincho")
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "stamp" not in raw
    session.set_stamp_style("#0000ff", 16.0, "mincho")
    session.clear()
    assert session.layout.stamp == DEFAULT_STAMP


def test_zero_rotation_is_omitted_after_a_full_turn(tmp_path):
    session = Session(tmp_path)
    for _ in range(4):
        session.rotate(1)
    dumped = layout_to_json(session.layout)
    assert "rotation" not in dumped["cards"][0]
    assert "rotation" not in dumped["cards"][0]["slots"][0]
    assert session.layout.cards[0].slots[0].rotation == 0


def _card_layout(**slot):
    return {
        "series": "甲",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [slot]}],
        "lastWritten": [],
    }


def test_missing_stamp_offset_stays_at_the_origin():
    layout = parse_layout(_card_layout(files=[], title=""))
    assert layout.cards[0].slots[0].stamp_dx == 0
    assert layout.cards[0].slots[0].stamp_dy == 0
    assert "stampDx" not in layout_to_json(layout)["cards"][0]["slots"][0]


def test_stamp_offset_in_the_layout_must_be_an_integer():
    with pytest.raises(ValueError, match="配置ファイルを読めません"):
        parse_layout(_card_layout(files=[], title="", stampDx=1.5, stampDy=0))


def test_stamp_offset_stays_on_its_slot_and_on_the_first_page(tmp_path):
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")
    source = tmp_path / "a.pdf"
    other = tmp_path / "b.pdf"
    document = fitz.open()
    document.new_page(width=595, height=842)
    document.new_page(width=595, height=842)
    document.save(source)
    document.close()
    _pdf(other)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    saved = session.set_stamp_offset(1, 0, -40, 55)
    assert (saved["dx"], saved["dy"]) == (-40, 55)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["cards"][0]["slots"][0]["stampDx"] == -40
    assert raw["cards"][0]["slots"][0]["stampDy"] == 55
    job = jobs_from_layout(session.layout, tmp_path).jobs[0]
    assert (job.stamp_dx, job.stamp_dy) == (-40, 55)
    session.set_title(1, "契約")
    session.rotate(1, 0)
    session.add_file(1, 0, str(other))
    session.replace_file(1, 0, 0, str(other))
    assert (session.layout.cards[0].slots[0].stamp_dx, session.layout.cards[0].slots[0].stamp_dy) == (-40, 55)
    session.add_branch(1)
    assert session.layout.cards[0].slots[1].stamp_dx == 0
    session.reset_pages(1, 0)
    assert session.layout.cards[0].slots[0].stamp_dx == -40
    session.begin_edit(1, 0)
    frame = session.edit_context()["stampFrame"]
    assert (frame["dx"], frame["dy"]) == (-40, 55)
    moved = session.preview(1, 0, 0)
    session.set_stamp_offset(1, 0, 0, 0)
    parked = session.preview(1, 0, 0)
    bare = session.preview(1, 0, 0, bare=True)
    assert moved["image"] != parked["image"]
    assert bare["image"] != parked["image"]
    session.set_stamp_offset(1, 0, -40, 55)
    written = write_jobs(tmp_path, jobs_from_layout(session.layout, tmp_path).jobs, last_written=())
    opened = fitz.open(tmp_path / "LexCrew-PDF-Downloads" / written["written"][0]["filename"])
    try:
        rect = _red_rect(opened[0])
        fresh = stamp_frame(-40, 55)
        assert abs(rect.x0 - fresh["x"]) < 0.2
        assert abs(rect.y0 - fresh["y"]) < 0.2
        assert _red_rect(opened[1], missing=True) is None
    finally:
        opened.close()
    shoved = session.set_stamp_offset(1, 0, 5000, -5000)
    assert shoved["dx"] != 5000
    assert shoved["dy"] != -5000
    assert shoved["stampFrame"]["dx"] == shoved["dx"]
    session.set_stamp_offset(1, 0, 0, 0)
    cleared = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "stampDx" not in cleared["cards"][0]["slots"][0]
    assert "stampDy" not in cleared["cards"][0]["slots"][0]


def test_empty_cards_omit_masks_and_a_mask_round_trips(tmp_path):
    assert "masks" not in layout_to_json(default_layout())["cards"][0]
    source = tmp_path / "secret.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 120), "SECRET")
    page.insert_text((72, 240), "VISIBLE")
    document.save(source)
    document.close()
    opened = fitz.open(source)
    try:
        word = [item for item in opened[0].get_text("words") if item[4] == "SECRET"][0]
    finally:
        opened.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    added = session.add_mask(1, 0, 0, 0, 0, word[0], word[1], word[2] - word[0], word[3] - word[1])
    assert added["masks"][0]["source"] == 0
    assert added["masks"][0]["part"] == 0
    session.set_pages(1, [{"source": 0, "page": 0, "part": 0, "group": 1}])
    assert len(session.layout.cards[0].masks) == 1
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["cards"][0]["masks"][0]["page"] == 0
    assert load_layout(tmp_path).cards[0].masks == session.layout.cards[0].masks
    stored = session.layout.cards[0].masks[0]
    assert session.remove_mask(1, 0, stored.source, stored.page, stored.x, stored.y, stored.w, stored.h)["masks"] == []
    assert session.remove_mask(1, 0, stored.source, stored.page, stored.x, stored.y, stored.w, stored.h)["masks"] == []
    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲"],
            "cards": [{
                "number": 1,
                "slots": [{"files": [], "title": ""}],
                "masks": [{"source": 0, "page": 0, "x": 1, "y": 1, "w": 0, "h": 4}],
            }],
            "lastWritten": [],
        })


def test_empty_cards_omit_trims_and_a_trim_round_trips(tmp_path):
    assert "trims" not in layout_to_json(default_layout())["cards"][0]
    source = tmp_path / "body.pdf"
    _pdf(source, "BODY")
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    saved = session.set_trim(1, 0, 0, 0, 0, 200, 0, 0, 0)
    assert saved["trim"] == {"top": 200, "right": 0, "bottom": 0, "left": 0}
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["cards"][0]["trims"][0] == {
        "source": 0, "page": 0, "part": 0, "top": 200, "right": 0, "bottom": 0, "left": 0,
    }
    assert load_layout(tmp_path).cards[0].trims == session.layout.cards[0].trims
    cleared = session.set_trim(1, 0, 0, 0, 0, 0, 0, 0, 0)
    assert cleared["trim"] == {"top": 0, "right": 0, "bottom": 0, "left": 0}
    assert session.layout.cards[0].trims == ()
    stored = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "trims" not in stored["cards"][0]
    with pytest.raises(ValueError):
        session.set_trim(1, 0, 0, 3, 0, 10, 0, 0, 0)
    with pytest.raises(ValueError):
        session.set_trim(1, 0, 0, 0, 0, 401, 0, 0, 0)
    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲"],
            "cards": [{
                "number": 1,
                "slots": [{"files": [], "title": ""}],
                "trims": [
                    {"source": 0, "page": 0, "part": 0, "top": 10, "right": 0, "bottom": 0, "left": 0},
                    {"source": 0, "page": 0, "part": 0, "top": 20, "right": 0, "bottom": 0, "left": 0},
                ],
            }],
            "lastWritten": [],
        })
    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲"],
            "cards": [{
                "number": 1,
                "slots": [{"files": [], "title": ""}],
                "trims": [{"source": 0, "page": 0, "part": 0, "top": 0, "right": 0, "bottom": 0, "left": 0}],
            }],
            "lastWritten": [],
        })


def test_trim_follows_a_new_file_drops_on_replace_and_survives_reorder(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _pdf(first, "FIRST")
    document = fitz.open()
    document.new_page(width=595, height=842).insert_text((72, 72), "A")
    document.new_page(width=595, height=842).insert_text((72, 72), "B")
    document.save(second)
    document.close()
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 1, str(first))
    session.set_trim(1, 1, 0, 0, 0, 80, 0, 0, 0)
    assert session.layout.cards[0].trims[0].source == 0
    session.add_file(1, 0, str(second))
    assert session.layout.cards[0].trims[0].source == 1
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ], 0)
    assert session.layout.cards[0].trims[0].top == 80
    assert session.layout.cards[0].trims[0].source == 1
    session.rotate(1, 1)
    assert session.layout.cards[0].trims[0].top == 80
    session.replace_file(1, 1, 0, str(second))
    assert session.layout.cards[0].trims == ()


def test_pulling_a_branch_keeps_its_trim(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _pdf(first, "FIRST")
    _pdf(second, "SECOND")
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(first))
    session.add_file(1, 1, str(second))
    session.set_trim(1, 1, 1, 0, 0, 40, 0, 0, 0)
    session.move_slot(1, 1, None)
    kept = [card for card in session.layout.cards if card.trims]
    assert session.layout.cards[0].trims == ()
    assert len(kept) == 1
    assert kept[0].number == 7
    assert kept[0].trims[0].source == 0
    assert kept[0].trims[0].top == 40


def test_split_clears_trims_and_the_editor_reports_the_image_box(tmp_path):
    source = tmp_path / "body.pdf"
    _pdf(source, "BODY")
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_trim(1, 0, 0, 0, 0, 120, 0, 0, 0)
    editor = session.editor(1, 0)
    page = editor["columns"][0]["pages"][0]
    assert page["trim"]["top"] == 120
    assert page["imageBox"]["w"] > 0.9
    assert page["imageBox"]["h"] > 0.9
    session.set_split(1, True)
    assert session.layout.cards[0].trims == ()
    assert session.layout.cards[0].pages is None


def test_generate_drops_the_trimmed_edge(tmp_path):
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")
    source = tmp_path / "marked.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 36), "EDGE")
    page.insert_text((72, 420), "BODY")
    document.save(source)
    document.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_trim(1, 0, 0, 0, 0, 200, 0, 0, 0)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert len(written) == 1
    produced = fitz.open(written[0])
    try:
        text = produced[0].get_text("text")
        assert "EDGE" not in text
        assert "BODY" in text
        assert "甲第１号証" in text
    finally:
        produced.close()


def test_empty_cards_omit_skews_and_a_skew_round_trips(tmp_path):
    assert "skews" not in layout_to_json(default_layout())["cards"][0]
    source = tmp_path / "body.pdf"
    _pdf(source, "BODY")
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    saved = session.set_skew(1, 0, 0, 0, 40)
    assert saved["skewTenths"] == 40
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["cards"][0]["skews"] == [{"source": 0, "page": 0, "tenths": 40}]
    assert load_layout(tmp_path).cards[0].skews == session.layout.cards[0].skews
    cleared = session.set_skew(1, 0, 0, 0, 0)
    assert cleared["skewTenths"] == 0
    assert session.layout.cards[0].skews == ()
    stored = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "skews" not in stored["cards"][0]
    with pytest.raises(ValueError):
        session.set_skew(1, 0, 0, 0, 101)
    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲"],
            "cards": [{
                "number": 1,
                "slots": [{"files": [], "title": ""}],
                "skews": [
                    {"source": 0, "page": 0, "tenths": 10},
                    {"source": 0, "page": 0, "tenths": 20},
                ],
            }],
            "lastWritten": [],
        })
    with pytest.raises(ValueError):
        parse_layout({
            "series": "甲",
            "enabledSeries": ["甲"],
            "cards": [{
                "number": 1,
                "slots": [{"files": [], "title": ""}],
                "skews": [{"source": 0, "page": 0, "tenths": 0}],
            }],
            "lastWritten": [],
        })


def test_split_halves_report_the_same_skew(tmp_path):
    source = tmp_path / "spread.pdf"
    document = fitz.open()
    page = document.new_page(width=1191, height=842)
    page.insert_text((40, 80), "LEFTSIDE")
    page.insert_text((1191 - 160, 80), "RIGHTSIDE")
    document.save(source)
    document.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_split(1, True)
    session.set_skew(1, 0, 0, 0, 25)
    pages = session.editor(1, 0)["columns"][0]["pages"]
    assert [row["part"] for row in pages] == [1, 2]
    assert [row["skewTenths"] for row in pages] == [25, 25]
    assert len(session.layout.cards[0].skews) == 1


def test_saved_skew_stays_on_reset_and_clears_when_split(tmp_path):
    source = tmp_path / "two.pdf"
    document = fitz.open()
    document.new_page(width=595, height=842).insert_text((72, 72), "A")
    document.new_page(width=595, height=842).insert_text((72, 72), "B")
    document.save(source)
    document.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_skew(1, 0, 0, 0, 40)
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ])
    session.reset_pages(1, 0)
    assert session.layout.cards[0].skews[0].tenths == 40
    session.set_split(1, True)
    assert session.layout.cards[0].skews == ()


def test_skew_follows_a_new_file_and_drops_on_replace(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _pdf(first, "FIRST")
    _pdf(second, "SECOND")
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 1, str(first))
    session.set_skew(1, 1, 0, 0, 30)
    assert session.layout.cards[0].skews[0].source == 0
    session.add_file(1, 0, str(second))
    assert session.layout.cards[0].skews[0].source == 1
    assert session.layout.cards[0].skews[0].tenths == 30
    session.replace_file(1, 1, 0, str(first))
    assert session.layout.cards[0].skews == ()


def test_generate_skews_the_page_and_leaves_the_stamp(tmp_path):
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")
    source = tmp_path / "marked.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((260, 48), "TOPMARK")
    page.insert_text((260, 420), "BODY")
    document.save(source)
    document.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_skew(1, 0, 0, 0, 50)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert len(written) == 1
    straight = fitz.open(stream=stamp_sources_to_pdf([str(source)], "甲第１号証"), filetype="pdf")
    produced = fitz.open(written[0])
    try:
        assert "TOPMARK" in produced[0].get_text("text")
        assert "甲第１号証" in produced[0].get_text("text")
        before = [item for item in straight[0].get_text("words") if item[4] == "TOPMARK"][0]
        after = [item for item in produced[0].get_text("words") if item[4] == "TOPMARK"][0]
        assert after[0] > before[0] + 2
    finally:
        straight.close()
        produced.close()


def test_mask_follows_a_new_file_and_drops_when_that_file_is_replaced(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _pdf(first, "FIRST")
    _pdf(second, "SECOND")
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 1, str(first))
    session.add_mask(1, 1, 0, 0, 0, 60, 40, 120, 40)
    assert session.layout.cards[0].masks[0].source == 0
    session.add_file(1, 0, str(second))
    assert session.layout.cards[0].masks[0].source == 1
    session.replace_file(1, 1, 0, str(second))
    assert session.layout.cards[0].masks == ()


def test_generate_burns_a_mask_and_skips_a_missing_page(tmp_path):
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")
    source = tmp_path / "secret.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 120), "SECRET")
    page.insert_text((72, 240), "VISIBLE")
    document.save(source)
    document.close()
    opened = fitz.open(source)
    try:
        word = [item for item in opened[0].get_text("words") if item[4] == "SECRET"][0]
    finally:
        opened.close()
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.add_mask(1, 0, 0, 0, 0, word[0], word[1], word[2] - word[0], word[3] - word[1])
    from lexcrew_pdf.layout import Mask
    from dataclasses import replace as replace_card

    card = session.layout.cards[0]
    session._put(replace_card(card, masks=card.masks + (Mask(0, 99, 0, 0, 10, 10),)))
    before = source.read_bytes()
    result = session.generate()
    assert result["ok"] is True
    assert source.read_bytes() == before
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert len(written) == 1
    produced = fitz.open(written[0])
    try:
        text = produced[0].get_text("text")
        assert "SECRET" not in text
        assert "VISIBLE" in text
        assert "甲第１号証" in text
    finally:
        produced.close()


def _red_rect(page, missing=False):
    found = []
    for drawing in page.get_drawings():
        color = drawing.get("color")
        if color and len(color) >= 3 and color[0] > 0.8 and color[1] < 0.2 and color[2] < 0.2:
            found.append(drawing["rect"])
    if missing:
        assert found == []
        return None
    assert len(found) == 1
    return found[0]
