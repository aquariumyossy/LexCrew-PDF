"""枝番の合体、区切り、号証一覧。"""
import json

import fitz
import pytest

from lexcrew_pdf.layout import load_layout, parse_layout
from lexcrew_pdf.plan import evidence_tsv, jobs_from_layout, slot_job
from lexcrew_pdf.session import Session


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
    assert evidence_tsv(merged.jobs) == "甲第１号証の１\t契約\n甲第１号証の２\t領収"
    session.set_title(1, "領収書", 1)
    view = session.view()["cards"][0]
    assert view["slots"][0]["filename"] == "甲001-1~2 契約.pdf"
    assert view["slots"][1]["title"] == "領収書"
    assert evidence_tsv(jobs_from_layout(session.layout, tmp_path).jobs) == "甲第１号証の１\t契約\n甲第１号証の２\t領収書"

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

    def fake_write(folder, jobs, *, last_written, preserve=(), grayscale=False, style=None):
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


def test_separator_choice_is_saved_and_survives_other_settings(tmp_path):
    source = tmp_path / "契約書.pdf"
    _pdf(source)
    session = Session(tmp_path)
    assert session.view()["filenameSeparator"] == " "
    assert session.view()["mergeBranches"] is True
    session.set_filename_separator("：")
    session.add_file(1, 0, str(source))
    session.add_branch(1)
    session.add_file(1, 1, str(source))
    session.set_grayscale(True)
    assert session.layout.filename_separator == "："
    assert session.layout.merge_branches is True
    assert session.view()["cards"][0]["slots"][0]["filename"] == "甲001-1~2：契約書.pdf"
    assert session.view()["cards"][0]["slots"][1]["filename"] == "甲001-1~2：契約書.pdf"
    assert session.view()["cards"][0]["mergedFilename"] == "甲001-1~2：契約書.pdf"
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert raw["filenameSeparator"] == "："
    assert "mergeBranches" not in raw
    loaded = Session(tmp_path)
    assert loaded.layout.filename_separator == "："
    assert loaded.layout.merge_branches is True
    assert loaded.layout.grayscale is True
    session.set_filename_separator(" ")
    session.set_merge_branches(False)
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "filenameSeparator" not in raw
    assert raw["mergeBranches"] is False
    loaded = Session(tmp_path)
    assert loaded.layout.merge_branches is False
    session.clear()
    assert session.layout.filename_separator == " "
    assert session.layout.merge_branches is True
    assert session.layout.grayscale is False
    raw = json.loads((tmp_path / "LexCrew-PDF-Downloads" / "layout.json").read_text(encoding="utf-8"))
    assert "mergeBranches" not in raw


def test_old_layout_without_the_new_keys_uses_a_space(tmp_path):
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
    assert loaded.filename_separator == " "
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
    with pytest.raises(ValueError, match="配置ファイルを読めません"):
        parse_layout({
            "series": "甲",
            "labelTemplate": "甲第N号証",
            "enabledSeries": ["甲", "乙", "丙"],
            "cards": [{"number": 1, "slots": [{"files": [], "title": ""}]}],
            "lastWritten": [],
            "filenameSeparator": ":",
        })


def test_party_letter_template_is_saved_and_numbered(tmp_path):
    source = tmp_path / "準備書面.pdf"
    _pdf(source)
    session = Session(tmp_path)
    session.set_series("乙A第N号証")
    session.add_file(1, 0, str(source))
    assert session.layout.series == "乙A"
    assert session.view()["cards"][0]["slots"][0]["filename"] == "乙A001 準備書面.pdf"
    assert jobs_from_layout(session.layout, tmp_path).jobs[0].stamp == "乙A第１号証"
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
    assert evidence_tsv(jobs_from_layout(session.layout, tmp_path).jobs).split("\n")[-2:] == [
        "甲第３号証の１\t納品書",
        "甲第３号証の２\t覚書",
    ]


def test_evidence_list_follows_output_order_and_escapes_tabs(tmp_path):
    first = tmp_path / "あ.pdf"
    second = tmp_path / "い.pdf"
    _pdf(first)
    _pdf(second)
    session = Session(tmp_path)
    session.add_file(2, 0, str(second))
    session.set_title(2, "売買\t契約\n書")
    session.add_file(1, 0, str(first))
    session.set_title(1, "先頭")
    listed = session.evidence_list()
    assert listed["rows"] == 2
    assert listed["text"] == "甲第１号証\t先頭\n甲第２号証\t売買 契約 書"
    assert session.evidence_list()["text"].count("\n") == 1
    empty = Session(tmp_path)
    empty.clear()
    assert empty.evidence_list() == {"text": "", "rows": 0}


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
