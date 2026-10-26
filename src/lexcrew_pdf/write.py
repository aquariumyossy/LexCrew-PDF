"""出力フォルダへの書き出し。前回このアプリが書いた PDF だけを消し、それ以外の同名は置き換えない。"""
from __future__ import annotations

import os
from pathlib import Path

from .layout import OUTPUT_DIR_NAME
from .plan import OutputJob
from .stamp import (
    DEFAULT_PAGE_NUMBERS,
    PageNumberStyle,
    StampFontMissing,
    StampStyle,
    require_stamp_font,
    skew_lookup,
    stamp_sources_to_pdf,
    trim_lookup,
)


def write_jobs(
    folder: Path,
    jobs: list[OutputJob] | tuple[OutputJob, ...],
    *,
    last_written: tuple[str, ...] | list[str],
    preserve: tuple[str, ...] | list[str] = (),
    grayscale: bool = False,
    style=None,
    page_numbers: PageNumberStyle | None = None,
    stamp_enabled: bool = True,
    fit_stamp: bool = False,
) -> dict:
    """ジョブを書き、last_written から外れた前回分だけを消す。

    選んだ印のフォントが無いときは、何も書かず何も消さない。
    印を出さないときは、印のフォントが無くても書く。頁番号を付けるときだけ、そのフォントを要る。
    """
    if stamp_enabled:
        require_stamp_font(style)
    numbers = page_numbers if isinstance(page_numbers, PageNumberStyle) else DEFAULT_PAGE_NUMBERS
    if numbers.enabled:
        require_stamp_font(StampStyle(numbers.color, numbers.size, numbers.font))
    dest = folder / OUTPUT_DIR_NAME
    written: list[dict] = []
    errors: list[dict] = []
    replaced: list[str] = []
    owned = set(last_written)
    rendered: list[tuple[OutputJob, bytes]] = []
    for job in jobs:
        _checked_output_path(dest, job.filename)
        target = dest / job.filename
        try:
            exists = target.is_file()
        except OSError as exc:
            errors.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
                "message": _short_error(exc),
            })
            continue
        if exists and job.filename not in owned:
            errors.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
                "message": "同じ名前のファイルがあるため、書けませんでした。",
            })
            continue
        try:
            data = stamp_sources_to_pdf(
                job.sources,
                job.stamp,
                tilt=job.rotation,
                split=job.split_a4,
                pages=job.pages,
                grayscale=grayscale,
                stamp_dx=job.stamp_dx,
                stamp_dy=job.stamp_dy,
                masks=job.masks,
                trims=trim_lookup(job.trims),
                skews=skew_lookup(job.skews),
                style=style,
                parts=job.parts or None,
                page_numbers=numbers,
                draw_stamp=stamp_enabled,
                fit_stamp=fit_stamp,
            )
        except StampFontMissing:
            raise
        except Exception as exc:
            errors.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
                "message": _short_error(exc),
            })
            continue
        rendered.append((job, data))
    # 一つでも失敗したら、置き換えも削除もしない。前回の証拠 PDF を残す。
    if errors:
        return {
            "written": [],
            "errors": errors,
            "keep": tuple(last_written),
            "replaced": (),
            "deleted": (),
        }
    staged: list[tuple[OutputJob, Path, Path, bool]] = []
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for job, data in rendered:
            target = _checked_output_path(dest, job.filename)
            tmp = dest / f"{job.filename}.writing"
            tmp.write_bytes(data)
            staged.append((job, target, tmp, target.is_file()))
        for job, target, tmp, replacing in staged:
            os.replace(tmp, target)
            if replacing:
                replaced.append(job.filename)
            written.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
            })
    finally:
        for _job, _target, tmp, _replacing in staged:
            tmp.unlink(missing_ok=True)
    keep = {row["filename"] for row in written} | set(preserve)
    deleted = _delete_stale(dest, last_written, keep)
    return {
        "written": written,
        "errors": errors,
        "keep": tuple(sorted(keep)),
        "replaced": tuple(replaced),
        "deleted": tuple(deleted),
    }


def foreign_output_names(folder: Path, last_written: tuple[str, ...] | list[str]) -> set[str]:
    """出力フォルダにある、このアプリが前回書いていない PDF。"""
    dest = folder / OUTPUT_DIR_NAME
    if not dest.is_dir():
        return set()
    owned = set(last_written)
    found: set[str] = set()
    for path in dest.iterdir():
        if path.is_file() and path.suffix.lower() == ".pdf" and path.name not in owned:
            found.add(path.name)
    return found


def pending_writes(
    folder: Path,
    filenames: list[str] | tuple[str, ...],
    last_written: tuple[str, ...] | list[str],
    kept: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    retain: tuple[str, ...] | list[str] = (),
) -> dict:
    """書く前に、置き換えるファイル、消すファイル、残して別名にするファイルを返す。

    retain は失敗する生成が消してはいけない前回分。置き換え一覧には入れない。
    """
    dest = folder / OUTPUT_DIR_NAME
    owned = set(last_written)
    planned = set(filenames) | set(retain)
    replace = [name for name in filenames if name in owned and (dest / name).is_file()]
    delete = [name for name in last_written if name not in planned and (dest / name).is_file()]
    return {
        "replace": replace,
        "delete": delete,
        "keep": [{"existing": existing, "writing": writing} for existing, writing in kept],
    }


def _checked_output_path(dest: Path, filename: str) -> Path:
    if filename != Path(filename).name or not filename.endswith(".pdf") or ".." in filename:
        raise ValueError(f"出力ファイル名が不正です: {filename}")
    path = dest / filename
    if path.parent.resolve() != dest.resolve():
        raise ValueError(f"出力ファイル名が不正です: {filename}")
    return path


def _delete_stale(dest: Path, last_written, keep: set[str]) -> list[str]:
    if not dest.is_dir():
        return []
    deleted: list[str] = []
    for name in last_written:
        if name in keep:
            continue
        try:
            path = _checked_output_path(dest, name)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
            deleted.append(name)
    for path in list(dest.glob("*.writing")):
        if path.is_file():
            path.unlink()
    return deleted


def _short_error(exc: Exception) -> str:
    from .layout import missing_original_message, unreadable_original_message

    filename = getattr(exc, "filename", None)
    name = Path(str(filename)).name if filename else ""
    if isinstance(exc, FileNotFoundError):
        return missing_original_message((name,)) if name else "原本が見つかりません："
    text = str(exc)
    if name and (isinstance(exc, OSError) or "/" in text or "\\" in text or "Errno" in text):
        return unreadable_original_message((name,))
    if "/" in text or "\\" in text or "Errno" in text:
        return "原本を開けません。"
    detail = text.strip().replace("\n", " ")
    if len(detail) > 180:
        detail = detail[:180]
    return detail or "保存できませんでした。"
