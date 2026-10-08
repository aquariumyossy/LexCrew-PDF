"""証拠フォルダへの書き出し。前回このアプリが書いた PDF だけを消す。"""
from __future__ import annotations

import os
from pathlib import Path

from .plan import OutputJob
from .stamp import StampFontMissing, require_yu_mincho, stamp_sources_to_pdf

OUTPUT_DIR_NAME = "証拠"


def write_jobs(
    folder: Path,
    jobs: list[OutputJob] | tuple[OutputJob, ...],
    *,
    last_written: tuple[str, ...] | list[str],
    preserve: tuple[str, ...] | list[str] = (),
) -> dict:
    """ジョブを書き、last_written から外れた前回分だけを消す。

    游明朝が無いときは、何も書かず何も消さない。
    """
    require_yu_mincho()
    dest = folder / OUTPUT_DIR_NAME
    written: list[dict] = []
    errors: list[dict] = []
    failed = set(preserve)
    for job in jobs:
        _checked_output_path(dest, job.filename)
        tmp: Path | None = None
        try:
            data = stamp_sources_to_pdf(
                job.sources,
                job.stamp,
                tilt=job.rotation,
                split=job.split_a4,
                pages=job.pages,
            )
            dest.mkdir(parents=True, exist_ok=True)
            target = _checked_output_path(dest, job.filename)
            tmp = dest / f"{job.filename}.writing"
            tmp.write_bytes(data)
            os.replace(tmp, target)
            written.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
            })
        except StampFontMissing:
            raise
        except Exception as exc:
            failed.add(job.filename)
            errors.append({
                "filename": job.filename,
                "stampLabel": job.stamp,
                "message": _short_error(exc),
            })
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    keep = {row["filename"] for row in written} | failed
    _delete_stale(dest, last_written, keep)
    return {
        "written": written,
        "errors": errors,
        "keep": tuple(sorted(keep)),
    }


def _checked_output_path(dest: Path, filename: str) -> Path:
    if filename != Path(filename).name or not filename.endswith(".pdf") or ".." in filename:
        raise ValueError(f"出力ファイル名が不正です: {filename}")
    path = dest / filename
    if path.parent.resolve() != dest.resolve():
        raise ValueError(f"出力ファイル名が不正です: {filename}")
    return path


def _delete_stale(dest: Path, last_written, keep: set[str]) -> None:
    if not dest.is_dir():
        return
    for name in last_written:
        if name in keep:
            continue
        try:
            path = _checked_output_path(dest, name)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
    for path in list(dest.glob("*.writing")):
        if path.is_file():
            path.unlink()


def _short_error(exc: Exception) -> str:
    detail = str(exc).strip().replace("\n", " ")
    if len(detail) > 180:
        detail = detail[:180]
    return detail or "保存できませんでした。"
