"""ファイル名と印の文字。種類は甲乙丙丁戊。疎甲や乙Aは、その見出しをファイル名の頭に使う。

N の無い形（別紙、参考資料）は、その文字をすべての印にする。ファイル名には番号を出さない。
"""
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
    """「資料N」の N が証拠番号。甲・乙だけを渡したときは「甲第N号証」にする。

    N が無いときは、その文字をすべてのカードの印にする。例: 別紙、参考資料。
    """
    text = (value or "").strip().replace("Ｎ", "N")
    if text in SERIES:
        text = f"{text}第N号証"
    if len(text) > 40:
        raise ValueError("番号の形が長すぎます。")
    if "N" not in text:
        if not text:
            raise ValueError("番号の形を入力してください。")
        if any(ord(ch) < 32 or ch in _ILLEGAL_FILENAME for ch in text):
            raise ValueError("番号の形に、ファイル名に使えない文字があります。")
        return text
    body = text.replace("N", "")
    if not body or body[0] in _ILLEGAL_FILENAME or body[0] in " ." or ord(body[0]) < 32:
        raise ValueError("N のほかに、ファイル名に使える文字を1文字以上入れてください。")
    return text


def template_has_number(value: str) -> bool:
    """N がある形だけ、カードごとに番号が変わる。"""
    return "N" in canonical_template(value)


def exhibit_filenames_use_numbers(template: str, *, stamp_enabled: bool) -> bool:
    """印を付け、かつ形に N があるときだけ、ファイル名の頭に番号を出す。"""
    return bool(stamp_enabled) and template_has_number(template)


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
    text = canonical_template(template)
    if "N" not in text:
        return text
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    return text.replace("N", fullwidth_digits(number))


def branch_number(slot_index: int, slot_count: int) -> int | None:
    """スロットが2つ以上のとき、1始まりの枝番。1つなら枝番なし。"""
    if slot_count <= 1:
        return None
    return slot_index + 1


def display_label(series: str, number: int, slot_index: int, slot_count: int) -> str:
    """カードに出す号証名。枝番スロットが複数のときだけ「の１」を付ける。

    N が無い形は、枝番があっても同じ文字のまま。
    """
    if not template_has_number(series):
        return canonical_template(series)
    base = apply_number(series, number)
    if slot_count <= 1:
        return base
    return f"{base}の{fullwidth_digits(slot_index + 1)}"


def stamp_label(series: str, number: int, branch: int | None) -> str:
    """印は全角数字。枝番が無いときは「甲第１号証」。

    N が無い形は、番号も枝番も付けず、その文字だけ。
    """
    if not template_has_number(series):
        return canonical_template(series)
    label = apply_number(series, number)
    if branch:
        if branch < 1:
            raise ValueError("枝番が不正です。")
        label += f"の{fullwidth_digits(branch)}"
    return label


def exhibit_number(series: str, number: int, branch: int | None) -> str:
    """ファイル名の号証番号。甲001、甲001-1、乙A001。印の文言や範囲は含めない。"""
    _require_numbered_template(series)
    if number < 1:
        raise ValueError("証拠番号が不正です。")
    return filename_prefix(series) + _number_token(number, branch, None)


# 長いものから見る。.jpeg を .jpg より先に外す。
_SOURCE_SUFFIXES = (".jpeg", ".jpg", ".png", ".pdf")


def document_title(typed: str, first_file: str | None) -> str:
    """保存した書名。空なら、その枝番の先頭原本から拡張子を除く。

    原本名の先頭に号証番号があるときは外す。手入力の書名はそのまま残す。
    PDF と同じく、JPG と PNG の拡張子も除く。
    """
    title = (typed or "").strip()
    if title:
        return title
    if not first_file:
        return ""
    return strip_leading_exhibit_number(_without_source_suffix(Path(first_file).name))


def _without_source_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in _SOURCE_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


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
    _require_numbered_template(series)
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
    _require_numbered_template(series)
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


def plain_pdf_name(title: str) -> str:
    """衝突を足す前の書名ファイル。空の書名は「証拠.pdf」。"""
    suffix = ".pdf"
    stem = _fit_filename_title(title, MAX_FILENAME_CHARS - len(suffix))
    return f"{stem}{suffix}"


def title_only_filename(title: str, taken: set[str] | None = None) -> str:
    """書名だけのファイル名。taken にあれば「書名 (2).pdf」。渡した集合へ足す。

    印を出さないときと、N の無い形のときに使う。空の書名は「証拠.pdf」。
    CON.pdf のような Windows の装置名は、最初から「 (2)」を付ける。
    """
    return allocate_pdf_name(plain_pdf_name(title), taken)


class FilenameBook:
    """1回の表示、または1回の生成で、ファイル名をカードの順に決める。"""

    def __init__(
        self,
        template: str,
        stamp_enabled: bool = True,
        blocked: set[str] | None = None,
    ) -> None:
        self.template = canonical_template(template)
        self.numbered = exhibit_filenames_use_numbers(self.template, stamp_enabled=stamp_enabled)
        self.blocked = set(blocked or ())
        self.taken: set[str] = set(self.blocked)
        self.kept: list[tuple[str, str]] = []
        self.naturals: dict[str, str] = {}

    def claim(
        self,
        shown: int,
        branch: int | None,
        title: str,
        branch_end: int | None = None,
    ) -> str:
        if self.numbered:
            natural = output_filename(self.template, shown, branch, title, branch_end=branch_end)
        else:
            natural = plain_pdf_name(title)
        chosen = allocate_pdf_name(natural, self.taken, self.blocked, self.kept)
        self.naturals[chosen] = natural
        return chosen

    def natural_of(self, filename: str) -> str:
        """衝突の接尾辞を足す前のファイル名。欄の書名へ戻すときに使う。"""
        return self.naturals.get(filename, filename)

    def token(self, shown: int, branch: int | None, branch_end: int | None, filename: str) -> str:
        """「含めて出力」の印。番号があるときは甲001-1~3。無いときはファイル名そのもの。"""
        if self.numbered:
            return filename_stem_token(self.template, shown, branch, branch_end)
        return filename


_WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_COLLISION_SUFFIX = re.compile(r" \(\d+\)$")


def allocate_pdf_name(
    natural: str,
    taken: set[str] | None = None,
    blocked: set[str] | None = None,
    kept: list[tuple[str, str]] | None = None,
) -> str:
    """natural が使えなければ「 (2)」から空いている名前を返す。taken へ足す。

    blocked にある名前は残すファイル。そのときは kept に (残す名前, 書く名前) を足す。
    """
    blocked = blocked or set()
    if not _pdf_name_taken(natural, taken):
        if taken is not None:
            taken.add(natural)
        return natural
    existing = _blocked_filename(natural, blocked)
    skipped = [existing] if existing else []
    number = 2
    while number <= 9999:
        candidate = _insert_filename_mark(natural, f" ({number})")
        existing = _blocked_filename(candidate, blocked)
        if existing:
            skipped.append(existing)
        if not _pdf_name_taken(candidate, taken) and len(candidate) <= MAX_FILENAME_CHARS:
            if taken is not None:
                taken.add(candidate)
            if kept is not None:
                for existing in skipped:
                    kept.append((existing, candidate))
            return candidate
        number += 1
    raise ValueError("同じ書名が多すぎます。")


def edited_title(text: str, current_filename: str, natural_name: str, *, numbered: bool) -> str:
    """ファイル名欄の文字列を、保存する書名に戻す。

    割り当てが足した「 (2)」だけを外す。書名自体の「 (2)」は残す。
    """
    bare = _pdf_stem(text)
    shown = _pdf_stem(current_filename)
    natural = _pdf_stem(natural_name)
    if natural and shown.startswith(natural):
        suffix = shown[len(natural):]
        if _COLLISION_SUFFIX.fullmatch(suffix) and bare.endswith(suffix) and len(bare) > len(suffix):
            bare = bare[: -len(suffix)]
    if numbered:
        match = re.match(r"^[^\d]+\d{3}(?:-\d+(?:~\d+)?)?[ ：:](.+)$", bare)
        if match:
            return match.group(1)
    return bare


def _pdf_stem(name: str) -> str:
    text = (name or "").strip()
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    return text.strip()


def _pdf_name_taken(filename: str, taken: set[str] | None) -> bool:
    if _is_windows_device(filename):
        return True
    if taken is None:
        return False
    return any(_same_pdf_name(filename, item) for item in taken)


def _same_pdf_name(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _blocked_filename(filename: str, blocked: set[str]) -> str | None:
    for item in blocked:
        if _same_pdf_name(filename, item):
            return item
    return None


def _is_windows_device(filename: str) -> bool:
    return _pdf_stem(filename).upper() in _WINDOWS_DEVICES


def _insert_filename_mark(natural: str, mark: str) -> str:
    base = _pdf_stem(natural)
    suffix = ".pdf"
    budget = MAX_FILENAME_CHARS - len(suffix) - len(mark)
    if budget < 1:
        budget = 1
    trimmed = base[:budget].strip(" .")
    if not trimmed:
        trimmed = "証拠"[:budget]
    return f"{trimmed}{mark}{suffix}"


def _require_numbered_template(series: str) -> str:
    text = canonical_template(series)
    if "N" not in text:
        raise ValueError("この形には番号がありません。")
    return text


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
