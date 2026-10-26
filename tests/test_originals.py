"""原本の複製。生成結果は、書いた PDF のページ本文で見る。"""
import os
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from lexcrew_pdf.layout import default_layout, save_layout
from lexcrew_pdf.originals import originals_dir
from lexcrew_pdf.session import Session
from lexcrew_pdf.stamp import yu_mincho_path


def _pdf(path: Path, texts) -> None:
    document = fitz.open()
    for text in texts:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), text)
        document.save(path)
    document.close()


def _texts(path: Path) -> list[str]:
    document = fitz.open(path)
    try:
        return [page.get_text("text") for page in document]
    finally:
        document.close()


def _use_font(monkeypatch) -> None:
    if os.path.isfile(yu_mincho_path()):
        return
    fallback = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    if not os.path.isfile(fallback):
        pytest.skip("游明朝がありません")
    monkeypatch.setattr("lexcrew_pdf.stamp.yu_mincho_path", lambda: fallback)


def _stored(session: Session, number: int, slot: int = 0, index: int = 0) -> Path:
    card = next(item for item in session.layout.cards if item.number == number)
    return Path(card.slots[slot].files[index])


def test_originals_dir_follows_localappdata_then_a_per_user_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("LEXCREW_ORIGINALS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert originals_dir() == tmp_path / "Local" / "LexCrew-PDF" / "originals"
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert originals_dir() == tmp_path / "home" / ".local" / "share" / "LexCrew-PDF" / "originals"


def test_add_replace_and_drop_copy_the_original(tmp_path):
    source = tmp_path / "契約書.pdf"
    replacement = tmp_path / "差替.pdf"
    dropped = tmp_path / "追加.pdf"
    _pdf(source, ["SOURCE-BODY"])
    _pdf(replacement, ["REPLACED-BODY"])
    _pdf(dropped, ["DROPPED-BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    copied = _stored(session, 1)
    assert copied.is_file()
    assert copied.resolve() != source.resolve()
    assert originals_dir().resolve() in copied.resolve().parents
    assert copied.name == "契約書.pdf"
    assert copied.read_bytes() == source.read_bytes()
    assert source.is_file()

    session.replace_slot(1, 0, [str(replacement)])
    assert not copied.exists()
    replaced = _stored(session, 1)
    assert replaced.read_bytes() == replacement.read_bytes()
    assert replacement.is_file()

    session.drop_files(1, 0, None, [str(dropped)])
    names = [Path(item).name for item in session.layout.cards[0].slots[0].files]
    assert names == ["差替.pdf", "追加.pdf"]
    extra = _stored(session, 1, 0, 1)
    assert extra.read_bytes() == dropped.read_bytes()
    assert replaced.is_file()


def test_source_deleted_after_add_still_generates_in_order(tmp_path, monkeypatch):
    source = tmp_path / "契約書.pdf"
    _pdf(source, ["AFTER-DELETE-1", "AFTER-DELETE-2"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約書", 0)
    copied = _stored(session, 1)
    source.unlink()
    assert not source.exists()
    assert copied.is_file()
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001 契約書.pdf"
    texts = _texts(output)
    assert len(texts) == 2
    assert "AFTER-DELETE-1" in texts[0]
    assert "AFTER-DELETE-2" in texts[1]
    assert "AFTER-DELETE-2" not in texts[0]


def test_copies_are_removed_on_delete_replace_and_clear_but_sources_stay(tmp_path, monkeypatch):
    first = tmp_path / "甲.pdf"
    second = tmp_path / "乙.pdf"
    third = tmp_path / "丙.pdf"
    _pdf(first, ["KEEP-A"])
    _pdf(second, ["KEEP-B"])
    _pdf(third, ["KEEP-C"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    session.add_file(2, 0, str(third))
    branch_copy = _stored(session, 1, 1)
    kept_copy = _stored(session, 1, 0)
    other_copy = _stored(session, 2)
    session.delete_slot(1, 1)
    assert not branch_copy.exists()
    assert kept_copy.is_file()
    assert other_copy.is_file()
    assert second.is_file()

    session.replace_file(2, 0, 0, str(first))
    assert not other_copy.exists()
    replaced = _stored(session, 2)
    assert replaced.is_file()
    assert replaced != other_copy
    assert third.is_file()

    _use_font(monkeypatch)
    session.set_title(2, "甲", 0)
    session.generate()
    evidence = tmp_path / "LexCrew-PDF-Downloads" / "甲002 甲.pdf"
    assert evidence.is_file()
    evidence_bytes = evidence.read_bytes()
    session.clear()
    assert not kept_copy.exists()
    assert not replaced.exists()
    assert evidence.is_file()
    assert evidence.read_bytes() == evidence_bytes
    assert first.is_file()


def test_a_shared_copy_stays_until_every_card_and_case_releases_it(tmp_path):
    source = tmp_path / "共有.pdf"
    _pdf(source, ["SHARED"])
    case_a = tmp_path / "a"
    case_b = tmp_path / "b"
    case_a.mkdir()
    case_b.mkdir()
    first = Session(case_a)
    first.add_file(1, 0, str(source))
    stored = first.layout.cards[0].slots[0].files[0]
    second_card = first.layout.cards[1]
    first._put(replace(second_card, slots=(replace(second_card.slots[0], files=(stored,)),)))
    first.delete_slot(1, 0)
    assert Path(stored).is_file()
    other = Session(case_b)
    other_card = other.layout.cards[0]
    other._put(replace(other_card, slots=(replace(other_card.slots[0], files=(stored,)),)))
    first.delete_slot(1, 0)
    assert Path(stored).is_file()
    assert source.is_file()
    other.clear()
    assert not Path(stored).exists()
    assert source.is_file()


def test_legacy_layout_copies_a_live_source_and_keeps_a_missing_one(tmp_path, monkeypatch):
    scans = tmp_path / "scans"
    scans.mkdir()
    live = scans / "残す.pdf"
    _pdf(live, ["MIGRATED-PAGE"])
    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(cards[0], slots=(replace(cards[0].slots[0], files=("scans/残す.pdf",)),))
    cards[1] = replace(cards[1], slots=(replace(cards[1].slots[0], files=("scans/消えた.pdf",)),))
    save_layout(tmp_path, replace(layout, cards=tuple(cards)))
    session = Session(tmp_path)
    copied = _stored(session, 1)
    assert copied.is_file()
    assert copied.read_bytes() == live.read_bytes()
    assert session.layout.cards[1].slots[0].files == ("scans/消えた.pdf",)
    view = session.view()["cards"]
    assert view[0]["hasFile"] is True
    assert view[0]["message"] == ""
    assert view[1]["hasFile"] is False
    assert view[1]["number"] == 2
    assert view[1]["message"] == "原本が見つかりません：消えた.pdf"
    assert "scans" not in view[1]["message"]
    live.unlink()
    _use_font(monkeypatch)
    session.set_title(1, "残す", 0)
    result = session.generate()
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001 残す.pdf"
    assert output.is_file()
    assert "MIGRATED-PAGE" in _texts(output)[0]
    assert result["ok"] is False
    assert result["cards"][1]["message"] == "原本が見つかりません：消えた.pdf"
    assert [row["filename"] for row in result["written"]] == ["甲001 残す.pdf"]


def test_legacy_missing_exhibit_is_skipped_and_previous_pdf_bytes_stay(tmp_path, monkeypatch):
    source = tmp_path / "契約書.pdf"
    _pdf(source, ["OLD-ONE", "OLD-TWO"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約書", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001 契約書.pdf"
    previous = output.read_bytes()
    texts = _texts(output)
    assert "OLD-ONE" in texts[0]
    assert "OLD-TWO" in texts[1]
    copied = _stored(session, 1)
    card = session.layout.cards[0]
    session._put(replace(card, slots=(replace(card.slots[0], files=("gone/契約書.pdf",)),)))
    copied.unlink()
    session.set_title(1, "領収書", 0)
    assert session.preview_generate()["delete"] == []
    result = session.generate()
    assert result["ok"] is False
    assert output.is_file()
    assert output.read_bytes() == previous
    assert not (output.parent / "甲001 領収書.pdf").exists()
    assert "OLD-ONE" in _texts(output)[0]
    assert "OLD-TWO" in _texts(output)[1]
    assert "削除したファイル" not in result["message"]
    assert result["cards"][0]["message"] == "原本が見つかりません：契約書.pdf"
    assert str(tmp_path) not in result["cards"][0]["message"]


def test_adding_a_file_to_a_missing_slot_keeps_other_exclusions(tmp_path, monkeypatch):
    placeholder = tmp_path / "仮.pdf"
    body = tmp_path / "本文.pdf"
    added = tmp_path / "追加.pdf"
    _pdf(placeholder, ["PLACEHOLDER"])
    _pdf(body, ["KEEP-PAGE", "DROP-PAGE"])
    _pdf(added, ["NEW-PAGE"])
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(placeholder))
    session.add_file(1, 1, str(body))
    session.set_pages(1, [
        {"source": 1, "page": 0, "part": 0, "group": 2},
        {"source": 1, "page": 1, "part": 0, "group": 0},
    ], 1)
    copied = _stored(session, 1, 0)
    card = session.layout.cards[0]
    session._put(replace(card, slots=(
        replace(card.slots[0], files=("gone/仮.pdf",)),
        card.slots[1],
    )))
    copied.unlink()
    assert session.view()["cards"][0]["slots"][0]["files"] == []
    session.add_file(1, 0, str(added))
    pages = session.layout.cards[0].pages
    assert pages is not None
    assert any(row.source == 1 and row.page == 1 and row.group == 0 for row in pages)
    assert any(row.source == 1 and row.page == 0 and row.group == 2 for row in pages)
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert len(written) == 1
    texts = _texts(written[0])
    joined = "\n".join(texts)
    assert "NEW-PAGE" in texts[0]
    assert "KEEP-PAGE" in texts[1]
    assert "DROP-PAGE" not in joined
    assert "PLACEHOLDER" not in joined
    assert "gone" not in result["cards"][0]["message"]
