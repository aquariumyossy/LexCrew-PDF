"""出力 PDF の文書情報は、原本が持っていても空にする。"""
import os

import fitz
import pytest

from lexcrew_pdf.stamp import stamp_sources_to_pdf, yu_mincho_path

_SECRETS = (
    "TITLE-X",
    "AUTHOR-X",
    "SUBJECT-X",
    "KEYWORDS-X",
    "CREATOR-X",
    "PRODUCER-X",
    "XMP-SECRET",
    "TOPSECRET-FILE",
    "JS-SECRET",
    "NAME-JS",
    "SECRET-NOTE",
    "20200101120000",
    "20210101120000",
)


def _use_stamp_font(monkeypatch) -> None:
    if os.path.isfile(yu_mincho_path()):
        return
    fallback = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    if not os.path.isfile(fallback):
        pytest.skip("游明朝がありません")
    monkeypatch.setattr("lexcrew_pdf.stamp.yu_mincho_path", lambda: fallback)


def _rich_pdf(path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "BODY-TEXT")
    page.add_text_annot((120, 120), "SECRET-NOTE")
    document.set_metadata({
        "title": "TITLE-X",
        "author": "AUTHOR-X",
        "subject": "SUBJECT-X",
        "keywords": "KEYWORDS-X",
        "creator": "CREATOR-X",
        "producer": "PRODUCER-X",
        "creationDate": "D:20200101120000+09'00'",
        "modDate": "D:20210101120000+09'00'",
    })
    document.set_xml_metadata(
        "<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>"
        "<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
        "<rdf:Description>XMP-SECRET</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    document.embfile_add("secret.txt", b"TOPSECRET-FILE", filename="secret.txt")
    action = document.get_new_xref()
    document.update_object(action, "<</S/JavaScript/JS(app.alert('JS-SECRET');)>>")
    document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{action} 0 R")
    named = document.get_new_xref()
    document.update_object(named, "<</S/JavaScript/JS(app.alert('NAME-JS');)>>")
    # 保存前の Names はインライン辞書のことがある。添付を残したまま JavaScript を足す。
    kind, current = document.xref_get_key(document.pdf_catalog(), "Names")
    javascript = f"<</Names[(evil){named} 0 R]>>"
    if kind == "xref":
        names_xref = int(current.split()[0])
        document.xref_set_key(names_xref, "JavaScript", javascript)
    else:
        names_xref = document.get_new_xref()
        body = current.strip()
        inner = body[2:-2] if body.startswith("<<") and body.endswith(">>") else body
        document.update_object(names_xref, f"<<{inner}/JavaScript{javascript}>>")
        document.xref_set_key(document.pdf_catalog(), "Names", f"{names_xref} 0 R")
    document.save(path)
    document.close()


def test_stamped_output_drops_source_metadata(tmp_path, monkeypatch):
    _use_stamp_font(monkeypatch)
    source = tmp_path / "原本.pdf"
    _rich_pdf(source)
    original = fitz.open(source)
    try:
        assert original.metadata["title"] == "TITLE-X"
        assert original.metadata["author"] == "AUTHOR-X"
        assert "XMP-SECRET" in (original.get_xml_metadata() or "")
        assert original.embfile_count() == 1
        assert [annot.info.get("content") for annot in original[0].annots()] == ["SECRET-NOTE"]
        assert original.xref_get_key(original.pdf_catalog(), "OpenAction")[0] != "null"
    finally:
        original.close()

    data = stamp_sources_to_pdf([str(source)], "甲第１号証")
    for secret in _SECRETS:
        assert secret.encode() not in data
    output = fitz.open(stream=data, filetype="pdf")
    try:
        assert output.page_count == 1
        assert "BODY-TEXT" in output[0].get_text()
        assert "甲第１号証" in output[0].get_text()
        info = output.metadata
        for key in ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate"):
            assert info[key] == ""
        assert output.get_xml_metadata() in ("", None)
        assert output.embfile_count() == 0
        assert output.embfile_names() == []
        assert output[0].first_annot is None
        assert output.xref_get_key(output.pdf_catalog(), "OpenAction")[0] == "null"
        catalog = output.pdf_catalog()
        kind, names = output.xref_get_key(catalog, "Names")
        if kind == "xref":
            names_xref = int(names.split()[0])
            assert output.xref_get_key(names_xref, "JavaScript")[0] == "null"
            assert output.xref_get_key(names_xref, "EmbeddedFiles")[0] == "null"
        for xref in range(1, output.xref_length()):
            assert output.xref_get_key(xref, "S")[1] != "/JavaScript"
    finally:
        output.close()
