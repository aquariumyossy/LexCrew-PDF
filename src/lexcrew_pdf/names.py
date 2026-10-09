"""ファイル名と印の文字。種類は甲乙丙丁戊。疎甲や乙Aは、その見出しをファイル名の頭に使う。"""
from __future__ import annotations

import re
from pathlib import Path

SERIES = ("甲", "乙", "丙", "丁", "戊")
INITIAL_SERIES = ("甲", "乙", "丙")

_ILLEGAL_FILENAME = set('\\/:*?"<>|')
# mints の提出マニュアル。拡張子を含めたファイル名の上限。
MAX_FILENAME_CHARS = 100
_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")
FIRST_NUMBER_MAX = 9999
_LATIN_LETTER = r"[A-Za-z\uff21-\uff3a\uff41-\uff5a]"
_KO_TEMPLATE = re.compile(rf"^([甲乙丙丁戊])({_LATIN_LETTER})?第N号証$")
_SO_TEMPLATE = re.compile(rf"^疎([甲乙丙])({_LATIN_LETTER})?第N号証$")
# 原本名の先頭だけ。甲1 、甲第2号証_、乙3の1 、甲001-1~3 を外し、甲府や金額は残す。
_EXHIBIT_SEP = r"[ \t\u3000:：_＿]*"
_EXHIBIT_TAIL = r"(?:[ \t\u3000:：_＿]+|$)"
_LEADING_EXHIBIT = re.compile(
    r"^(?:疎)?[甲乙丙丁戊][A-Za-zＡ-Ｚａ-ｚ]?"
    r"(?:"
    rf"第[0-9０-９]+号証(?:の[0-9０-９]+)?{_EXHIBIT_SEP}"
    rf"|[0-9０-９]+号証(?:の[0-9０-９]+)?{_EXHIBIT_SEP}"
    rf"|[0-9０-９]+(?:の[0-9０-９]+|-[0-9０-９]+(?:[~〜～][0-9０-９]+)?){_EXHIBIT_TAIL}"
    rf"|[0-9０-９]+{_EXHIBIT_TAIL}"
    r")"
)


def fullwidth_digits(number: int) -> str:
    return str(number).translate(_FULLWIDTH_DIGITS)


def shown_number(first_number: int, ordinal: int) -> int:
    """並びの1からの番号を、開始番号からの証拠番号にする。"""
    return first_number + ordinal - 1


def require_first_number(value) -> int:
    """画面から来た開始番号。7.0 は 7 にし、7.5 や真偽値は拒む。"""
    if isinstance(value, bool):
        raise ValueError("開始番号は1から9999までの整数です。")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("開始番号は1から9999までの整数です。")
        value = int(value)
    if isinstance(value, int) and 1 <= value <= FIRST_NUMBER_MAX:
        return value
    raise ValueError("開始番号は1から9999までの整数です。")


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


def filename_prefix(template: str) -> str:
    """甲第N号証は甲。乙A第N号証は乙A。疎甲第N号証は疎甲。別紙N は N より前の文字。"""
    text = canonical_template(template)
    so = _SO_TEMPLATE.fullmatch(text)
    if so:
        return "疎" + so.group(1) + _halfwidth_latin(so.group(2) or "")
    ko = _KO_TEMPLATE.fullmatch(text)
    if ko:
        return ko.group(1) + _halfwidth_latin(ko.group(2) or "")
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


def branch_number(slot_index: int, slot_count: int) -> int | None:
    """スロットが2つ以上のとき、1始まりの枝番。1つなら枝番なし。"""
    if slot_count <= 1:
        return None
    return slot_index + 1


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


def exhibit_number(series: str, number: int, branch: int | None) -> str:
    """ファイル名の号証番号。甲001、甲001-1、乙A001。印の文言や範囲は含めない。"""
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    return filename_prefix(series) + _number_token(number, branch, None)


def document_title(typed: str, first_file: str | None) -> str:
    """保存した書名。空なら、その枝番の先頭 PDF から拡張子を除く。

    原本名の先頭に号証番号があるときは外す。手入力の書名はそのまま残す。
    """
    title = (typed or "").strip()
    if title:
        return title
    if not first_file:
        return ""
    name = Path(first_file).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return strip_leading_exhibit_number(name)


def strip_leading_exhibit_number(name: str) -> str:
    """先頭の号証番号と、その直後の区切りを外す。無ければそのまま。"""
    text = (name or "").strip()
    match = _LEADING_EXHIBIT.match(text)
    if not match:
        return text
    return text[match.end():].strip()


def filename_stem_token(
    series: str,
    number: int,
    branch: int | None,
    branch_end: int | None = None,
) -> str:
    """甲001-1~3。書名と拡張子は付けない。カードの「含めて出力」に使う。"""
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    return filename_prefix(series) + _number_token(number, branch, branch_end)


def output_filename(
    series: str,
    number: int,
    branch: int | None,
    title: str,
    *,
    branch_end: int | None = None,
) -> str:
    """ファイル名の番号は半角3桁。枝番は半角ハイフン。範囲は 1~3。

    番号と書名のあいだは半角スペース。
    `.pdf` を含めて 100 文字に収まるよう、書名の後ろを切る。
    """
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    prefix = filename_prefix(series)
    head = prefix + _number_token(number, branch, branch_end)
    suffix = ".pdf"
    budget = MAX_FILENAME_CHARS - len(head) - 1 - len(suffix)
    safe = _fit_filename_title(title, budget)
    return f"{head} {safe}{suffix}"


def sanitize_filename_title(title: str) -> str:
    """Windows のファイル名に使えない文字を除く。全角コロンは残す。長さは切らない。"""
    kept: list[str] = []
    for ch in title or "":
        if ord(ch) < 32 or ch in _ILLEGAL_FILENAME:
            continue
        kept.append(ch)
    return "".join(kept).strip(" .")


def _number_token(number: int, branch: int | None, branch_end: int | None) -> str:
    token = f"{number:03d}"
    if branch is None:
        if branch_end is not None:
            raise ValueError("枝番が不正です。")
        return token
    if branch < 1:
        raise ValueError("枝番が不正です。")
    if branch_end is None or branch_end == branch:
        return f"{token}-{branch}"
    if branch_end < branch:
        raise ValueError("枝番が不正です。")
    return f"{token}-{branch}~{branch_end}"


def _fit_filename_title(title: str, budget: int) -> str:
    """書名を予算内へ切る。切れ端の空白とピリオドは残さない。空なら「証拠」。"""
    cleaned = sanitize_filename_title(title)
    if not cleaned:
        cleaned = "証拠"
    if budget < 1:
        budget = 1
    if len(cleaned) > budget:
        cleaned = cleaned[:budget].strip(" .")
    if not cleaned:
        cleaned = "証拠" if budget >= 2 else "証"
        cleaned = cleaned[:budget]
    return cleaned


def _halfwidth_latin(text: str) -> str:
    """全角の英字だけを半角にする。乙Ａ のファイル名は乙A。"""
    chars = []
    for ch in text:
        code = ord(ch)
        if 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(ch)
    return "".join(chars)
