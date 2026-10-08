"""ファイル名と印の文字。種類は甲乙丙丁戊。疎甲などは見出しをそのまま使う。"""
from __future__ import annotations

import re
from pathlib import Path

SERIES = ("甲", "乙", "丙", "丁", "戊")
INITIAL_SERIES = ("甲", "乙", "丙")

_FILENAME_COLON = "："
_ILLEGAL_FILENAME = set('\\/:*?"<>|')
_MAX_TITLE_CHARS = 120
_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def fullwidth_digits(number: int) -> str:
    return str(number).translate(_FULLWIDTH_DIGITS)


def check_series(series: str) -> str:
    if series not in SERIES:
        raise ValueError(f"証拠の種類を読めません: {series}")
    return series


def canonical_template(value: str) -> str:
    """「資料N」の N が証拠番号。甲・乙だけを渡したときは「甲第N号証」にする。"""
    text = (value or "").strip().replace("Ｎ", "N")
    if text in SERIES:
        text = f"{text}第N号証"
    if "N" not in text:
        raise ValueError("証拠番号の位置に N を入れてください。例: 資料N")
    if len(text) > 40:
        raise ValueError("番号の形が長すぎます。")
    body = text.replace("N", "")
    if not body or body[0] in _ILLEGAL_FILENAME or body[0] in " ." or ord(body[0]) < 32:
        raise ValueError("N のほかに、ファイル名に使える文字を1文字以上入れてください。")
    return text


_KO_TEMPLATE = re.compile(r"^([甲乙丙丁戊])第N号証$")
_SO_TEMPLATE = re.compile(r"^疎([甲乙丙])第N号証$")


def filename_prefix(template: str) -> str:
    """甲第N号証は甲。疎甲第N号証は疎甲。別紙N や資料N は N より前の文字。"""
    text = canonical_template(template)
    so = _SO_TEMPLATE.fullmatch(text)
    if so:
        return "疎" + so.group(1)
    ko = _KO_TEMPLATE.fullmatch(text)
    if ko:
        return ko.group(1)
    head = text.split("N", 1)[0]
    prefix = "".join(ch for ch in head if ord(ch) >= 32 and ch not in _ILLEGAL_FILENAME).strip(" .")
    if prefix:
        return prefix
    body = text.replace("N", "")
    return body[0]


def apply_number(template: str, number: int) -> str:
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    return canonical_template(template).replace("N", fullwidth_digits(number))


def display_label(series: str, number: int, slot_index: int, slot_count: int) -> str:
    """カードに出す号証名。枝番スロットが複数のときだけ「の１」を付ける。"""
    base = apply_number(series, number)
    if slot_count <= 1:
        return base
    return f"{base}の{fullwidth_digits(slot_index + 1)}"


def stamp_label(series: str, number: int, branch: int | None) -> str:
    """印は全角数字。枝番が無いときは「甲第１号証」。"""
    label = apply_number(series, number)
    if branch:
        if branch < 1:
            raise ValueError("枝番が不正です。")
        label += f"の{fullwidth_digits(branch)}"
    return label


def document_title(typed: str, first_file: str | None) -> str:
    """保存した書名。空なら、その枝番の先頭 PDF から拡張子を除く。"""
    title = (typed or "").strip()
    if title:
        return title
    if not first_file:
        return ""
    name = Path(first_file).name
    if name.lower().endswith(".pdf"):
        return name[:-4]
    return name


def output_filename(series: str, number: int, branch: int | None, title: str) -> str:
    """ファイル名の番号は半角3桁。区切りは全角コロン。枝番は半角ハイフン。"""
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    prefix = filename_prefix(series)
    safe = sanitize_filename_title(title)
    if branch:
        if branch < 1:
            raise ValueError("枝番が不正です。")
        return f"{prefix}{number:03d}-{branch}{_FILENAME_COLON}{safe}.pdf"
    return f"{prefix}{number:03d}{_FILENAME_COLON}{safe}.pdf"


def sanitize_filename_title(title: str) -> str:
    """Windows のファイル名に使えない文字を除く。全角コロンは残す。"""
    kept: list[str] = []
    for ch in title or "":
        if ord(ch) < 32 or ch in _ILLEGAL_FILENAME:
            continue
        kept.append(ch)
    cleaned = "".join(kept).strip(" .")
    if len(cleaned) > _MAX_TITLE_CHARS:
        cleaned = cleaned[:_MAX_TITLE_CHARS].strip(" .")
    return cleaned or "証拠"
