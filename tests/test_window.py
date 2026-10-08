"""窓が呼ぶ Python API。ブラウザは使わない。"""
import base64
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import PageRow
from lexcrew_pdf.session import Session, _replace, downloads_dir
from lexcrew_pdf.stamp import yu_mincho_path
from lexcrew_pdf import window as app_window


def _pdf(path: Path, pages=("ONE", "TWO")) -> None:
    document = fitz.open()
    for text in pages:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _require_font():
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")


def test_default_view_has_six_cards_and_opens_no_pdf(monkeypatch):
    opened = []
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: opened.append(args))
    view = Session().view()
    assert [card["number"] for card in view["cards"]] == [1, 2, 3, 4, 5, 6]
    assert view["cards"][0]["label"] == "甲第１号証"
    assert opened == []


def test_plus_adds_the_next_number():
    session = Session()
    view = session.add_card()
    assert [card["number"] for card in view["cards"]][-1] == 7


def test_series_changes_every_card():
    session = Session()
    view = session.set_series("乙")
    assert all(card["label"].startswith("乙") for card in view["cards"])
    assert view["cards"][5]["number"] == 6


def test_custom_template_numbers_the_cards(tmp_path):
    session = Session(tmp_path)
    view = session.set_series("資料N")
    assert [card["label"] for card in view["cards"][:3]] == ["資料１", "資料２", "資料３"]
    assert view["cards"][0]["slots"][0]["filename"].startswith("資料001：")
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("BODY",))
    _pdf(branch, ("BRANCH",))
    session.add_file(1, 0, str(body))
    session.add_branch(1)
    session.add_file(1, 1, str(branch))
    card = session.view()["cards"][0]
    assert [slot["label"] for slot in card["slots"]] == ["資料１の１", "資料１の２"]
    assert card["slots"][0]["filename"].startswith("資料001-1：")
    assert card["slots"][1]["filename"].startswith("資料001-2：")


def test_branch_relabels_the_body():
    session = Session()
    view = session.add_branch(3)
    card = next(item for item in view["cards"] if item["number"] == 3)
    assert card["label"] == "甲第３号証の１"
    assert card["slots"][1]["label"] == "甲第３号証の２"


def test_a_file_dropped_once_can_be_dropped_again(tmp_path):
    from lexcrew_pdf.window import resolve_dropped_paths

    pdf = tmp_path / "same.pdf"
    _pdf(pdf, ("A",))
    cache = {}
    first, cache = resolve_dropped_paths(
        [{"name": "same.pdf", "pywebviewFullPath": str(pdf)}],
        [],
        cache,
    )
    assert first == [str(pdf)]
    second, cache = resolve_dropped_paths([{"name": "same.pdf"}], [], cache)
    assert second == [str(pdf)]


def test_button_appends_and_drop_on_a_file_replaces(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    third = tmp_path / "third.pdf"
    _pdf(first, ("A",))
    _pdf(second, ("B",))
    _pdf(third, ("C",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.drop_files(1, 0, None, [str(second)])
    assert [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]] == ["first.pdf", "second.pdf"]
    session.drop_files(1, 0, 0, [str(third)])
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["third.pdf", "second.pdf"]
    replacement = tmp_path / "replacement.pdf"
    _pdf(replacement, ("D",))
    session.drop_files(1, 0, None, [str(replacement)], replace=True)
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["replacement.pdf"]
    assert session.layout.cards[0].pages is None


def test_non_pdf_is_rejected(tmp_path):
    note = tmp_path / "memo.txt"
    note.write_text("no", encoding="utf-8")
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="PDFを選んでください"):
        session.add_file(1, 0, str(note))


def test_generate_skips_empty_cards(tmp_path):
    _require_font()
    source = tmp_path / "契約書.pdf"
    _pdf(source, ("BODY",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    result = session.generate()
    written = list((tmp_path / "証拠").glob("*.pdf"))
    assert len(written) == 1
    assert written[0].name.startswith("甲001：")
    assert result["ok"] is True


def test_reload_restores_cards(tmp_path):
    source = tmp_path / "契約書.pdf"
    _pdf(source, ("BODY",))
    session = Session(tmp_path)
    session.add_file(2, 0, str(source))
    session.set_title(2, "賃貸借")
    session.rotate(2)
    loaded = Session(tmp_path).view()
    card = next(item for item in loaded["cards"] if item["number"] == 2)
    assert card["slots"][0]["title"] == "賃貸借"
    assert card["title"] == "賃貸借"
    assert card["rotation"] == 90
    assert card["slots"][0]["files"][0]["name"] == "契約書.pdf"


def test_page_edit_changes_generate_order(tmp_path):
    _require_font()
    source = tmp_path / "two.pdf"
    _pdf(source, ("FIRSTPAGE", "SECONDPAGE"))
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 0},
    ])
    session.generate()
    document = fitz.open(tmp_path / "証拠" / "甲001：two.pdf")
    try:
        assert "SECONDPAGE" in document[0].get_text("text")
        assert document.page_count == 1
    finally:
        document.close()


def test_replace_clears_pages_and_add_keeps_them(tmp_path):
    first = tmp_path / "first.pdf"
    extra = tmp_path / "extra.pdf"
    replacement = tmp_path / "replacement.pdf"
    _pdf(first, ("A", "B"))
    _pdf(extra, ("C",))
    _pdf(replacement, ("D", "E"))
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ])
    assert session.layout.cards[0].pages is not None
    session.add_file(1, 0, str(extra))
    assert session.layout.cards[0].pages is not None
    session.replace_file(1, 0, 0, str(replacement))
    assert session.layout.cards[0].pages is None


def test_split_toggle_resets_only_when_the_value_changes(tmp_path):
    source = tmp_path / "a.pdf"
    _pdf(source, ("A", "B"))
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ])
    session.set_split(1, False)
    assert session.layout.cards[0].pages is not None
    session.set_split(1, True)
    assert session.layout.cards[0].pages is None


def test_missing_font_on_generate_keeps_previous_output(tmp_path, monkeypatch):
    source = tmp_path / "a.pdf"
    _pdf(source, ("A",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    dest = tmp_path / "証拠" / "甲001：a.pdf"
    dest.write_bytes(b"stay")
    session.layout = session.layout.__class__(
        series=session.layout.series,
        enabled_series=session.layout.enabled_series,
        cards=session.layout.cards,
        last_written=("甲001：a.pdf",),
        label_template=session.layout.label_template,
    )
    monkeypatch.setattr("lexcrew_pdf.stamp.yu_mincho_path", lambda: str(tmp_path / "missing.ttf"))
    result = session.generate()
    assert result["ok"] is False
    assert "游明朝" in result["message"]
    assert dest.read_bytes() == b"stay"


def test_broken_layout_keeps_the_cards(tmp_path):
    evidence = tmp_path / "証拠"
    evidence.mkdir()
    (evidence / "layout.json").write_text("{", encoding="utf-8")
    view = Session(tmp_path).view()
    assert view["message"] == "配置ファイルを読めません。"
    assert view["outputDir"] == str(tmp_path / "証拠")
    assert [card["number"] for card in view["cards"]] == [1, 2, 3, 4, 5, 6]


def _upper_right_has_red(jpeg: bytes) -> bool:
    document = fitz.open(stream=jpeg, filetype="jpeg")
    try:
        pix = document[0].get_pixmap()
        found = 0
        x0 = int(pix.width * 0.7)
        y1 = max(int(pix.height * 0.2), 1)
        for y in range(y1):
            for x in range(x0, pix.width):
                red, green, blue = pix.pixel(x, y)[:3]
                if red > 160 and red > green + 50 and red > blue + 50:
                    found += 1
                    if found > 6:
                        return True
        return False
    finally:
        document.close()


def test_thumbnail_stamps_the_evidence_number(tmp_path):
    _require_font()
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("BODY",))
    _pdf(branch, ("BRANCH",))
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(body))
    session.add_file(1, 1, str(branch))
    media = session.media(1)
    first = base64.b64decode(media["slots"][0]["thumb"])
    second = base64.b64decode(media["slots"][1]["thumb"])
    assert _upper_right_has_red(first)
    assert _upper_right_has_red(second)
    assert first != second


def test_preview_works_before_a_folder_is_chosen(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _pdf(source, ("ONE", "TWO"))
    session = Session()
    session.add_file(1, 0, str(source))
    preview = session.preview(1, 0, 0)
    assert preview["pageCount"] == 2
    assert preview["label"] == "甲第１号証"
    assert preview["image"]


def test_layout_save_does_not_leave_a_writing_file(tmp_path):
    session = Session(tmp_path)
    session.set_title(1, "契約")
    evidence = tmp_path / "証拠"
    assert (evidence / "layout.json").is_file()
    assert not (evidence / "layout.json.writing").exists()


def test_replace_slot_clears_the_previous_files(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _pdf(first, ("A",))
    _pdf(second, ("B",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    third = tmp_path / "third.pdf"
    _pdf(third, ("C",))
    session.replace_slot(1, 0, [str(third)])
    names = [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]]
    assert names == ["third.pdf"]


def test_delete_moves_later_numbers_up(tmp_path):
    session = Session(tmp_path)
    session.set_title(2, "消える")
    session.set_title(3, "残る")
    view = session.delete_slot(2, 0)
    assert [card["number"] for card in view["cards"]] == [1, 2, 3, 4, 5]
    assert view["cards"][1]["slots"][0]["title"] == "残る"
    assert view["cards"][1]["title"] == "残る"
    assert view["cards"][1]["slots"][0]["filename"].startswith("甲002：")


def test_delete_branch_closes_the_gap_and_renames(tmp_path):
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    third = tmp_path / "c.pdf"
    _pdf(first, ("A",))
    _pdf(second, ("B",))
    _pdf(third, ("C",))
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_branch(1)
    session.add_file(1, 0, str(first))
    session.add_file(1, 1, str(second))
    session.add_file(1, 2, str(third))
    view = session.delete_slot(1, 1)
    slots = view["cards"][0]["slots"]
    assert [slot["label"] for slot in slots] == ["甲第１号証の１", "甲第１号証の２"]
    assert [slot["files"][0]["name"] for slot in slots] == ["a.pdf", "c.pdf"]
    assert slots[0]["filename"].startswith("甲001-1：")
    assert slots[1]["filename"].startswith("甲001-2：")


def test_delete_last_branch_drops_the_branch_mark(tmp_path):
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("A",))
    _pdf(branch, ("B",))
    session = Session(tmp_path)
    session.add_branch(4)
    session.add_file(4, 0, str(body))
    session.add_file(4, 1, str(branch))
    view = session.delete_slot(4, 0)
    card = next(item for item in view["cards"] if item["number"] == 4)
    assert card["label"] == "甲第４号証"
    assert card["slots"][0]["files"][0]["name"] == "branch.pdf"
    assert card["slots"][0]["filename"] == "甲004：branch.pdf"
    assert view["cards"][4]["number"] == 5


def test_delete_shifts_saved_page_groups(tmp_path):
    files = []
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        path = tmp_path / name
        _pdf(path, (name,))
        files.append(path)
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_branch(1)
    for index, path in enumerate(files):
        session.add_file(1, index, str(path))
    card = session.layout.cards[0]
    session._put(_replace(card, pages=(
        PageRow(source=0, page=0, part=0, group=1, position=0),
        PageRow(source=1, page=0, part=0, group=2, position=1),
        PageRow(source=2, page=0, part=0, group=3, position=2),
    )))
    session.delete_slot(1, 1)
    assert session.layout.cards[0].pages == (
        PageRow(source=0, page=0, part=0, group=1, position=0),
        PageRow(source=1, page=0, part=0, group=2, position=1),
    )


def test_branch_preview_uses_that_branch(tmp_path):
    _require_font()
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("BODY",))
    _pdf(branch, ("BRANCH", "MORE"))
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(body))
    session.add_file(1, 1, str(branch))
    first = session.preview(1, 0, 0)
    second = session.preview(1, 1, 0)
    assert first["pageCount"] == 1
    assert second["pageCount"] == 2
    assert first["label"] == "甲第１号証の１"
    assert second["label"] == "甲第１号証の２"
    assert first["image"] != second["image"]


def test_branch_editor_keeps_the_other_branch(tmp_path):
    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("ONE", "TWO"))
    _pdf(branch, ("THREE",))
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(body))
    session.add_file(1, 1, str(branch))
    first = session.editor(1, 0)
    second = session.editor(1, 1)
    assert [column["title"] for column in first["columns"]] == ["出すページ", "除くページ"]
    assert [column["title"] for column in second["columns"]] == ["出すページ", "除くページ"]
    assert {page["source"] for column in first["columns"] for page in column["pages"]} == {0}
    assert {page["source"] for column in second["columns"] for page in column["pages"]} == {1}
    assert first["columns"][0]["group"] == 1
    assert second["columns"][0]["group"] == 2
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 0},
    ], 0)
    pages = session.layout.cards[0].pages
    assert any(row.source == 0 and row.page == 1 and row.group == 0 for row in pages)
    assert any(row.source == 1 and row.group == 2 for row in pages)
    again = session.editor(1, 1)
    assert [page["source"] for page in again["columns"][0]["pages"]] == [1]
    assert again["columns"][1]["pages"] == []
    session.reset_pages(1, 0)
    assert session.layout.cards[0].pages is None


def test_editor_lock_blocks_that_number_and_releases(tmp_path):
    body = tmp_path / "body.pdf"
    other = tmp_path / "other.pdf"
    _pdf(body, ("A", "B"))
    _pdf(other, ("C",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(body))
    session.add_branch(1)
    opened = session.begin_edit(1, 0)
    assert opened["editor"] == {"number": 1, "slot": 0}
    with pytest.raises(ValueError, match="編集中"):
        session.rotate(1)
    with pytest.raises(ValueError, match="編集中"):
        session.drop_files(1, 0, None, [str(other)], replace=True)
    with pytest.raises(ValueError, match="編集中"):
        session.delete_slot(1, 1)
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 0},
    ], 0)
    assert any(row.group == 0 for row in session.layout.cards[0].pages)
    session.add_file(2, 0, str(other))
    session.finish_edit()
    assert session.view()["editor"] is None
    session.rotate(1)
    assert session.layout.cards[0].slots[0].rotation == 90


def test_editor_lock_follows_a_lower_number_deleted(tmp_path):
    session = Session(tmp_path)
    first = tmp_path / "a.pdf"
    third = tmp_path / "c.pdf"
    _pdf(first, ("A",))
    _pdf(third, ("C", "D"))
    session.add_file(1, 0, str(first))
    session.add_file(3, 0, str(third))
    session.begin_edit(3, 0)
    session.delete_slot(1, 0)
    assert session.editor_identity() == {"number": 2, "slot": 0}
    with pytest.raises(ValueError, match="編集中"):
        session.rotate(2)
    session.rotate(1)
    session.finish_edit()
    session.rotate(2)


def test_media_counts_pages_that_remain(tmp_path):
    _require_font()
    body = tmp_path / "body.pdf"
    _pdf(body, ("A", "B"))
    session = Session(tmp_path)
    session.add_file(1, 0, str(body))
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 0},
    ], 0)
    assert session.media(1)["slots"][0]["pageCount"] == 1


def test_zoom_stays_inside_the_render_range():
    from lexcrew_pdf.session import _clamp_zoom

    assert _clamp_zoom(0.01) == 0.2
    assert _clamp_zoom(9) == 4
    assert _clamp_zoom(1.15) == 1.15


def test_move_plain_card_renumbers_title_and_filename(tmp_path):
    session = Session(tmp_path)
    session.set_title(1, "いち")
    session.set_title(2, "に")
    session.set_title(3, "さん")
    session.card_errors[3] = "開けません。"
    view = session.move_slot(3, 0, 1)
    assert [card["slots"][0]["title"] for card in view["cards"][:3]] == ["さん", "いち", "に"]
    assert view["cards"][0]["slots"][0]["filename"] == "甲001：さん.pdf"
    assert view["cards"][0]["label"] == "甲第１号証"
    assert view["cards"][1]["slots"][0]["filename"] == "甲002：いち.pdf"
    assert view["cards"][2]["label"] == "甲第３号証"
    assert view["cards"][0]["message"] == "開けません。"
    assert view["cards"][2]["message"] == ""
    assert [card["number"] for card in view["cards"]] == [1, 2, 3, 4, 5, 6]


def test_move_plain_card_does_not_join_a_branch(tmp_path):
    session = Session(tmp_path)
    session.add_branch(2)
    session.set_title(2, "本体", 0)
    session.set_title(2, "枝", 1)
    session.set_title(3, "さん")
    view = session.move_slot(3, 0, 2)
    assert len(view["cards"][1]["slots"]) == 1
    assert view["cards"][1]["slots"][0]["title"] == "さん"
    assert [slot["title"] for slot in view["cards"][2]["slots"]] == ["本体", "枝"]


def test_move_branch_to_the_front_drops_the_branch_mark(tmp_path):
    from lexcrew_pdf.plan import jobs_from_layout

    body = tmp_path / "body.pdf"
    branch = tmp_path / "branch.pdf"
    _pdf(body, ("BODY",))
    _pdf(branch, ("BRANCH",))
    session = Session(tmp_path)
    session.set_title(1, "いち")
    session.add_file(2, 0, str(body))
    session.add_branch(2)
    session.add_file(2, 1, str(branch))
    session.rotate(2, 1)
    session.set_title(3, "さん")
    session.card_errors[2] = "開けません。"
    view = session.move_slot(2, 1, 1)
    moved = view["cards"][0]
    assert moved["label"] == "甲第１号証"
    assert len(moved["slots"]) == 1
    assert moved["slots"][0]["filename"] == "甲001：branch.pdf"
    assert moved["slots"][0]["rotation"] == 90
    assert moved["message"] == ""
    assert view["cards"][1]["slots"][0]["title"] == "いち"
    left = view["cards"][2]
    assert left["label"] == "甲第３号証"
    assert left["slots"][0]["filename"] == "甲003：body.pdf"
    assert left["message"] == "開けません。"
    assert view["cards"][3]["slots"][0]["title"] == "さん"
    built = jobs_from_layout(session.layout, tmp_path)
    assert [(job.stamp, job.filename) for job in built.jobs] == [
        ("甲第１号証", "甲001：branch.pdf"),
        ("甲第３号証", "甲003：body.pdf"),
    ]


def test_move_middle_branch_keeps_the_other_two(tmp_path):
    files = []
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        path = tmp_path / name
        _pdf(path, (name,))
        files.append(path)
    session = Session(tmp_path)
    session.add_branch(2)
    session.add_branch(2)
    for index, path in enumerate(files):
        session.add_file(2, index, str(path))
    view = session.move_slot(2, 1, 1)
    assert view["cards"][0]["label"] == "甲第１号証"
    assert view["cards"][0]["slots"][0]["files"][0]["name"] == "b.pdf"
    assert view["cards"][0]["slots"][0]["filename"] == "甲001：b.pdf"
    kept = view["cards"][2]
    assert [slot["files"][0]["name"] for slot in kept["slots"]] == ["a.pdf", "c.pdf"]
    assert [slot["label"] for slot in kept["slots"]] == ["甲第３号証の１", "甲第３号証の２"]
    assert kept["slots"][0]["filename"] == "甲003-1：a.pdf"
    assert kept["slots"][1]["filename"] == "甲003-2：c.pdf"


def test_move_branch_carries_pages_and_split_without_opening_pdfs(tmp_path, monkeypatch):
    files = []
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        path = tmp_path / name
        _pdf(path, (name,))
        files.append(path)
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_branch(1)
    for index, path in enumerate(files):
        session.add_file(1, index, str(path))
    session._put(_replace(
        session.layout.cards[0],
        split_a4=True,
        pages=(
            PageRow(source=0, page=0, part=0, group=0, position=0),
            PageRow(source=0, page=0, part=1, group=1, position=1),
            PageRow(source=1, page=0, part=0, group=2, position=2),
            PageRow(source=2, page=0, part=0, group=3, position=3),
        ),
    ))

    def refuse_open(*_args, **_kwargs):
        raise AssertionError("pdf")

    monkeypatch.setattr(fitz, "open", refuse_open)
    session.move_slot(1, 0, 2)
    assert session.layout.cards[0].split_a4 is True
    assert [slot.files[0] for slot in session.layout.cards[0].slots] == ["b.pdf", "c.pdf"]
    assert session.layout.cards[0].pages == (
        PageRow(source=0, page=0, part=0, group=1, position=0),
        PageRow(source=1, page=0, part=0, group=2, position=1),
    )
    assert session.layout.cards[1].split_a4 is True
    assert session.layout.cards[1].slots[0].files == ("a.pdf",)
    assert session.layout.cards[1].pages == (
        PageRow(source=0, page=0, part=0, group=0, position=0),
        PageRow(source=0, page=0, part=1, group=1, position=1),
    )


def test_move_to_the_same_place_keeps_the_layout(tmp_path):
    session = Session(tmp_path)
    session.set_title(2, "に")
    session.add_branch(4)
    session.set_title(4, "枝", 1)
    before = session.layout.cards
    assert session.move_slot(2, 0, 3)["cards"][1]["slots"][0]["title"] == "に"
    assert session.move_slot(2, 0, 2)["cards"][1]["number"] == 2
    assert session.move_slot(6, 0, None)["cards"][5]["number"] == 6
    assert session.layout.cards == before


def test_move_locked_number_is_rejected_and_another_move_follows_the_editor(tmp_path):
    source = tmp_path / "c.pdf"
    other = tmp_path / "a.pdf"
    _pdf(source, ("C", "D"))
    _pdf(other, ("A",))
    session = Session(tmp_path)
    session.add_file(1, 0, str(other))
    session.add_file(3, 0, str(source))
    session.add_branch(3)
    session.add_file(3, 1, str(source))
    session.begin_edit(3, 1)
    with pytest.raises(ValueError, match="編集中"):
        session.move_slot(3, 0, 1)
    session.move_slot(1, 0, None)
    assert session.editor_identity() == {"number": 2, "slot": 1}
    with pytest.raises(ValueError, match="編集中"):
        session.rotate(2)
    session.rotate(1)
    assert session.layout.cards[0].slots[0].rotation == 90


def test_downloads_dir_is_this_pc_download_folder():
    path = downloads_dir()
    assert path.is_absolute()
    assert path.is_dir()


def test_boot_uses_the_download_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(app_window, "downloads_dir", lambda: tmp_path)
    session = app_window.boot()
    assert session.folder == tmp_path
    assert session.view()["outputDir"] == str(tmp_path / "証拠")
    assert [card["number"] for card in session.view()["cards"]] == [1, 2, 3, 4, 5, 6]


def test_startup_view_is_under_the_budget():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    script = (
        "import time\n"
        "started = time.perf_counter()\n"
        "from lexcrew_pdf.session import Session\n"
        "Session().view()\n"
        "print('cards-ready', int((time.perf_counter() - started) * 1000))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    line = completed.stdout.strip().splitlines()[-1]
    assert line.startswith("cards-ready")
    elapsed = int(line.split()[-1])
    assert elapsed < 1500
