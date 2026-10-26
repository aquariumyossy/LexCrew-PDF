"""枝番の合体。"""
import json
import os
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import default_layout, layout_to_json, load_layout, parse_layout, with_next_series
from lexcrew_pdf.plan import jobs_from_layout, slot_job
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import yu_mincho_path


def _pdf(path, text="PAGE"):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _pages(path, texts):
    document = fitz.open()
    for text in texts:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_merge_is_on_until_branches_are_output_separately(tmp_path):
    first = tmp_path / "契約.pdf"
    second = tmp_path / "領収.pdf"
    _pages(first, ("A1", "A2"))
    _pdf(second, "B1")
    session = Session(tmp_path)
    assert session.layout.merge_branches is True
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    session.set_title(1, "契約", 0)
    session.set_title(1, "領収", 1)
    merged = jobs_from_layout(session.layout, tmp_path)
    assert len(merged.jobs) == 1
    job = merged.jobs[0]
    assert job.filename == "甲001-1~2 契約.pdf"
    assert [part.stamp for part in job.parts] == ["甲第１号証の１", "甲第１号証の２"]
    assert [part.title for part in job.parts] == ["契約", "領収"]
    assert [len(part.pages) for part in job.parts] == [2, 1]
    assert job.parts[0].pages[0][0] == 0
    assert job.parts[1].pages[0][0] == 1
    view = session.view()["cards"][0]
    assert view["slots"][0]["filename"] == "甲001-1~2 契約.pdf"
    assert view["slots"][1]["filename"] == "甲001-1~2 契約.pdf"
    assert view["slots"][0]["outputNote"] == "→ 甲001-1~2 に含めて出力"
    assert view["slots"][1]["outputNote"] == "→ 甲001-1~2 に含めて出力"
    assert view["mergedFilename"] == "甲001-1~2 契約.pdf"
    assert view["mergeWarning"] == ""
    assert [part.exhibit for part in job.parts] == ["甲001-1", "甲001-2"]
    session.set_title(1, "領収書", 1)
    view = session.view()["cards"][0]
    assert view["slots"][0]["filename"] == "甲001-1~2 契約.pdf"
    assert view["slots"][1]["title"] == "領収書"
    updated = jobs_from_layout(session.layout, tmp_path).jobs[0]
    assert [part.exhibit for part in updated.parts] == ["甲001-1", "甲001-2"]
    assert [part.title for part in updated.parts] == ["契約", "領収書"]

    second_slot = slot_job(merged.jobs, 1, 1)
    assert second_slot is not None
    assert second_slot.stamp == "甲第１号証の２"
    assert second_slot.parts == ()
    assert len(second_slot.pages) == 1

    session.set_merge_branches(False)
    separate = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in separate.jobs] == ["甲001-1 契約.pdf", "甲001-2 領収書.pdf"]
    assert all(job.parts == () for job in separate.jobs)
    view = session.view()["cards"][0]
    assert view["slots"][0]["filename"] == "甲001-1 契約.pdf"
    assert view["slots"][1]["filename"] == "甲001-2 領収書.pdf"
    assert view["slots"][0]["outputNote"] == ""
    assert view["mergedFilename"] == ""


def test_one_filled_branch_stays_a_single_file_when_merge_is_on(tmp_path):
    source = tmp_path / "契約.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.set_merge_branches(True)
    session.add_file(1, 0, str(source))
    session.add_branch(1)
    built = jobs_from_layout(session.layout, tmp_path)
    assert len(built.jobs) == 1
    assert built.jobs[0].filename == "甲001-1 契約.pdf"
    assert built.jobs[0].parts == ()
    assert session.view()["cards"][0]["mergedFilename"] == ""


def test_empty_middle_branch_is_not_merged_across_the_gap(tmp_path):
    first = tmp_path / "一.pdf"
    third = tmp_path / "三.pdf"
    _pdf(first)
    _pdf(third)
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_branch(1)
    session.add_file(1, 2, str(third))
    session.set_title(1, "初め", 0)
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["甲001-1 初め.pdf", "甲001-3 三.pdf"]
    assert [job.stamp for job in built.jobs] == ["甲第１号証の１", "甲第１号証の３"]
    assert built.warnings[0]["message"] == (
        "甲第１号証の２にPDFが無いため、まとめて出力しません。空の枝番を削除すると番号が詰まります。"
    )
    view = session.view()["cards"][0]
    assert view["mergedFilename"] == ""
    assert view["mergeWarning"] == built.warnings[0]["message"]
    assert [slot["filename"] for slot in view["slots"]] == [
        "甲001-1 初め.pdf",
        "甲001-2 証拠.pdf",
        "甲001-3 三.pdf",
    ]
    assert all(slot["outputNote"] == "" for slot in view["slots"])
    session.delete_slot(1, 1)
    closed = jobs_from_layout(session.layout, tmp_path)
    assert len(closed.jobs) == 1
    assert closed.jobs[0].filename == "甲001-1~2 初め.pdf"
    assert [part.stamp for part in closed.jobs[0].parts] == ["甲第１号証の１", "甲第１号証の２"]
    assert closed.warnings == ()


def test_leading_empty_branch_merges_the_later_contiguous_ones(tmp_path):
    second = tmp_path / "二.pdf"
    third = tmp_path / "三.pdf"
    _pdf(second)
    _pdf(third)
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    session.add_file(1, 2, str(third))
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].filename == "甲001-2~3 二.pdf"
    assert [part.stamp for part in built.jobs[0].parts] == ["甲第１号証の２", "甲第１号証の３"]
    view = session.view()["cards"][0]
    assert view["slots"][0]["filename"] == "甲001-2~3 二.pdf"
    assert view["slots"][0]["outputNote"] == ""
    assert view["slots"][1]["outputNote"] == "→ 甲001-2~3 に含めて出力"
    assert view["slots"][2]["filename"] == "甲001-2~3 二.pdf"
    session.set_title(1, "親の書名", 0)
    assert jobs_from_layout(session.layout, tmp_path).jobs[0].filename == "甲001-2~3 親の書名.pdf"


def test_excluded_middle_pages_are_not_merged_and_do_not_renumber(tmp_path, monkeypatch):
    from dataclasses import replace

    from lexcrew_pdf.layout import PageRow

    files = []
    for name in ("一.pdf", "二.pdf", "三.pdf"):
        path = tmp_path / name
        _pdf(path, name)
        files.append(path)
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_branch(1)
    for index, path in enumerate(files):
        session.add_file(1, index, str(path))
    session._put(replace(
        session.layout.cards[0],
        pages=(
            PageRow(source=0, page=0, part=0, group=1, position=0),
            PageRow(source=1, page=0, part=0, group=0, position=1),
            PageRow(source=2, page=0, part=0, group=3, position=2),
        ),
    ))
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["甲001-1 一.pdf", "甲001-3 三.pdf"]
    assert [job.stamp for job in built.jobs] == ["甲第１号証の１", "甲第１号証の３"]
    assert "出すページが無い" in built.warnings[0]["message"]
    assert "甲第１号証の２" in built.warnings[0]["message"]
    # 画面は原本を開かないので、ファイルがある枝番はまとめる表示のまま。案内は生成時に出る。
    view = session.view()["cards"][0]
    assert view["mergedFilename"] == "甲001-1~3 一.pdf"
    assert view["mergeWarning"] == ""

    def fake_write(folder, jobs, *, last_written, preserve=(), grayscale=False, style=None, page_numbers=False, stamp_enabled=True, fit_stamp=False):
        return {
            "written": [{"filename": job.filename} for job in jobs],
            "errors": [],
            "keep": tuple(job.filename for job in jobs),
        }

    monkeypatch.setattr("lexcrew_pdf.write.write_jobs", fake_write)
    result = session.generate()
    assert result["ok"] is True
    assert "出すページが無い" in result["message"]
    assert "保存できませんでした" not in result["message"]
    assert result["cards"][0]["message"] == built.warnings[0]["message"]
    assert {item["filename"] for item in result["written"]} == {"甲001-1 一.pdf", "甲001-3 三.pdf"}


def test_merged_parts_keep_each_slots_rotation_and_stamp_offset(tmp_path):
    from dataclasses import replace

    first = tmp_path / "一.pdf"
    second = tmp_path / "二.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.set_merge_branches(True)
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    session.rotate(1, 1)
    slots = list(session.layout.cards[0].slots)
    slots[1] = replace(slots[1], stamp_dx=-30, stamp_dy=12)
    card = replace(session.layout.cards[0], slots=tuple(slots))
    cards = tuple(card if item.number == 1 else item for item in session.layout.cards)
    session.layout = replace(session.layout, cards=cards)
    job = jobs_from_layout(session.layout, tmp_path).jobs[0]
    assert [part.rotation for part in job.parts] == [0, 90]
    assert (job.parts[1].stamp_dx, job.parts[1].stamp_dy) == (-30, 12)
    assert (job.parts[0].stamp_dx, job.parts[0].stamp_dy) == (0, 0)


def test_unreadable_merge_preserves_the_combined_name(tmp_path):
    broken = tmp_path / "壊れ.pdf"
    other = tmp_path / "別.pdf"
    broken.write_bytes(b"not a pdf")
    _pdf(other)
    session = Session(tmp_path)
    session.set_merge_branches(True)
    session.add_file(1, 0, str(broken))
    session.add_branch(1)
    session.add_file(1, 1, str(other))
    session.set_title(1, "契約", 0)
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs == ()
    assert built.preserve == ("甲001-1~2 契約.pdf",)


def test_merge_and_grayscale_are_saved_together(tmp_path):
    source = tmp_path / "契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    assert session.view()["mergeBranches"] is True
    assert "filenameSeparator" not in session.view()
    session.add_file(1, 0, str(source))
    session.add_branch(1)
    session.add_file(1, 1, str(source))
    session.set_grayscale(True)
    assert session.layout.merge_branches is True
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001-1~2 契約書.pdf"
    assert session.view()["cards"][0]["slots"][1]["filename"] == "甲001-1~2 契約書.pdf"
    assert session.view()["cards"][0]["mergedFilename"] == "甲001-1~2 契約書.pdf"
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "filenameSeparator" not in raw
    assert "mergeBranches" not in raw
    loaded = Session(tmp_path)
    assert loaded.layout.merge_branches is True
    assert loaded.layout.grayscale is True
    session.set_merge_branches(False)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["mergeBranches"] is False
    loaded = Session(tmp_path)
    assert loaded.layout.merge_branches is False
    session.clear()
    assert session.layout.merge_branches is True
    assert session.layout.grayscale is False
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "mergeBranches" not in raw


def test_old_layout_without_the_new_keys_merges_branches(tmp_path):
    evidence = tmp_path / "LexCrew-PDF-Downloads"
    evidence.mkdir()
    (evidence / "layout.json").write_text(
        json.dumps({
            "series": "甲",
            "labelTemplate": "甲第N号証",
            "enabledSeries": ["甲", "乙", "丙"],
            "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
            "lastWritten": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = load_layout(tmp_path)
    assert loaded.merge_branches is True
    kept = parse_layout({
        "series": "甲",
        "labelTemplate": "甲第N号証",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
        "lastWritten": [],
        "mergeBranches": True,
    })
    assert kept.merge_branches is True


def test_saved_filename_separator_is_ignored(tmp_path):
    source = tmp_path / "契約書.pdf"
    _pdf(source)
    evidence = tmp_path / "LexCrew-PDF-Downloads"
    evidence.mkdir()
    payload = {
        "series": "甲",
        "labelTemplate": "甲第N号証",
        "enabledSeries": ["甲", "乙", "丙"],
        "cards": [{"number": 1, "slots": [{"files": ["契約書.pdf"], "title": "契約書"}]}],
        "lastWritten": [],
        "filenameSeparator": "：",
        "mergeBranches": False,
    }
    (evidence / "layout.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    session = Session(tmp_path)
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001 契約書.pdf"
    assert session.layout.merge_branches is False
    session.set_grayscale(True)
    raw = json.loads((evidence / "layout.json").read_text(encoding="utf-8"))
    assert "filenameSeparator" not in raw
    assert raw["mergeBranches"] is False
    payload["filenameSeparator"] = ":"
    ignored = parse_layout(payload)
    assert "filenameSeparator" not in layout_to_json(ignored)
    assert ignored.merge_branches is False


def test_party_letter_template_is_saved_and_numbered(tmp_path):
    source = tmp_path / "準備書面.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.set_series("乙A第N号証")
    session.add_file(1, 0, str(source))
    assert session.layout.series == "乙A"
    assert session.view()["cards"][0]["slots"][0]["filename"] == "乙A001 準備書面.pdf"
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].stamp == "乙A第１号証"
    assert built.jobs[0].exhibit == "乙A001"
    assert built.jobs[0].title == "準備書面"
    assert Session(tmp_path).layout.label_template == "乙A第N号証"


def test_fallback_title_does_not_keep_the_old_exhibit_number(tmp_path):
    source = tmp_path / "甲1 売買契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(2, 0, str(source))
    assert jobs_from_layout(session.layout, tmp_path).jobs[0].filename == "甲002 売買契約書.pdf"
    session.set_title(2, "甲1 残す")
    assert session.view()["cards"][1]["slots"][0]["filename"] == "甲002 甲1 残す.pdf"
    branched = tmp_path / "乙3の1 納品書.pdf"
    memo = tmp_path / "甲第2号証_覚書.pdf"
    _pdf(branched)
    _pdf(memo)
    session.add_file(3, 0, str(branched))
    session.add_branch(3)
    session.add_file(3, 1, str(memo))
    names = [slot["filename"] for slot in session.view()["cards"][2]["slots"]]
    assert names == ["甲003-1~2 納品書.pdf", "甲003-1~2 納品書.pdf"]
    job = jobs_from_layout(session.layout, tmp_path).jobs[-1]
    assert [part.exhibit for part in job.parts] == ["甲003-1", "甲003-2"]
    assert [part.title for part in job.parts] == ["納品書", "覚書"]


def test_jobs_follow_card_order(tmp_path):
    first = tmp_path / "あ.pdf"
    second = tmp_path / "い.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(2, 0, str(second))
    session.set_title(2, "売買契約書")
    session.add_file(1, 0, str(first))
    session.set_title(1, "先頭")
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.exhibit for job in built.jobs] == ["甲001", "甲002"]
    assert [job.title for job in built.jobs] == ["先頭", "売買契約書"]


def test_unreadable_cards_keep_their_names_and_later_cards_still_generate(tmp_path):
    broken = tmp_path / "甲1 売買契約書.pdf"
    later = tmp_path / "領収.pdf"
    branch = tmp_path / "納品.pdf"
    good = tmp_path / "覚書.pdf"
    broken.write_bytes(b"not a pdf")
    later.write_bytes(b"also not")
    _pdf(branch)
    _pdf(good)
    session = Session(tmp_path)
    session.add_file(1, 0, str(broken))
    session.add_branch(1)
    session.add_file(1, 1, str(branch))
    session.set_title(1, "契約", 0)
    session.add_file(2, 0, str(later))
    session.set_title(2, "領収書")
    session.add_file(3, 0, str(good))
    session.set_title(3, "覚書")
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["甲003 覚書.pdf"]
    assert [row["number"] for row in built.errors] == [1, 2]
    assert all(row["message"].startswith("原本を開けません。") for row in built.errors)
    assert built.preserve == ("甲001-1~2 契約.pdf", "甲002 領収書.pdf")


def test_long_title_on_a_job_stays_within_100_characters(tmp_path):
    source = tmp_path / "長い.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "あ" * 180)
    name = jobs_from_layout(session.layout, tmp_path).jobs[0].filename
    assert len(name) <= 100
    assert name.startswith("甲001 ")
    assert name.endswith(".pdf")


def test_first_number_shifts_filename_stamp_and_list(tmp_path, monkeypatch):
    source = tmp_path / "a.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.begin_edit(1, 0)
    view = session.set_first_number(7.0)
    assert view["firstNumber"] == 7
    assert [card["number"] for card in view["cards"]] == [1, 2, 3, 4, 5, 6]
    assert view["cards"][0]["label"] == "甲第７号証"
    assert view["cards"][0]["slots"][0]["filename"] == "甲007 a.pdf"
    assert view["cards"][5]["label"] == "甲第１２号証"
    assert session.edit_context()["label"] == "甲第７号証"
    assert session.editor_identity() == {"number": 1, "slot": 0}
    session.finish_edit()
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs[0].number == 1
    assert built.jobs[0].stamp == "甲第７号証"
    assert built.jobs[0].exhibit == "甲007"
    assert built.jobs[0].filename == "甲007 a.pdf"
    assert built.jobs[0].title == "a"
    if os.path.isfile(yu_mincho_path()):
        generated = session.generate()
        assert generated["ok"] is True
        assert generated["written"][0]["filename"] == "甲007 a.pdf"
        assert generated["written"][0]["stampLabel"] == "甲第７号証"
        document = fitz.open(tmp_path / "LexCrew-PDF-Downloads" / "甲007 a.pdf")
        try:
            assert "甲第７号証" in document[0].get_text("text")
        finally:
            document.close()
    session.set_title(1, "契約")
    session.set_grayscale(True)
    session.set_series("乙")
    assert session.layout.first_number == 7
    assert session.view()["cards"][0]["label"] == "乙第７号証"
    assert with_next_series(session.layout).first_number == 7
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["firstNumber"] == 7
    assert load_layout(tmp_path).first_number == 7
    session.add_branch(2)
    assert session.view()["cards"][1]["slots"][0]["label"] == "乙第８号証の１"
    deleted = session.delete_slot(1, 0)
    assert deleted["firstNumber"] == 7
    assert deleted["cards"][0]["number"] == 1
    assert deleted["cards"][0]["slots"][0]["label"] == "乙第７号証の１"
    for bad in (0, 1.5, 10000, True, "7"):
        with pytest.raises(ValueError, match="開始番号は1から9999までの整数です。"):
            session.set_first_number(bad)
    assert session.layout.first_number == 7
    session.clear()
    assert session.view()["firstNumber"] == 1
    assert session.view()["cards"][0]["label"] == "甲第１号証"
    assert "firstNumber" not in layout_to_json(session.layout)


def test_missing_first_number_is_one_and_bad_values_are_rejected():
    raw = layout_to_json(default_layout())
    assert "firstNumber" not in raw
    assert parse_layout(raw).first_number == 1
    assert parse_layout({**raw, "firstNumber": 7}).first_number == 7
    for bad in (0, 10000, 1.5, True, "7"):
        with pytest.raises(ValueError, match="配置ファイルを読めません。"):
            parse_layout({**raw, "firstNumber": bad})


def test_generation_reports_a_vanished_original_and_skips_the_partial_pdf(tmp_path, monkeypatch):
    from lexcrew_pdf.window import Api

    missing = tmp_path / "消えた契約書.pdf"
    also_missing = tmp_path / "無い付属.pdf"
    kept = tmp_path / "残す.pdf"
    _pdf(missing, "GONE")
    _pdf(also_missing, "ALSO")
    _pdf(kept, "KEEP")
    session = Session(tmp_path)
    session.add_file(1, 0, str(missing))
    session.add_file(2, 0, str(also_missing))
    session.add_file(2, 0, str(kept))
    missing.unlink()
    also_missing.unlink()
    assert any(Path(stored).name == "消えた契約書.pdf" for stored in session.layout.cards[0].slots[0].files)
    assert [Path(stored).name for stored in session.layout.cards[1].slots[0].files] == ["無い付属.pdf", "残す.pdf"]

    opened = []
    import lexcrew_pdf.stamp as stamp

    real_open = stamp.open_source

    def spy(path):
        name = Path(path).name
        opened.append(name)
        if name in {"消えた契約書.pdf", "無い付属.pdf"}:
            raise AssertionError(path)
        return real_open(path)

    monkeypatch.setattr(stamp, "open_source", spy)
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs == ()
    assert [row["number"] for row in built.errors] == [1, 2]
    assert built.errors[0]["message"] == "原本が見つかりません：消えた契約書.pdf"
    assert built.errors[1]["message"] == "原本が見つかりません：無い付属.pdf"
    assert "消えた契約書.pdf" not in opened
    assert "無い付属.pdf" not in opened
    assert str(tmp_path) not in built.errors[0]["message"]

    written_sources = []

    def fake_pdf(source_paths, *args, **kwargs):
        written_sources.append(tuple(Path(path).name for path in source_paths))
        return b"%PDF-1.4\n"

    monkeypatch.setattr("lexcrew_pdf.write.require_stamp_font", lambda *args, **kwargs: None)
    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", fake_pdf)
    opened.clear()
    result = session.generate()
    assert "消えた契約書.pdf" not in opened
    assert "無い付属.pdf" not in opened
    assert written_sources == []
    assert result["ok"] is False
    assert result["written"] == []
    assert "Errno 2" not in result["message"]
    assert str(tmp_path) not in result["message"]
    first = result["cards"][0]
    second = result["cards"][1]
    assert first["hasFile"] is False
    assert first["slots"][0]["files"] == []
    assert first["message"] == "原本が見つかりません：消えた契約書.pdf"
    assert [item["name"] for item in second["slots"][0]["files"]] == ["残す.pdf"]
    assert second["message"] == "原本が見つかりません：無い付属.pdf"
    assert "残す.pdf" not in second["message"]
    media = Api(session).media(1)
    assert media["ok"] is False
    assert media["message"] == "原本が見つかりません：消えた契約書.pdf"
    assert str(tmp_path) not in media["message"]
    assert "Errno" not in media["message"]


def test_unreadable_file_keeps_the_shown_filename(tmp_path):
    broken = tmp_path / "壊れ.pdf"
    broken.write_bytes(b"not a pdf")
    session = Session(tmp_path)
    session.set_first_number(7)
    session.add_file(1, 0, str(broken))
    built = jobs_from_layout(session.layout, tmp_path)
    assert built.jobs == ()
    assert built.preserve == ("甲007 壊れ.pdf",)
    assert built.errors[0]["number"] == 1
    assert built.errors[0]["message"].startswith("原本を開けません。")


def test_media_keeps_the_ordinal_and_stamps_the_shown_number(tmp_path, monkeypatch):
    source = tmp_path / "a.pdf"
    _pdf(source)
    seen = {}

    def fake_render(paths, stamp, *args, **kwargs):
        seen["stamp"] = stamp
        return b"jpeg"

    monkeypatch.setattr("lexcrew_pdf.stamp.render_stamped_page_jpeg", fake_render)
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_first_number(7)
    media = session.media(1)
    assert media["number"] == 1
    assert seen["stamp"] == "甲第７号証"


def test_stamp_off_uses_the_title_and_leaves_numbered_stamps_for_later(tmp_path, monkeypatch):
    first = tmp_path / "契約.pdf"
    second = tmp_path / "同じ.pdf"
    third = tmp_path / "領収.pdf"
    _pdf(first, "ONE")
    _pdf(second, "TWO")
    _pdf(third, "THREE")
    session = Session(tmp_path)
    assert session.layout.stamp_enabled is True
    assert "stampEnabled" not in layout_to_json(session.layout)
    session.add_file(1, 0, str(first))
    session.set_title(1, "契約書", 0)
    session.add_file(2, 0, str(second))
    session.set_title(2, "契約書", 0)
    session.add_branch(2)
    session.add_file(2, 1, str(third))
    session.set_title(2, "領収", 1)
    session.set_stamp_enabled(False)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["stampEnabled"] is False
    assert load_layout(tmp_path).stamp_enabled is False
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["契約書.pdf", "契約書 (2).pdf"]
    assert built.jobs[0].stamp == "甲第１号証"
    assert [part.stamp for part in built.jobs[1].parts] == ["甲第２号証の１", "甲第２号証の２"]
    view = session.view()
    assert view["stampEnabled"] is False
    assert view["cards"][0]["label"] == "甲第１号証"
    assert view["cards"][0]["slots"][0]["filename"] == "契約書.pdf"
    assert view["cards"][1]["slots"][0]["filename"] == "契約書 (2).pdf"
    assert view["cards"][1]["slots"][1]["filename"] == "契約書 (2).pdf"
    assert view["cards"][1]["slots"][1]["outputNote"] == "→ 契約書 (2).pdf に含めて出力"
    assert view["cards"][1]["slots"][0]["label"] == "甲第２号証の１"
    seen = {}

    def fake_render(paths, stamp, *args, **kwargs):
        seen["draw"] = kwargs.get("draw_stamp")
        return b"jpeg"

    monkeypatch.setattr("lexcrew_pdf.stamp.render_stamped_page_jpeg", fake_render)
    session.media(1)
    assert seen["draw"] is False
    session.begin_edit(1, 0)
    assert session.edit_context()["stampFrame"] is None
    assert session.edit_context()["label"] == "甲第１号証"
    session.set_stamp_enabled(True)
    restored = jobs_from_layout(session.layout, tmp_path)
    assert restored.jobs[0].filename == "甲001 契約書.pdf"
    assert "stampEnabled" not in layout_to_json(session.layout)


def test_template_without_n_stamps_the_same_text_and_drops_the_number(tmp_path):
    body = tmp_path / "本体.pdf"
    branch = tmp_path / "枝.pdf"
    other = tmp_path / "もう一つ.pdf"
    _pdf(body, "BODY")
    _pdf(branch, "BRANCH")
    _pdf(other, "OTHER")
    session = Session(tmp_path)
    session.set_series("別紙")
    assert session.layout.label_template == "別紙"
    assert [card["label"] for card in session.view()["cards"][:3]] == ["別紙", "別紙", "別紙"]
    session.add_file(1, 0, str(body))
    session.add_branch(1)
    session.add_file(1, 1, str(branch))
    session.set_title(1, "契約", 0)
    session.set_title(1, "領収", 1)
    session.add_file(2, 0, str(other))
    session.set_title(2, "契約", 0)
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["契約.pdf", "契約 (2).pdf"]
    assert built.jobs[0].stamp == "別紙"
    assert [part.stamp for part in built.jobs[0].parts] == ["別紙", "別紙"]
    assert built.jobs[0].exhibit == ""
    assert all(part.exhibit == "" for part in built.jobs[0].parts)
    view = session.view()["cards"]
    assert [slot["label"] for slot in view[0]["slots"]] == ["別紙", "別紙"]
    assert view[0]["slots"][1]["outputNote"] == "→ 契約.pdf に含めて出力"
    assert view[1]["slots"][0]["filename"] == "契約 (2).pdf"
    session.set_series("参考資料")
    named = jobs_from_layout(session.layout, tmp_path)
    assert named.jobs[0].stamp == "参考資料"
    assert named.jobs[0].filename == "契約.pdf"
    session.set_merge_branches(False)
    session.set_series("別紙")
    separate = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in separate.jobs[:2]] == ["契約.pdf", "領収.pdf"]
    assert [job.stamp for job in separate.jobs[:2]] == ["別紙", "別紙"]


def test_template_without_n_mentions_the_branch_slot_when_a_gap_blocks_merge(tmp_path):
    first = tmp_path / "一.pdf"
    third = tmp_path / "三.pdf"
    _pdf(first)
    _pdf(third)
    session = Session(tmp_path)
    session.set_series("別紙")
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_branch(1)
    session.add_file(1, 2, str(third))
    built = jobs_from_layout(session.layout, tmp_path)
    assert [job.filename for job in built.jobs] == ["一.pdf", "三.pdf"]
    assert [job.stamp for job in built.jobs] == ["別紙", "別紙"]
    assert built.warnings[0]["message"] == (
        "2番目の枝番にPDFが無いため、まとめて出力しません。空の枝番を削除すると、残った枝番がまとまります。"
    )
    assert session.view()["cards"][0]["mergeWarning"] == built.warnings[0]["message"]


def test_missing_primary_does_not_bring_excluded_pages_back(tmp_path):
    from dataclasses import replace

    from lexcrew_pdf.layout import PageRow, drop_missing_originals
    from lexcrew_pdf.pages import GROUP_EXCLUDED, GROUP_PRIMARY, resolve_buckets

    body = tmp_path / "本文.pdf"
    cover = tmp_path / "送付状.pdf"
    _pdf(body, "BODY")
    _pdf(cover, "COVER")
    session = Session(tmp_path)
    session.add_file(1, 0, str(body))
    session.add_file(1, 0, str(cover))
    session._put(replace(
        session.layout.cards[0],
        pages=(
            PageRow(source=0, page=0, part=0, group=1, position=0),
            PageRow(source=1, page=0, part=0, group=0, position=1),
        ),
    ))
    body.unlink()
    assert [Path(item).name for item in session.layout.cards[0].slots[0].files] == ["本文.pdf", "送付状.pdf"]
    cleaned, names = drop_missing_originals(tmp_path, session.layout.cards[0])
    assert names == ("本文.pdf",)
    assert cleaned.pages == (PageRow(source=0, page=0, part=0, group=0, position=0),)
    rows = [{
        "source_index": 0,
        "page_index": 0,
        "part": 0,
        "group_index": cleaned.pages[0].group,
        "position": 0,
    }]
    buckets = resolve_buckets([(0, 0, 0)], rows, [1], honor_exclusions=True)
    assert buckets[GROUP_PRIMARY] == []
    assert buckets[GROUP_EXCLUDED] == [(0, 0, 0)]
    built = jobs_from_layout(session.layout, tmp_path)
    for job in built.jobs:
        names = [Path(source).name for source in job.sources]
        assert names != ["送付状.pdf"]
        if job.pages is None:
            assert "送付状.pdf" not in names


def test_failed_regeneration_keeps_the_previous_evidence_pdf(tmp_path, monkeypatch):
    contract = tmp_path / "契約書.pdf"
    extra = tmp_path / "別紙.pdf"
    _pdf(contract, "A")
    _pdf(extra, "B")
    session = Session(tmp_path)
    session.add_file(1, 0, str(contract))
    session.add_file(1, 0, str(extra))
    monkeypatch.setattr("lexcrew_pdf.write.require_stamp_font", lambda *args, **kwargs: None)
    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", lambda *args, **kwargs: b"%PDF-1.4\n")
    first = session.generate()
    assert first["ok"] is True
    assert [row["filename"] for row in first["written"]] == ["甲001 契約書.pdf"]
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001 契約書.pdf"
    assert output.is_file()
    previous = output.read_bytes()
    contract.unlink()
    extra.write_bytes(b"not a pdf")
    second = session.generate()
    assert second["ok"] is False
    assert output.is_file()
    assert output.read_bytes() == previous
    assert "削除したファイル: 甲001 契約書.pdf" not in second["message"]


def test_emptied_first_branch_title_is_not_the_merged_filename(tmp_path):
    sale = tmp_path / "売買.pdf"
    receipt = tmp_path / "領収.pdf"
    delivery = tmp_path / "納品.pdf"
    _pdf(sale)
    _pdf(receipt)
    _pdf(delivery)
    session = Session(tmp_path)
    session.add_file(1, 0, str(sale))
    session.add_branch(1)
    session.add_file(1, 1, str(receipt))
    session.add_branch(1)
    session.add_file(1, 2, str(delivery))
    session.set_title(1, "売買契約書", 0)
    sale.unlink()
    view = session.view()["cards"][0]
    assert view["slots"][0]["files"] == []
    assert view["slots"][0]["filename"] == "甲001-2~3 領収.pdf"
    assert view["mergedFilename"] == "甲001-2~3 領収.pdf"
    assert "売買契約書" not in view["mergedFilename"]
    assert all("売買契約書" not in slot["filename"] for slot in view["slots"])
    built = jobs_from_layout(session.layout, tmp_path)
    assert all("売買契約書" not in job.filename for job in built.jobs)


def test_missing_notice_follows_the_slot_and_stays_with_other_warnings(tmp_path, monkeypatch):
    present = tmp_path / "本文.pdf"
    missing = tmp_path / "無い付属.pdf"
    tail = tmp_path / "末尾.pdf"
    extra = tmp_path / "追加.pdf"
    for path in (present, missing, tail, extra):
        _pdf(path)
    session = Session(tmp_path)
    session.add_file(1, 0, str(present))
    session.add_branch(1)
    session.add_file(1, 1, str(missing))
    session.add_branch(1)
    session.add_file(1, 2, str(tail))
    missing.unlink()
    session.card_errors[1] = "甲第１号証の２に出すページが無いため、まとめて出力しません。"
    view = session.view()["cards"][0]
    assert "原本が見つかりません：無い付属.pdf" in view["message"]
    assert "出すページが無い" in view["message"]
    assert "にPDFが無い" in view["mergeWarning"]
    session.add_file(1, 0, str(extra))
    held = session.view()["cards"][0]
    assert "原本が見つかりません：無い付属.pdf" in held["message"]
    assert "出すページが無い" in held["message"]
    monkeypatch.setattr("lexcrew_pdf.write.require_stamp_font", lambda *args, **kwargs: None)
    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", lambda *args, **kwargs: b"%PDF-1.4\n")
    generated = session.generate()
    card = generated["cards"][0]
    assert "原本が見つかりません：無い付属.pdf" in card["message"]
    assert "にPDFが無い" in card["mergeWarning"]
    moved = session.move_slot(1, 1)
    by_number = {item["number"]: item for item in moved["cards"]}
    assert "原本が見つかりません：無い付属.pdf" in by_number[7]["message"]
    assert "出すページが無い" not in by_number[7]["message"]
    assert "原本が見つかりません" not in by_number[1]["message"]
    assert by_number[7]["hasFile"] is False
    assert by_number[7]["slots"][0]["files"] == []


def test_old_layout_without_stamp_enabled_keeps_the_stamp_on():
    raw = layout_to_json(default_layout())
    assert "stampEnabled" not in raw
    assert parse_layout(raw).stamp_enabled is True
    off = parse_layout({**raw, "stampEnabled": False})
    assert off.stamp_enabled is False
    assert layout_to_json(off)["stampEnabled"] is False
    with pytest.raises(ValueError, match="配置ファイルを読めません。"):
        parse_layout({**raw, "stampEnabled": "no"})
