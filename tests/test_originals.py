"""原本の複製。生成結果は、書いた PDF のページ本文で見る。"""
import json
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
    blocked = session.generate()
    assert blocked["ok"] is False
    assert blocked["written"] == []
    assert blocked["message"] == "原本が見つかりません：消えた.pdf"
    assert not (tmp_path / "LexCrew-PDF-Downloads" / "甲001 残す.pdf").exists()
    session.delete_slot(2, 0)
    result = session.generate()
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001 残す.pdf"
    assert output.is_file()
    assert "MIGRATED-PAGE" in _texts(output)[0]
    assert result["ok"] is True
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


def test_file_added_to_a_missing_second_branch_stays_in_that_branch(tmp_path, monkeypatch):
    first = tmp_path / "本文.pdf"
    second = tmp_path / "別紙.pdf"
    added = tmp_path / "追加.pdf"
    _pdf(first, ["SLOT0-A", "SLOT0-B"])
    _pdf(second, ["OLD-BRANCH"])
    _pdf(added, ["NEW-BRANCH"])
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(first))
    session.add_file(1, 1, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ], 0)
    assert session.layout.cards[0].pages is not None
    _stored(session, 1, 1).unlink()
    session.add_file(1, 1, str(added))
    _use_font(monkeypatch)
    result = session.generate()
    dest = tmp_path / "LexCrew-PDF-Downloads"
    written = list(dest.glob("*.pdf"))
    assert [path.name for path in written] == ["甲001-1~2 契約.pdf"]
    texts = _texts(written[0])
    assert "SLOT0-B" in texts[0]
    assert "甲第１号証の１" in texts[0]
    assert "SLOT0-A" in texts[1]
    assert "NEW-BRANCH" in texts[2]
    assert "甲第１号証の２" in texts[2]
    assert "OLD-BRANCH" not in "\n".join(texts)
    assert "NEW-BRANCH" not in texts[0]
    assert result["ok"] is True
    assert result.get("deleted", ()) == () or "削除したファイル" not in result["message"]


def test_adding_to_a_missing_branch_does_not_delete_the_previous_merged_pdf(tmp_path, monkeypatch):
    first = tmp_path / "本文.pdf"
    second = tmp_path / "別紙.pdf"
    added = tmp_path / "追加.pdf"
    _pdf(first, ["SLOT0-A", "SLOT0-B"])
    _pdf(second, ["OLD-BRANCH"])
    _pdf(added, ["NEW-BRANCH"])
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(first))
    session.add_file(1, 1, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 1},
    ], 0)
    _use_font(monkeypatch)
    first_result = session.generate()
    assert [row["filename"] for row in first_result["written"]] == ["甲001-1~2 契約.pdf"]
    output = tmp_path / "LexCrew-PDF-Downloads" / "甲001-1~2 契約.pdf"
    assert "OLD-BRANCH" in _texts(output)[2]
    _stored(session, 1, 1).unlink()
    session.add_file(1, 1, str(added))
    preview = session.preview_generate()
    assert "甲001-1~2 契約.pdf" not in preview["delete"]
    second = session.generate()
    assert output.is_file()
    texts = _texts(output)
    assert "SLOT0-B" in texts[0]
    assert "甲第１号証の１" in texts[0]
    assert "NEW-BRANCH" in texts[2]
    assert "甲第１号証の２" in texts[2]
    assert "OLD-BRANCH" not in "\n".join(texts)
    names = sorted(path.name for path in output.parent.glob("*.pdf"))
    assert names == ["甲001-1~2 契約.pdf"]
    assert "削除したファイル" not in second["message"]
    assert second["ok"] is True


def test_skipped_exhibit_name_is_not_overwritten_by_another_card(tmp_path, monkeypatch):
    later = tmp_path / "後.pdf"
    earlier = tmp_path / "先.pdf"
    _pdf(later, ["SECOND-BODY"])
    _pdf(earlier, ["FIRST-BODY"])
    session = Session(tmp_path)
    session.set_stamp_enabled(False)
    session.add_file(2, 0, str(later))
    session.set_title(2, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    output = tmp_path / "LexCrew-PDF-Downloads" / "契約.pdf"
    previous = output.read_bytes()
    assert "SECOND-BODY" in _texts(output)[0]
    session.add_file(1, 0, str(earlier))
    session.set_title(1, "契約", 0)
    _stored(session, 2).unlink()
    result = session.generate()
    assert result["ok"] is False
    assert result["written"] == []
    assert output.read_bytes() == previous
    assert "SECOND-BODY" in _texts(output)[0]
    assert not (output.parent / "契約 (2).pdf").exists()
    assert {path.name for path in output.parent.glob("*.pdf")} == {"契約.pdf"}
    assert result["message"] == "原本が見つかりません：後.pdf"
    assert str(originals_dir()) not in result["message"]


def test_replace_on_a_missing_branch_keeps_other_branch_exclusions(tmp_path, monkeypatch):
    body = tmp_path / "本文.pdf"
    missing = tmp_path / "消えた.pdf"
    replacement = tmp_path / "差替.pdf"
    _pdf(body, ["KEEP-PAGE", "DROP-PAGE"])
    _pdf(missing, ["GONE-PAGE"])
    _pdf(replacement, ["NEW-PAGE"])
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(body))
    session.add_file(1, 1, str(missing))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 0},
    ], 0)
    assert any(row.source == 0 and row.page == 1 and row.group == 0 for row in session.layout.cards[0].pages)
    _stored(session, 1, 1).unlink()
    session.drop_files(1, 1, None, [str(replacement)], replace=True)
    pages = session.layout.cards[0].pages
    assert pages is not None
    assert any(row.source == 0 and row.page == 1 and row.group == 0 for row in pages)
    assert any(row.source == 0 and row.page == 0 and row.group == 1 for row in pages)
    _use_font(monkeypatch)
    result = session.generate()
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001-1~2 契約.pdf"]
    texts = _texts(written[0])
    joined = "\n".join(texts)
    assert "KEEP-PAGE" in texts[0]
    assert "甲第１号証の１" in texts[0]
    assert "NEW-PAGE" in texts[1]
    assert "甲第１号証の２" in texts[1]
    assert "DROP-PAGE" not in joined
    assert "GONE-PAGE" not in joined
    assert result["ok"] is True


def test_unreadable_legacy_original_does_not_crash_startup(tmp_path, monkeypatch):
    scans = tmp_path / "scans"
    scans.mkdir()
    blocked = scans / "秘密.pdf"
    live = scans / "残す.pdf"
    _pdf(blocked, ["SECRET-PAGE"])
    _pdf(live, ["LIVE-PAGE"])
    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(cards[0], slots=(replace(cards[0].slots[0], files=("scans/秘密.pdf",)),))
    cards[1] = replace(cards[1], slots=(replace(cards[1].slots[0], files=("scans/残す.pdf",)),))
    save_layout(tmp_path, replace(layout, cards=tuple(cards)))
    blocked.chmod(0)
    try:
        session = Session(tmp_path)
        assert session.layout.cards[0].slots[0].files == ("scans/秘密.pdf",)
        copied = _stored(session, 2)
        assert copied.is_file()
        assert copied.read_bytes() == live.read_bytes()
        assert copied != live
        view = session.view()["cards"]
        assert "原本が見つかりません" not in view[0]["message"]
        assert str(blocked) not in view[0]["message"]
        assert "scans" not in view[0]["message"]
        _use_font(monkeypatch)
        generated = session.generate()
        message = generated["cards"][0]["message"]
        assert generated["ok"] is False
        assert generated["written"] == []
        assert message == "原本が見つかりません：秘密.pdf"
        assert generated["message"] == "原本が見つかりません：秘密.pdf"
        assert str(blocked) not in generated["message"]
        assert str(tmp_path) not in generated["message"]
        assert "原本を開けません" not in generated["message"]
        assert list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf")) == []
        assert copied.is_file()
        assert copied.read_bytes() == live.read_bytes()
    finally:
        blocked.chmod(0o644)


def test_unreadable_ledger_or_layout_never_deletes_copies(tmp_path):
    from lexcrew_pdf.originals import remember_case, release_copies

    source = tmp_path / "証拠.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    copied = _stored(session, 1)
    assert copied.is_file()
    registry = originals_dir().parent / "cases.json"
    registry.write_text("{", encoding="utf-8")
    remember_case(tmp_path / "別の案件")
    assert registry.read_text(encoding="utf-8") == "{"
    release_copies([str(copied)], live=())
    assert copied.is_file()
    assert copied.read_bytes() == _pdf_bytes(source)
    registry.write_text(json.dumps([str(tmp_path.resolve())], ensure_ascii=False), encoding="utf-8")
    layout_file = tmp_path / "LexCrew-PDF-Downloads" / "layout.json"
    layout_file.chmod(0)
    try:
        release_copies([str(copied)], live=())
        assert copied.is_file()
    finally:
        layout_file.chmod(0o644)
    layout_file.write_text("[]", encoding="utf-8")
    release_copies([str(copied)], live=())
    assert copied.is_file()
    layout_file.unlink()
    release_copies([str(copied)], live=())
    assert not copied.exists()


def _pdf_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_files_placed_in_the_store_by_hand_are_not_deleted(tmp_path):
    from lexcrew_pdf.originals import is_stored_copy

    source = tmp_path / "カード.pdf"
    _pdf(source, ["CARD-PAGE"])
    notes = originals_dir() / "notes"
    notes.mkdir(parents=True)
    planted = notes / "証拠原本.pdf"
    planted.write_bytes(b"%PDF-1.4 planted\n")
    assert is_stored_copy(tmp_path, str(planted)) is False
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    app_copy = _stored(session, 1)
    assert app_copy.is_file()
    card = session.layout.cards[0]
    session._put(replace(card, slots=(replace(card.slots[0], files=(str(planted), str(app_copy))),)))
    session.delete_slot(1, 0)
    assert planted.is_file()
    assert planted.read_bytes() == b"%PDF-1.4 planted\n"
    assert notes.is_dir()
    assert not app_copy.exists()

    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(cards[0], slots=(replace(cards[0].slots[0], files=(str(planted),)),))
    other = tmp_path / "other-case"
    other.mkdir()
    save_layout(other, replace(layout, cards=tuple(cards)))
    before = planted.read_bytes()
    adopted = Session(other)
    assert planted.is_file()
    assert planted.read_bytes() == before
    copied = _stored(adopted, 1)
    assert copied.is_file()
    assert copied.read_bytes() == before
    assert copied.parent.name != "notes"
    assert len(copied.parent.name) == 32
    adopted.delete_slot(1, 0)
    assert planted.is_file()
    assert planted.read_bytes() == before
    assert not copied.exists()


def test_editor_and_card_view_do_not_expose_the_originals_path(tmp_path):
    import json

    from lexcrew_pdf.window import Api, EditorApi

    source = tmp_path / "契約書.pdf"
    _pdf(source, ["PAGE"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    view = session.view()["cards"][0]
    stored = view["slots"][0]["files"][0]["stored"]
    assert stored == "契約書.pdf"
    rendered = json.dumps(view, ensure_ascii=False)
    assert str(originals_dir()) not in rendered
    assert str(_stored(session, 1)) not in rendered
    copied = _stored(session, 1)
    copied.write_bytes(b"not a pdf")
    api = Api(session)
    result = api.editor(1, 0)
    assert result["ok"] is False
    assert result["message"] == "原本が見つかりません：契約書.pdf"
    assert str(originals_dir()) not in result["message"]
    assert str(copied) not in result["message"]
    assert "Errno" not in result["message"]
    again = EditorApi(session, api).editor(1, 0)
    assert again["ok"] is False
    assert str(originals_dir()) not in again["message"]
    assert str(copied) not in again["message"]
    assert "Errno" not in again["message"]


def test_one_bad_original_leaves_every_output_pdf_byte_identical(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    third = tmp_path / "別.pdf"
    _pdf(first, ["FIRST-BODY"])
    _pdf(second, ["SECOND-BODY"])
    _pdf(third, ["THIRD-BODY"])
    session = Session(tmp_path)
    session.set_stamp_enabled(False)
    session.add_file(1, 0, str(first))
    session.set_title(1, "契約", 0)
    session.add_file(2, 0, str(second))
    session.set_title(2, "契約", 0)
    session.add_file(3, 0, str(third))
    session.set_title(3, "領収", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    before = {path.name: path.read_bytes() for path in dest.glob("*.pdf")}
    assert "契約.pdf" in before
    assert "契約 (2).pdf" in before
    assert "領収.pdf" in before
    _stored(session, 2).unlink()
    session.set_title(1, "変更後の契約", 0)
    session.set_first_number(8)
    preview = session.preview_generate()
    assert preview["replace"] == []
    assert preview["delete"] == []
    result = session.generate()
    assert result["ok"] is False
    assert result["written"] == []
    assert {path.name: path.read_bytes() for path in dest.glob("*.pdf")} == before
    assert result["message"] == "原本が見つかりません：後.pdf"
    assert "変更後の契約" not in result["message"]
    assert str(originals_dir()) not in result["message"]
    assert str(dest) not in result["message"]
    _pdf(second, ["SECOND-BODY"])
    session.add_file(2, 0, str(second))
    broken = _stored(session, 1)
    broken.chmod(0)
    try:
        denied = session.generate()
        assert denied["ok"] is False
        assert denied["written"] == []
        assert {path.name: path.read_bytes() for path in dest.glob("*.pdf")} == before
        assert denied["message"] == "原本が見つかりません：先.pdf"
        assert "後.pdf" not in denied["message"]
        assert str(broken) not in denied["message"]
    finally:
        broken.chmod(0o644)


def test_replace_file_keeps_the_other_branch_page_selection(tmp_path, monkeypatch):
    body = tmp_path / "本文.pdf"
    branch = tmp_path / "枝.pdf"
    replacement = tmp_path / "差替.pdf"
    _pdf(body, ["OLD-KEEP", "OLD-DROP"])
    _pdf(branch, ["BRANCH-KEEP", "BRANCH-DROP"])
    _pdf(replacement, ["NEW-PAGE"])
    session = Session(tmp_path)
    session.add_branch(1)
    session.add_file(1, 0, str(body))
    session.add_file(1, 1, str(branch))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 1, "page": 0, "part": 0, "group": 2},
        {"source": 1, "page": 1, "part": 0, "group": 0},
    ], 1)
    session.replace_file(1, 0, 0, str(replacement))
    pages = session.layout.cards[0].pages
    assert pages is not None
    assert any(row.source == 1 and row.page == 1 and row.group == 0 for row in pages)
    assert any(row.source == 1 and row.page == 0 and row.group == 2 for row in pages)
    assert not any(row.source == 0 and row.page == 1 and row.group == 0 for row in pages)
    _use_font(monkeypatch)
    result = session.generate()
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001-1~2 契約.pdf"]
    texts = _texts(written[0])
    joined = "\n".join(texts)
    assert "NEW-PAGE" in texts[0]
    assert "甲第１号証の１" in texts[0]
    assert "BRANCH-KEEP" in texts[1]
    assert "甲第１号証の２" in texts[1]
    assert "BRANCH-DROP" not in joined
    assert "OLD-DROP" not in joined
    assert "OLD-KEEP" not in joined
    assert result["ok"] is True


def test_unreadable_case_folder_never_deletes_copies(tmp_path):
    source = tmp_path / "証拠.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    copied = _stored(session, 1)
    locked = tmp_path / "読めない案件"
    locked.mkdir()
    from lexcrew_pdf.originals import remember_case

    remember_case(locked)
    locked.chmod(0)
    try:
        session.delete_slot(1, 0)
        assert copied.is_file()
        assert copied.read_bytes() == source.read_bytes()
    finally:
        locked.chmod(0o755)


def test_readonly_output_folder_and_ledger_still_start(tmp_path):
    scans = tmp_path / "scans"
    scans.mkdir()
    live = scans / "残す.pdf"
    _pdf(live, ["LIVE-PAGE"])
    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(cards[0], slots=(replace(cards[0].slots[0], files=("scans/残す.pdf",)),))
    save_layout(tmp_path, replace(layout, cards=tuple(cards)))
    output = tmp_path / "LexCrew-PDF-Downloads"
    output.chmod(0o555)
    try:
        session = Session(tmp_path)
        copied = _stored(session, 1)
        assert copied.is_file()
        assert copied.read_bytes() == live.read_bytes()
        assert not (output / "layout.json.writing").exists()
    finally:
        output.chmod(0o755)
    kept = _stored(session, 1)
    ledger = originals_dir().parent
    ledger.chmod(0o555)
    try:
        other = tmp_path / "another"
        other.mkdir()
        started = Session(other)
        assert started.folder == other
        assert kept.is_file()
        assert not (ledger / "cases.json.writing").exists()
    finally:
        ledger.chmod(0o755)


def test_editor_lists_only_the_file_that_cannot_be_opened(tmp_path):
    from lexcrew_pdf.window import EditorApi

    good = tmp_path / "残す.pdf"
    missing = tmp_path / "消えた.pdf"
    _pdf(good, ["KEEP"])
    _pdf(missing, ["GONE"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(good))
    session.add_file(1, 0, str(missing))
    gone = _stored(session, 1, 0, 1)
    gone.unlink()
    api = EditorApi(session, None)
    result = api.editor(1, 0)
    assert result["ok"] is False
    assert result["message"] == "原本が見つかりません：消えた.pdf"
    assert "残す.pdf" not in result["message"]
    assert str(originals_dir()) not in result["message"]
    assert str(gone) not in result["message"]
    fresh = tmp_path / "追加.pdf"
    _pdf(fresh, ["BACK"])
    session.replace_file(1, 0, 1, str(fresh))
    broken = _stored(session, 1, 0, 0)
    broken.write_bytes(b"not a pdf")
    again = api.editor(1, 0)
    assert again["ok"] is False
    assert again["message"] == "原本が見つかりません：残す.pdf"
    assert "追加.pdf" not in again["message"]
    assert str(broken) not in again["message"]
    assert "Errno" not in again["message"]
    leaked = FileNotFoundError(2, "No such file or directory", str(gone))

    def explode(number, slot_index=0):
        raise leaked

    session.editor = explode
    surfaced = api.editor(1, 0)
    assert surfaced["ok"] is False
    assert surfaced["message"] == "原本が見つかりません：消えた.pdf"
    assert str(gone.parent) not in surfaced["message"]
    denied = api._run(lambda: (_ for _ in ()).throw(PermissionError(13, "Permission denied", str(broken))))
    assert denied["ok"] is False
    assert denied["message"] == "原本を開けません。残す.pdf"
    assert str(broken.parent) not in denied["message"]


_ZERO_PAGE_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Count 0 /Kids [] >>
endobj
xref
0 3
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
trailer
<< /Root 1 0 R /Size 3 >>
startxref
109
%%EOF
"""


def _encrypted(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "SECRET")
    document.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    document.close()


def _output_bytes(folder: Path) -> dict[str, bytes]:
    dest = folder / "LexCrew-PDF-Downloads"
    return {path.name: path.read_bytes() for path in dest.glob("*.pdf")}


def test_original_removed_after_precheck_leaves_every_pdf(tmp_path, monkeypatch):
    import lexcrew_pdf.plan as plan

    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["FIRST"])
    _pdf(second, ["SECOND"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.set_title(1, "契約", 0)
    session.add_file(2, 0, str(second))
    session.set_title(2, "領収", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    before = _output_bytes(tmp_path)
    session.set_title(1, "変更", 0)
    copy = _stored(session, 2)
    real = plan.generation_blockers

    def drop_after(layout, folder):
        found = real(layout, folder)
        copy.unlink(missing_ok=True)
        return found

    monkeypatch.setattr(plan, "generation_blockers", drop_after)
    result = session.generate()
    assert result["ok"] is False
    assert result["written"] == []
    assert _output_bytes(tmp_path) == before
    assert result["message"] == "原本が見つかりません：後.pdf"
    assert str(copy) not in result["message"]
    assert "削除したファイル" not in result["message"]
    assert not (tmp_path / "LexCrew-PDF-Downloads" / "甲001 変更.pdf").exists()


def test_encrypted_and_empty_originals_leave_previous_pdfs(tmp_path, monkeypatch):
    good = tmp_path / "契約.pdf"
    secret = tmp_path / "秘密.pdf"
    empty = tmp_path / "空.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    empty.write_bytes(_ZERO_PAGE_PDF)
    session = Session(tmp_path)
    session.add_file(1, 0, str(good))
    session.set_title(1, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    previous = (dest / "甲001 契約.pdf").read_bytes()
    session.add_file(2, 0, str(secret))
    session.set_title(1, "変更後", 0)
    encrypted = session.generate()
    assert encrypted["ok"] is False
    assert encrypted["written"] == []
    assert (dest / "甲001 契約.pdf").read_bytes() == previous
    assert list(dest.glob("*.pdf")) == [dest / "甲001 契約.pdf"]
    assert encrypted["message"] == "原本が見つかりません：秘密.pdf"
    assert "削除したファイル" not in encrypted["message"]
    assert str(originals_dir()) not in encrypted["message"]
    session.delete_slot(2, 0)
    session.add_file(2, 0, str(empty))
    blank = session.generate()
    assert blank["ok"] is False
    assert blank["written"] == []
    assert (dest / "甲001 契約.pdf").read_bytes() == previous
    assert list(dest.glob("*.pdf")) == [dest / "甲001 契約.pdf"]
    assert blank["message"] == "原本が見つかりません：空.pdf"
    assert "削除したファイル" not in blank["message"]


def test_encrypted_original_message_stays_on_refresh(tmp_path, monkeypatch):
    import base64

    from lexcrew_pdf.window import Api, _editor_error

    good = tmp_path / "契約.pdf"
    secret = tmp_path / "秘密.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    session = Session(tmp_path)
    _use_font(monkeypatch)
    session.add_file(1, 0, str(good))
    session.set_title(1, "契約", 0)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    previous = (dest / "甲001 契約.pdf").read_bytes()
    session.add_file(2, 0, str(secret))
    api = Api(session)
    media = api.media(2)
    assert media["ok"] is False
    assert media["slots"] == []
    assert media["message"] == "原本が見つかりません：秘密.pdf"
    assert "document closed" not in media["message"]
    thumb = api.media(1)
    assert thumb.get("ok") is not False
    assert base64.b64decode(thumb["slots"][0]["thumb"]).startswith(b"\xff\xd8")
    blocked = api.generate()
    assert blocked["ok"] is False
    assert blocked["written"] == []
    assert blocked["message"] == "原本が見つかりません：秘密.pdf"
    assert (dest / "甲001 契約.pdf").read_bytes() == previous
    assert list(dest.glob("*.pdf")) == [dest / "甲001 契約.pdf"]
    editor = api.editor(2, 0)
    assert editor["ok"] is False
    assert editor["message"] == "原本が見つかりません：秘密.pdf"
    assert "document closed" not in editor["message"]
    session.rotate(2, 0)
    session.add_branch(2)
    again = api.media(2)
    assert again["ok"] is False
    assert again["slots"] == []
    assert again["message"] == "原本が見つかりません：秘密.pdf"
    assert "document closed" not in again["message"]
    assert (dest / "甲001 契約.pdf").read_bytes() == previous
    assert list(dest.glob("*.pdf")) == [dest / "甲001 契約.pdf"]
    session.remove_file(2, 0, 0)
    cleared = api.media(2)
    assert "原本が見つかりません" not in str(cleared.get("message", ""))
    assert "document closed" not in str(cleared)
    assert session.view()["cards"][1]["message"] == ""
    assert _editor_error(ValueError("document closed or encrypted")) == "原本を開けません。"
    assert _editor_error(ValueError("原本が見つかりません：秘密.pdf")) == "原本が見つかりません：秘密.pdf"
    assert _editor_error(ValueError("原本を開けません。秘密.pdf")) == "原本を開けません。秘密.pdf"


def test_a_later_stamp_failure_does_not_replace_the_earlier_pdf(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["FIRST"])
    _pdf(second, ["SECOND"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.set_title(1, "契約", 0)
    session.add_file(2, 0, str(second))
    session.set_title(2, "領収", 0)
    monkeypatch.setattr("lexcrew_pdf.write.require_stamp_font", lambda *args, **kwargs: None)
    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", lambda *args, **kwargs: b"%PDF-1.4\nkept\n")
    assert session.generate()["ok"] is True
    before = _output_bytes(tmp_path)
    stored = _stored(session, 2)
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise FileNotFoundError(2, "No such file or directory", str(stored))
        return b"%PDF-1.4\nreplaced\n"

    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", boom)
    session.set_title(1, "変更", 0)
    result = session.generate()
    assert result["ok"] is False
    assert result["written"] == []
    assert _output_bytes(tmp_path) == before
    rendered = json.dumps(result["cards"], ensure_ascii=False)
    assert str(stored) not in rendered
    assert str(originals_dir()) not in rendered
    assert "Errno" not in rendered
    assert "後.pdf" in result["cards"][1]["message"]
    assert "削除したファイル" not in result["message"]


def test_generate_confirms_again_when_the_files_become_usable(tmp_path, monkeypatch):
    from lexcrew_pdf.window import Api

    monkeypatch.setattr("lexcrew_pdf.window.os.startfile", lambda path: None, raising=False)

    source = tmp_path / "契約.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    previous = (dest / "甲001 契約.pdf").read_bytes()
    stored = _stored(session, 1)
    stored.chmod(0)
    try:
        preview = session.preview_generate()
        assert preview == {"replace": [], "delete": [], "keep": []}
        stored.chmod(0o644)
        session.set_title(1, "領収", 0)
        held = Api(session).generate(preview)
        assert held["needsConfirm"] is True
        assert held.get("written") == []
        assert "甲001 契約.pdf" in held["delete"]
        assert (dest / "甲001 契約.pdf").read_bytes() == previous
        assert not (dest / "甲001 領収.pdf").exists()
        done = Api(session).generate(held)
        assert done["ok"] is True
        assert not (dest / "甲001 契約.pdf").exists()
        assert (dest / "甲001 領収.pdf").is_file()
    finally:
        stored.chmod(0o644)


def test_delete_during_generation_waits_until_the_snapshot_is_written(tmp_path, monkeypatch):
    import threading

    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["FIRST"])
    _pdf(second, ["SECOND"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(2, 0, str(second))
    monkeypatch.setattr("lexcrew_pdf.write.require_stamp_font", lambda *args, **kwargs: None)
    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", lambda *args, **kwargs: b"%PDF-1.4\nkept\n")
    assert session.generate()["ok"] is True
    started = threading.Event()
    finished = threading.Event()
    seen = []

    def slow(source_paths, *args, **kwargs):
        import time
        seen.append(all(Path(path).is_file() for path in source_paths))
        started.set()
        time.sleep(0.3)
        seen.append(all(Path(path).is_file() for path in source_paths))
        return b"%PDF-1.4\nnext\n"

    monkeypatch.setattr("lexcrew_pdf.write.stamp_sources_to_pdf", slow)
    copy = _stored(session, 2)

    def deleter():
        assert started.wait(5)
        session.delete_slot(2, 0)
        finished.set()

    thread = threading.Thread(target=deleter)
    thread.start()
    result = session.generate()
    assert result["ok"] is True
    assert seen == [True, True, True, True]
    assert finished.wait(5)
    thread.join(5)
    names = sorted(path.name for path in (tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert names == ["甲001 先.pdf", "甲002 後.pdf"]
    assert all(path.read_bytes() == b"%PDF-1.4\nnext\n" for path in (tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert not copy.is_file()


def test_missing_file_in_a_slot_can_be_replaced_or_removed(tmp_path):
    cover = tmp_path / "cover.pdf"
    body = tmp_path / "body.pdf"
    replacement = tmp_path / "new.pdf"
    _pdf(cover, ["COVER"])
    _pdf(body, ["BODY"])
    _pdf(replacement, ["NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(cover))
    session.add_file(1, 0, str(body))
    _stored(session, 1, 0, 1).unlink()
    files = session.view()["cards"][0]["slots"][0]["files"]
    assert [item["name"] for item in files] == ["cover.pdf", "body.pdf"]
    assert files[1]["missing"] is True
    assert "missing" not in files[0]
    session.replace_file(1, 0, 1, str(replacement))
    assert [item["name"] for item in session.view()["cards"][0]["slots"][0]["files"]] == ["cover.pdf", "new.pdf"]
    session.add_file(1, 0, str(body))
    _stored(session, 1, 0, 2).unlink()
    session.remove_file(1, 0, 2)
    assert [Path(item).name for item in session.layout.cards[0].slots[0].files] == ["cover.pdf", "new.pdf"]


def test_replacing_the_first_file_keeps_its_place(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    new = tmp_path / "差替.pdf"
    _pdf(first, ["KEEP", "DROP"])
    _pdf(second, ["SECOND"])
    _pdf(new, ["NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 1, "part": 0, "group": 0},
        {"source": 1, "page": 0, "part": 0, "group": 1},
    ], 0)
    assert session.layout.cards[0].pages is not None
    session.replace_file(1, 0, 0, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001 契約.pdf"]
    texts = _texts(written[0])
    assert "NEW" in texts[0]
    assert "甲第１号証" in texts[0]
    assert "SECOND" in texts[1]
    assert "FIRST" not in "\n".join(texts)


def test_copy_directory_that_cannot_be_written_keeps_the_card(tmp_path):
    from lexcrew_pdf.window import Api

    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["A"])
    _pdf(second, ["B"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(2, 0, str(second))
    copied = _stored(session, 1)
    copied.parent.chmod(0o555)
    try:
        view = Api(session).delete_slot(1, 0)
        assert view["ok"] is False
        assert str(copied) not in view["message"]
        assert str(originals_dir()) not in view["message"]
        assert "Errno" not in view["message"]
        assert copied.is_file()
        assert copied.read_bytes() == first.read_bytes()
        filled = [
            card["number"]
            for card in view["cards"]
            if any(slot["files"] for slot in card["slots"])
        ]
        assert filled == [1, 2]
        assert view["cards"][0]["slots"][0]["files"][0]["name"] == "先.pdf"
        assert view["cards"][1]["slots"][0]["files"][0]["name"] == "後.pdf"
    finally:
        copied.parent.chmod(0o755)


def test_piece_error_hides_the_originals_path(tmp_path):
    from lexcrew_pdf.window import Api

    source = tmp_path / "本文.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    stored = _stored(session, 1)
    stored.unlink()
    result = Api(session).piece(1, 0, 0, 0)
    assert result["ok"] is False
    assert "本文.pdf" in result["message"]
    assert str(stored) not in result["message"]
    assert str(originals_dir()) not in result["message"]
    assert "Errno" not in result["message"]


def test_view_does_not_read_whole_files_and_generation_still_blocks(tmp_path, monkeypatch):
    source = tmp_path / "本文.pdf"
    _pdf(source, ["PAGE"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    previous = (tmp_path / "LexCrew-PDF-Downloads" / "甲001 契約.pdf").read_bytes()
    calls = []
    real = Path.read_bytes

    def spy(self, *args, **kwargs):
        calls.append(self.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", spy)
    session.view()
    session.view()
    assert "本文.pdf" not in calls
    stored = _stored(session, 1)
    stored.chmod(0)
    try:
        blocked = session.generate()
        assert blocked["ok"] is False
        assert blocked["written"] == []
        assert (tmp_path / "LexCrew-PDF-Downloads" / "甲001 契約.pdf").read_bytes() == previous
        assert blocked["message"] == "原本が見つかりません：本文.pdf"
    finally:
        stored.chmod(0o644)


def test_readonly_startup_reuses_the_same_copy(tmp_path):
    scans = tmp_path / "scans"
    scans.mkdir()
    live = scans / "残す.pdf"
    _pdf(live, ["LIVE-PAGE"])
    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(cards[0], slots=(replace(cards[0].slots[0], files=("scans/残す.pdf",)),))
    save_layout(tmp_path, replace(layout, cards=tuple(cards)))
    output = tmp_path / "LexCrew-PDF-Downloads"
    output.chmod(0o555)
    try:
        Session(tmp_path)
        Session(tmp_path)
        copies = list(originals_dir().rglob("残す.pdf"))
        assert len(copies) == 1
        assert copies[0].read_bytes() == live.read_bytes()
    finally:
        output.chmod(0o755)


def test_unreadable_output_directory_still_starts(tmp_path):
    output = tmp_path / "LexCrew-PDF-Downloads"
    output.mkdir()
    (output / "layout.json").write_bytes(b"{}")
    output.chmod(0)
    try:
        session = Session(tmp_path)
        assert session.folder == tmp_path
        assert session.notice == "配置ファイルを読めません。"
    finally:
        output.chmod(0o755)


def test_publish_failure_restores_every_pdf_and_does_not_duplicate(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["FIRST"])
    _pdf(second, ["SECOND"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.set_title(1, "契約", 0)
    session.add_file(2, 0, str(second))
    session.set_title(2, "領収", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    before = _output_bytes(tmp_path)
    recorded = session.layout.last_written
    session.set_title(1, "変更", 0)
    real = os.replace
    armed = {"on": True}

    def flaky(src, dst):
        if armed["on"] and str(dst).endswith("甲002 領収.pdf") and str(src).endswith(".writing"):
            raise OSError(13, "Permission denied", str(dst))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    failed = session.generate()
    armed["on"] = False
    dest = tmp_path / "LexCrew-PDF-Downloads"
    assert failed["ok"] is False
    assert failed["written"] == []
    assert _output_bytes(tmp_path) == before
    assert session.layout.last_written == recorded
    assert not (dest / "甲001 変更.pdf").exists()
    assert not list(dest.glob("*.rollback"))
    assert " (2)" not in failed["message"]
    assert str(dest) not in failed["message"]
    assert "削除したファイル" not in failed["message"]
    again = session.generate()
    assert again["ok"] is True
    names = sorted(path.name for path in dest.glob("*.pdf"))
    assert names == ["甲001 変更.pdf", "甲002 領収.pdf"]
    assert all(" (2)" not in name for name in names)


def test_failed_card_delete_save_keeps_the_card_in_memory(tmp_path):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["A"])
    _pdf(second, ["B"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(2, 0, str(second))
    output = tmp_path / "LexCrew-PDF-Downloads"
    output.chmod(0o555)
    try:
        with pytest.raises(OSError):
            session.delete_slot(1, 0)
        filled = [
            (card.number, Path(card.slots[0].files[0]).name)
            for card in session.layout.cards
            if card.slots[0].files
        ]
        assert filled == [(1, "先.pdf"), (2, "後.pdf")]
    finally:
        output.chmod(0o755)
    session.set_title(2, "残る", 0)
    reloaded = Session(tmp_path)
    refilled = [
        (card.number, Path(card.slots[0].files[0]).name)
        for card in reloaded.layout.cards
        if card.slots[0].files
    ]
    assert refilled == [(1, "先.pdf"), (2, "後.pdf")]
    assert reloaded.layout.cards[1].slots[0].title == "残る"


def test_replacing_an_excluded_file_still_outputs_it(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    new = tmp_path / "差替.pdf"
    _pdf(first, ["OLD"])
    _pdf(second, ["SECOND"])
    _pdf(new, ["NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 0},
        {"source": 1, "page": 0, "part": 0, "group": 1},
    ], 0)
    assert session.layout.cards[0].pages is not None
    session.replace_file(1, 0, 0, str(new))
    pages = session.layout.cards[0].pages
    assert pages is not None
    assert any(row.source == 0 and row.group != 0 for row in pages)
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001 契約.pdf"]
    texts = _texts(written[0])
    assert "NEW" in texts[0]
    assert "甲第１号証" in texts[0]
    assert "SECOND" in texts[1]
    assert "OLD" not in "\n".join(texts)


def test_replacing_when_the_first_saved_page_is_excluded(tmp_path, monkeypatch):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    new = tmp_path / "差替.pdf"
    _pdf(first, ["DROP", "KEEP"])
    _pdf(second, ["SECOND"])
    _pdf(new, ["NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 0, "page": 0, "part": 0, "group": 0},
        {"source": 0, "page": 1, "part": 0, "group": 1},
        {"source": 1, "page": 0, "part": 0, "group": 1},
    ], 0)
    session.replace_file(1, 0, 0, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001 契約.pdf"]
    texts = _texts(written[0])
    assert "NEW" in texts[0]
    assert "甲第１号証" in texts[0]
    assert "SECOND" in texts[1]
    assert "KEEP" not in "\n".join(texts)
    assert "DROP" not in "\n".join(texts)


def test_unusable_original_can_be_removed(tmp_path):
    good = tmp_path / "本文.pdf"
    secret = tmp_path / "秘密.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    session = Session(tmp_path)
    session.add_file(1, 0, str(good))
    session.add_file(1, 0, str(secret))
    files = session.view()["cards"][0]["slots"][0]["files"]
    assert files[1]["name"] == "秘密.pdf"
    assert files[1]["unusable"] is True
    assert "missing" not in files[1]
    assert "unusable" not in files[0]
    screen = (Path(__file__).resolve().parents[1] / "ui" / "app.js").read_text(encoding="utf-8")
    assert "file.unusable" in screen
    with pytest.raises(ValueError, match="この原本は外せません。"):
        session.remove_file(1, 0, 0)
    session.remove_file(1, 0, 1)
    left = [Path(item).name for item in session.layout.cards[0].slots[0].files]
    assert left == ["本文.pdf"]


def test_replacing_an_unusable_original_clears_the_missing_message(tmp_path):
    good = tmp_path / "本文.pdf"
    secret = tmp_path / "秘密.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    session = Session(tmp_path)
    session.add_file(1, 0, str(secret))
    blocked = session.generate()
    assert blocked["ok"] is False
    assert blocked["cards"][0]["message"] == "原本が見つかりません：秘密.pdf"
    session.replace_file(1, 0, 0, str(good))
    message = session.view()["cards"][0]["message"]
    assert "原本が見つかりません" not in message
    assert "秘密.pdf" not in message


def test_slot_delete_keeps_every_copy_when_one_cannot_be_removed(tmp_path):
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    _pdf(first, ["A"])
    _pdf(second, ["B"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    copies = [_stored(session, 1, 0, 0), _stored(session, 1, 0, 1)]
    copies[1].parent.chmod(0o555)
    try:
        with pytest.raises(ValueError, match="原本を消せません。") as caught:
            session.delete_slot(1, 0)
        assert str(originals_dir()) not in str(caught.value)
        assert str(copies[0]) not in str(caught.value)
        assert str(copies[1]) not in str(caught.value)
        assert copies[0].read_bytes() == first.read_bytes()
        assert copies[1].read_bytes() == second.read_bytes()
        names = [Path(item).name for item in session.layout.cards[0].slots[0].files]
        assert names == ["先.pdf", "後.pdf"]
    finally:
        copies[1].parent.chmod(0o755)


def test_renaming_after_confirmation_asks_again(tmp_path, monkeypatch):
    from lexcrew_pdf.window import Api

    monkeypatch.setattr("lexcrew_pdf.window.os.startfile", lambda path: None, raising=False)
    source = tmp_path / "契約.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    previous = (dest / "甲001 契約.pdf").read_bytes()
    session.set_title(1, "変更", 0)
    preview = Api(session).preview_generate()
    assert preview["delete"] == ["甲001 契約.pdf"]
    assert preview["writing"] == ["甲001 変更.pdf"]
    session.set_title(1, "別", 0)
    held = Api(session).generate(preview)
    assert held["needsConfirm"] is True
    assert held.get("written") == []
    assert held["writing"] == ["甲001 別.pdf"]
    assert (dest / "甲001 契約.pdf").read_bytes() == previous
    assert not (dest / "甲001 別.pdf").exists()
    assert not (dest / "甲001 変更.pdf").exists()
    done = Api(session).generate(held)
    assert done["ok"] is True
    assert not (dest / "甲001 契約.pdf").exists()
    assert (dest / "甲001 別.pdf").is_file()
    assert not (dest / "甲001 変更.pdf").exists()


def test_permission_change_updates_the_list_without_a_new_mtime(tmp_path):
    source = tmp_path / "本文.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    assert "unusable" not in session.view()["cards"][0]["slots"][0]["files"][0]
    stored = _stored(session, 1)
    before = stored.stat()
    stored.chmod(0)
    try:
        after = stored.stat()
        assert after.st_size == before.st_size
        assert after.st_mtime_ns == before.st_mtime_ns
        assert session.view()["cards"][0]["slots"][0]["files"][0]["unusable"] is True
    finally:
        stored.chmod(before.st_mode)
    assert "unusable" not in session.view()["cards"][0]["slots"][0]["files"][0]


def test_failed_branch_delete_save_keeps_the_slot(tmp_path):
    first = tmp_path / "先.pdf"
    second = tmp_path / "枝.pdf"
    _pdf(first, ["A"])
    _pdf(second, ["B"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_branch(1)
    session.add_file(1, 1, str(second))
    output = tmp_path / "LexCrew-PDF-Downloads"
    output.chmod(0o555)
    try:
        with pytest.raises(OSError):
            session.delete_slot(1, 0)
        names = [Path(slot.files[0]).name for slot in session.layout.cards[0].slots]
        assert names == ["先.pdf", "枝.pdf"]
    finally:
        output.chmod(0o755)
    session.set_title(1, "残る", 0)
    reloaded = Session(tmp_path)
    slots = reloaded.layout.cards[0].slots
    assert [Path(slot.files[0]).name for slot in slots] == ["先.pdf", "枝.pdf"]
    assert slots[0].title == "残る"


def test_stale_delete_failure_keeps_the_published_name(tmp_path, monkeypatch):
    source = tmp_path / "契約.pdf"
    _pdf(source, ["BODY"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(source))
    session.set_title(1, "契約", 0)
    _use_font(monkeypatch)
    assert session.generate()["ok"] is True
    dest = tmp_path / "LexCrew-PDF-Downloads"
    old = dest / "甲001 契約.pdf"
    previous = old.read_bytes()
    session.set_title(1, "改", 0)
    real = Path.unlink
    armed = {"on": True}

    def flaky(self, *args, **kwargs):
        if armed["on"] and self.name == "甲001 契約.pdf":
            raise OSError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky)
    failed = session.generate()
    armed["on"] = False
    names = sorted(path.name for path in dest.glob("*.pdf"))
    assert (dest / "甲001 改.pdf").is_file()
    assert old.read_bytes() == previous
    assert names == ["甲001 契約.pdf", "甲001 改.pdf"]
    assert all(" (2)" not in name for name in names)
    assert set(session.layout.last_written) == {"甲001 契約.pdf", "甲001 改.pdf"}
    assert failed["ok"] is False
    assert "保存しました" in failed["message"]
    assert "保存できませんでした" not in failed["message"]
    assert "削除できませんでした。甲001 契約.pdf" in failed["message"]
    assert str(old) not in failed["message"]
    again = session.generate()
    assert again["ok"] is True
    left = sorted(path.name for path in dest.glob("*.pdf"))
    assert left == ["甲001 改.pdf"]
    assert " (2)" not in again["message"]


def test_replacing_an_excluded_first_file_uses_the_editor_page_order(tmp_path, monkeypatch):
    """edit.js は出すページを先に、除くページを後に保存する。"""
    first = tmp_path / "先.pdf"
    second = tmp_path / "後.pdf"
    new = tmp_path / "差替.pdf"
    _pdf(first, ["OLD"])
    _pdf(second, ["SECOND"])
    _pdf(new, ["NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(second))
    session.set_title(1, "契約", 0)
    session.set_pages(1, [
        {"source": 1, "page": 0, "part": 0, "group": 1},
        {"source": 0, "page": 0, "part": 0, "group": 0},
    ], 0)
    assert session.layout.cards[0].pages is not None
    session.replace_file(1, 0, 0, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert [path.name for path in written] == ["甲001 契約.pdf"]
    texts = _texts(written[0])
    assert "NEW" in texts[0]
    assert "甲第１号証" in texts[0]
    assert "SECOND" in texts[1]
    assert "OLD" not in "\n".join(texts)


def test_replace_slot_clears_the_missing_message(tmp_path):
    good = tmp_path / "本文.pdf"
    secret = tmp_path / "secret.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    session = Session(tmp_path)
    session.add_file(1, 0, str(secret))
    blocked = session.generate()
    assert blocked["ok"] is False
    assert blocked["cards"][0]["message"] == "原本が見つかりません：secret.pdf"
    session.replace_slot(1, 0, [str(good)])
    message = session.view()["cards"][0]["message"]
    assert "原本が見つかりません" not in message
    assert "secret.pdf" not in message

    other = tmp_path / "dropped"
    other.mkdir()
    dropped = Session(other)
    dropped.add_file(1, 0, str(secret))
    assert dropped.generate()["cards"][0]["message"] == "原本が見つかりません：secret.pdf"
    dropped.drop_files(1, 0, None, [str(good)], replace=True)
    cleared = dropped.view()["cards"][0]["message"]
    assert "原本が見つかりません" not in cleared
    assert "secret.pdf" not in cleared


def test_same_copy_referenced_twice_can_be_deleted(tmp_path):
    left = tmp_path / "a"
    right = tmp_path / "b"
    left.mkdir()
    right.mkdir()
    first = left / "契約.pdf"
    second = right / "契約.pdf"
    _pdf(first, ["SAME"])
    second.write_bytes(first.read_bytes())
    layout = default_layout()
    cards = list(layout.cards)
    cards[0] = replace(
        cards[0],
        slots=(replace(cards[0].slots[0], files=("a/契約.pdf", "b/契約.pdf")),),
    )
    save_layout(tmp_path, replace(layout, cards=tuple(cards)))
    session = Session(tmp_path)
    files = session.layout.cards[0].slots[0].files
    assert files[0] == files[1]
    copy = Path(files[0])
    assert copy.is_file()
    assert copy.read_bytes() == first.read_bytes()
    session.delete_slot(1, 0)
    assert not copy.exists()


def test_comma_in_a_file_name_stays_in_the_card_message(tmp_path):
    comma = tmp_path / "請求書、領収書.pdf"
    neighbor = tmp_path / "隣.pdf"
    good = tmp_path / "本文.pdf"
    other = tmp_path / "別.pdf"
    _encrypted(comma)
    _encrypted(neighbor)
    _pdf(good, ["BODY"])
    _pdf(other, ["OTHER"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(comma))
    session.add_file(1, 0, str(neighbor))
    blocked = session.generate()
    assert blocked["ok"] is False
    assert "請求書、領収書.pdf" in blocked["cards"][0]["message"]
    session.replace_file(1, 0, 1, str(good))
    message = session.view()["cards"][0]["message"]
    assert message == "原本が見つかりません：請求書、領収書.pdf"
    session.replace_file(1, 0, 0, str(other))
    cleared = session.view()["cards"][0]["message"]
    assert "原本が見つかりません" not in cleared
    assert "請求書、領収書.pdf" not in cleared


def _editor_pages(kept, excluded, group):
    """edit.js の commit。出すページを先に、除くページを後に書く。"""
    pages = [{"source": source, "page": 0, "part": 0, "group": group} for source in kept]
    pages.extend({"source": source, "page": 0, "part": 0, "group": 0} for source in excluded)
    return pages


def test_replacing_an_excluded_middle_file_stays_inside_its_branch(tmp_path, monkeypatch):
    first = tmp_path / "a.pdf"
    middle = tmp_path / "mid.pdf"
    third = tmp_path / "c.pdf"
    branch = tmp_path / "d.pdf"
    new = tmp_path / "new.pdf"
    _pdf(first, ["A"])
    _pdf(middle, ["MID"])
    _pdf(third, ["C"])
    _pdf(branch, ["D"])
    _pdf(new, ["BODY-NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(middle))
    session.add_file(1, 0, str(third))
    session.add_branch(1)
    session.add_file(1, 1, str(branch))
    session.set_pages(1, _editor_pages([0, 2], [1], 1), 0)
    saved = session.layout.cards[0].pages
    assert saved is not None
    assert [(row.source, row.group) for row in saved] == [(3, 2), (0, 1), (2, 1), (1, 0)]
    session.replace_file(1, 0, 1, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    written = list((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf"))
    assert len(written) == 1
    texts = _texts(written[0])
    assert len(texts) == 4
    assert "A" in texts[0] and "甲第１号証の１" in texts[0]
    assert "BODY-NEW" in texts[1] and "甲第１号証" not in texts[1]
    assert "C" in texts[2]
    assert "D" in texts[3] and "甲第１号証の２" in texts[3]


def test_replacing_an_excluded_last_file_stays_inside_its_branch(tmp_path, monkeypatch):
    first = tmp_path / "a.pdf"
    middle = tmp_path / "mid.pdf"
    last = tmp_path / "c.pdf"
    branch = tmp_path / "d.pdf"
    new = tmp_path / "new.pdf"
    _pdf(first, ["A"])
    _pdf(middle, ["MID"])
    _pdf(last, ["C"])
    _pdf(branch, ["D"])
    _pdf(new, ["BODY-NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(middle))
    session.add_file(1, 0, str(last))
    session.add_branch(1)
    session.add_file(1, 1, str(branch))
    session.set_pages(1, _editor_pages([0, 1], [2], 1), 0)
    session.replace_file(1, 0, 2, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    texts = _texts(next((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf")))
    assert "A" in texts[0] and "甲第１号証の１" in texts[0]
    assert "MID" in texts[1]
    assert "BODY-NEW" in texts[2] and "甲第１号証" not in texts[2]
    assert "D" in texts[3] and "甲第１号証の２" in texts[3]


def test_replacing_an_excluded_middle_file_keeps_its_place_on_one_card(tmp_path, monkeypatch):
    first = tmp_path / "a.pdf"
    middle = tmp_path / "mid.pdf"
    third = tmp_path / "c.pdf"
    new = tmp_path / "new.pdf"
    _pdf(first, ["A"])
    _pdf(middle, ["MID"])
    _pdf(third, ["C"])
    _pdf(new, ["BODY-NEW"])
    session = Session(tmp_path)
    session.add_file(1, 0, str(first))
    session.add_file(1, 0, str(middle))
    session.add_file(1, 0, str(third))
    session.set_pages(1, _editor_pages([0, 2], [1], 1), 0)
    saved = session.layout.cards[0].pages
    assert saved is not None
    assert [(row.source, row.group) for row in saved] == [(0, 1), (2, 1), (1, 0)]
    session.replace_file(1, 0, 1, str(new))
    _use_font(monkeypatch)
    result = session.generate()
    assert result["ok"] is True
    texts = _texts(next((tmp_path / "LexCrew-PDF-Downloads").glob("*.pdf")))
    assert "A" in texts[0] and "甲第１号証" in texts[0]
    assert "BODY-NEW" in texts[1] and "甲第１号証" not in texts[1]
    assert "C" in texts[2]


def test_same_display_name_lists_the_unusable_file_once(tmp_path):
    left = tmp_path / "a"
    right = tmp_path / "b"
    left.mkdir()
    right.mkdir()
    good = left / "契約.pdf"
    secret = right / "契約.pdf"
    _pdf(good, ["BODY"])
    _encrypted(secret)
    session = Session(tmp_path)
    session.add_file(1, 0, str(good))
    session.add_file(1, 0, str(secret))
    blocked = session.generate()
    assert blocked["ok"] is False
    assert blocked["cards"][0]["message"] == "原本が見つかりません：契約.pdf"
    assert blocked["message"].count("契約.pdf") == 1
