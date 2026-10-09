"""出力フォルダへの書き出し。"""
import os

import fitz
import pytest

from lexcrew_pdf.plan import OutputJob
from lexcrew_pdf.stamp import yu_mincho_path
from lexcrew_pdf.write import write_jobs


def _require_font():
    if not os.path.isfile(yu_mincho_path()):
        pytest.skip("游明朝がありません")


def _pdf(path, text):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _job(folder, name, stamp, filename, text="BODY"):
    path = folder / name
    _pdf(path, text)
    return OutputJob(
        number=1,
        sources=(str(path),),
        stamp=stamp,
        filename=filename,
        rotation=0,
        split_a4=False,
        pages=None,
    )


def test_two_jobs_are_written_and_recorded(tmp_path):
    _require_font()
    jobs = (
        _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf", "ONE"),
        _job(tmp_path, "b.pdf", "甲第２号証", "甲002：契約.pdf", "TWO"),
    )
    result = write_jobs(tmp_path, jobs, last_written=())
    dest = tmp_path / "LexCrew-PDF-Downloads"
    assert (dest / "甲001：契約.pdf").is_file()
    assert (dest / "甲002：契約.pdf").is_file()
    assert set(result["keep"]) == {"甲001：契約.pdf", "甲002：契約.pdf"}


def test_one_corrupt_file_does_not_stop_the_other(tmp_path):
    _require_font()
    good = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf", "ONE")
    bad_path = tmp_path / "bad.pdf"
    bad_path.write_bytes(b"not a pdf")
    previous = tmp_path / "LexCrew-PDF-Downloads" / "甲002：契約.pdf"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"%PDF-old")
    bad = OutputJob(2, (str(bad_path),), "甲第２号証", "甲002：契約.pdf", 0, False, None)
    result = write_jobs(tmp_path, (good, bad), last_written=("甲002：契約.pdf",))
    assert (tmp_path / "LexCrew-PDF-Downloads" / "甲001：契約.pdf").is_file()
    assert previous.read_bytes() == b"%PDF-old"
    assert len(result["errors"]) == 1


def test_names_missing_from_last_written_are_deleted(tmp_path):
    _require_font()
    dest = tmp_path / "LexCrew-PDF-Downloads"
    dest.mkdir()
    stale = dest / "甲009：古い.pdf"
    stale.write_bytes(b"old")
    job = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf")
    write_jobs(tmp_path, (job,), last_written=("甲009：古い.pdf", "甲001：契約.pdf"))
    assert not stale.exists()
    assert (dest / "甲001：契約.pdf").is_file()


def test_unrelated_pdf_is_kept(tmp_path):
    _require_font()
    dest = tmp_path / "LexCrew-PDF-Downloads"
    dest.mkdir()
    note = dest / "メモ.pdf"
    note.write_bytes(b"keep")
    job = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf")
    write_jobs(tmp_path, (job,), last_written=())
    assert note.read_bytes() == b"keep"


def test_orphan_writing_file_is_removed_on_the_next_run(tmp_path):
    _require_font()
    dest = tmp_path / "LexCrew-PDF-Downloads"
    dest.mkdir()
    orphan = dest / "甲001：契約.pdf.writing"
    orphan.write_bytes(b"partial")
    job = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf")
    write_jobs(tmp_path, (job,), last_written=())
    assert not orphan.exists()


def test_dotdot_filename_is_rejected(tmp_path):
    _require_font()
    source = tmp_path / "a.pdf"
    _pdf(source, "BODY")
    job = OutputJob(1, (str(source),), "甲第１号証", "../逃げる.pdf", 0, False, None)
    with pytest.raises(ValueError):
        write_jobs(tmp_path, (job,), last_written=())
    assert not any(tmp_path.rglob("逃げる.pdf"))


def test_running_twice_matches(tmp_path):
    _require_font()
    job = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf", "SAME")
    first = write_jobs(tmp_path, (job,), last_written=())
    second = write_jobs(tmp_path, (job,), last_written=first["keep"])
    assert second["keep"] == first["keep"]
    assert second["errors"] == []
    document = fitz.open(tmp_path / "LexCrew-PDF-Downloads" / "甲001：契約.pdf")
    try:
        assert document.page_count == 1
        assert "SAME" in document[0].get_text("text")
        assert "甲第１号証" in document[0].get_text("text")
    finally:
        document.close()


def test_missing_font_leaves_the_destination_unchanged(tmp_path, monkeypatch):
    dest = tmp_path / "LexCrew-PDF-Downloads"
    dest.mkdir()
    previous = dest / "甲001：契約.pdf"
    previous.write_bytes(b"stay")
    monkeypatch.setattr("lexcrew_pdf.stamp.yu_mincho_path", lambda: str(tmp_path / "missing.ttf"))
    source = tmp_path / "a.pdf"
    _pdf(source, "BODY")
    job = OutputJob(1, (str(source),), "甲第１号証", "甲001：契約.pdf", 0, False, None)
    from lexcrew_pdf.stamp import StampFontMissing

    with pytest.raises(StampFontMissing):
        write_jobs(tmp_path, (job,), last_written=("甲001：契約.pdf",))
    assert previous.read_bytes() == b"stay"


def test_series_switch_deletes_the_old_kou_file(tmp_path):
    _require_font()
    dest = tmp_path / "LexCrew-PDF-Downloads"
    dest.mkdir()
    old = dest / "甲001：契約.pdf"
    old.write_bytes(b"old")
    job = _job(tmp_path, "a.pdf", "乙第１号証", "乙001：契約.pdf", "OTSU")
    write_jobs(tmp_path, (job,), last_written=("甲001：契約.pdf",))
    assert not old.exists()
    assert (dest / "乙001：契約.pdf").is_file()


def test_grayscale_write_leaves_the_source_and_keeps_a_red_stamp(tmp_path):
    _require_font()
    source = tmp_path / "color.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=400)
    page.draw_rect(fitz.Rect(40, 80, 140, 180), color=(1, 0, 0), fill=(1, 0, 0), width=0)
    document.save(source)
    document.close()
    before = source.read_bytes()
    job = OutputJob(1, (str(source),), "甲第１号証", "甲001：色.pdf", 0, False, None)
    write_jobs(tmp_path, (job,), last_written=(), grayscale=True)
    assert source.read_bytes() == before
    written = fitz.open(tmp_path / "LexCrew-PDF-Downloads" / "甲001：色.pdf")
    try:
        drawings = written[0].get_drawings()
        assert any(
            item.get("color") and item["color"][0] > 0.8 and item["color"][1] < 0.2 and item["color"][2] < 0.2
            for item in drawings
        )
        fills = [item.get("fill") for item in drawings if item.get("fill")]
        assert fills
        assert abs(fills[0][0] - fills[0][1]) < 0.05
        assert abs(fills[0][1] - fills[0][2]) < 0.05
    finally:
        written.close()


def test_output_is_only_under_shoko(tmp_path):
    _require_font()
    job = _job(tmp_path, "a.pdf", "甲第１号証", "甲001：契約.pdf")
    write_jobs(tmp_path, (job,), last_written=())
    assert (tmp_path / "LexCrew-PDF-Downloads" / "甲001：契約.pdf").is_file()
    assert not (tmp_path / "甲001：契約.pdf").exists()
