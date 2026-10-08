"""LexCrew-PDFの窓。"""
from __future__ import annotations

import os
import threading
import time
import unicodedata
from pathlib import Path

from .session import Session, downloads_dir


def boot() -> Session:
    session = Session(downloads_dir())
    session.view()
    print("cards-ready", flush=True)
    return session


def main() -> None:
    session = boot()
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("画面を開く部品がありません。") from exc
    api = Api(session)
    page = Path(__file__).resolve().parents[2] / "ui" / "index.html"
    window = webview.create_window(
        "LexCrew-PDF",
        url=page.as_uri(),
        js_api=api,
        width=1080,
        height=760,
        min_size=(760, 520),
    )
    api.attach(window)
    webview.start()


class Api:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._window = None
        self._drop_paths: dict[str, str] = {}
        self._editor_window = None
        self._editor_gate = threading.Lock()
        self._editor_opening = False
        self._closing = False

    def attach(self, window) -> None:
        self._window = window
        window.events.loaded += self._listen_for_drops
        window.events.closing += self._save_on_close

    def _dropped(self, event) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = self._resolve_dropped_paths(files)
        if files and not paths:
            time.sleep(0.2)
            paths = self._resolve_dropped_paths(files)
        target = self._window.evaluate_js("window.__lexDrop || null")
        if not target or not paths:
            if files and not paths:
                self._window.evaluate_js(f"window.showBanner({_js('このファイルの場所を取得できません。')})")
            return
        file_index = target.get("file")
        try:
            self.session.drop_files(
                int(target["number"]),
                int(target["slot"]),
                None if file_index is None else int(file_index),
                paths,
                replace=bool(target.get("replace")),
            )
        except ValueError as exc:
            self._window.evaluate_js(f"window.showBanner({_js(str(exc))})")
            return
        self._window.evaluate_js("window.refreshApp()")

    def _resolve_dropped_paths(self, files) -> list[str]:
        from webview.dom import _dnd_state

        resolved, self._drop_paths = resolve_dropped_paths(files, list(_dnd_state.get("paths") or []), self._drop_paths)
        return resolved

    def state(self) -> dict:
        return self.session.view()

    def add_card(self) -> dict:
        return self._run(self.session.add_card)

    def set_series(self, series: str) -> dict:
        view = self._run(lambda: self.session.set_series(series))
        self._notify_editor("window.invalidatePreview()")
        return view

    def add_series_choice(self) -> dict:
        return self._run(self.session.add_series_choice)

    def add_branch(self, number: int) -> dict:
        return self._run(lambda: self.session.add_branch(int(number)))

    def delete_slot(self, number: int, slot_index: int) -> dict:
        before = self.session.editor_identity()
        view = self._run(lambda: self.session.delete_slot(int(number), int(slot_index)))
        after = self.session.editor_identity()
        if after and before != after:
            self._notify_editor(f"window.retarget({int(after['number'])}, {int(after['slot'])})")
        return view

    def move_slot(self, number: int, slot_index: int, before_number=None) -> dict:
        before = self.session.editor_identity()
        target = None if before_number is None else int(before_number)
        view = self._run(lambda: self.session.move_slot(int(number), int(slot_index), target))
        after = self.session.editor_identity()
        if after and before != after:
            self._notify_editor(f"window.retarget({int(after['number'])}, {int(after['slot'])})")
        return view

    def set_title(self, number: int, title: str, slot_index: int = 0) -> dict:
        return self._run(lambda: self.session.set_title(int(number), title, int(slot_index)))

    def rotate(self, number: int, slot_index: int = 0) -> dict:
        return self._run(lambda: self.session.rotate(int(number), int(slot_index)))

    def set_split(self, number: int, split: bool) -> dict:
        return self._run(lambda: self.session.set_split(int(number), bool(split)))

    def choose_pdf(self, number: int, slot_index: int, replace: bool = False) -> dict:
        import webview

        try:
            self.session.ensure_editable(int(number))
        except ValueError as exc:
            return {**self.session.view(), "ok": False, "message": str(exc)}
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=("PDF (*.pdf)",),
        )
        if not chosen:
            return self.session.view()

        def apply():
            if replace:
                return self.session.replace_slot(int(number), int(slot_index), list(chosen))
            view = self.session.view()
            for path in chosen:
                view = self.session.add_file(int(number), int(slot_index), path)
            return view

        return self._run(apply)

    def open_editor(self, number: int, slot_index: int = 0) -> dict:
        number = int(number)
        slot_index = int(slot_index)
        try:
            self.session.begin_edit(number, slot_index)
        except ValueError as exc:
            return {**self.session.view(), "ok": False, "message": str(exc)}
        try:
            self._present_editor(number, slot_index)
        except Exception:
            self.session.finish_edit()
            raise
        self._refresh_main()
        return self.session.view()

    def editor(self, number: int, slot_index: int = 0) -> dict:
        return self._run(lambda: self.session.editor(int(number), int(slot_index)))

    def set_pages(self, number: int, slot_index: int, pages: list) -> dict:
        return self._run(lambda: self.session.set_pages(int(number), pages, int(slot_index)))

    def reset_pages(self, number: int, slot_index: int = 0) -> dict:
        return self._run(lambda: self.session.reset_pages(int(number), int(slot_index)))

    def media(self, number: int) -> dict:
        try:
            return self.session.media(int(number))
        except ValueError as exc:
            return {"ok": False, "message": str(exc), "slots": []}
        except OSError as exc:
            return {"ok": False, "message": f"原本を開けません。{exc}", "slots": []}

    def preview(self, number: int, slot_index: int, page_index: int, zoom: float = 1.15) -> dict:
        return self._run(lambda: self.session.preview(int(number), int(slot_index), int(page_index), float(zoom)))

    def piece(self, number: int, source: int, page: int, part: int, zoom: float = 0.45, slot_index: int | None = None) -> dict:
        slot = None if slot_index is None else int(slot_index)
        return self._run(lambda: self.session.piece(int(number), int(source), int(page), int(part), float(zoom), slot))

    def generate(self) -> dict:
        return self._run(self.session.generate)

    def _run(self, fn):
        try:
            return fn()
        except ValueError as exc:
            return {**self.session.view(), "ok": False, "message": str(exc)}

    def _save_on_close(self) -> None:
        self._closing = True
        editor = self._editor_window
        self._editor_window = None
        if editor is not None:
            try:
                editor.destroy()
            except Exception:
                pass
        self.session.finish_edit()
        self.session._persist()

    def _present_editor(self, number: int, slot_index: int) -> None:
        with self._editor_gate:
            window = self._living_editor()
            if window is not None:
                self._focus_editor(window, number, slot_index)
                return
            if self._editor_opening:
                return
            self._editor_opening = True
            try:
                self._create_editor(number, slot_index)
            finally:
                self._editor_opening = False

    def _living_editor(self):
        window = self._editor_window
        if window is None:
            return None
        if window.events.closed.is_set():
            self._editor_window = None
            return None
        return window

    def _create_editor(self, number: int, slot_index: int) -> None:
        # start のあと、子ウィンドウはメイン以外のスレッドから create_window したときだけ出る。
        import webview

        context = self.session.edit_context()
        page = Path(__file__).resolve().parents[2] / "ui" / "edit.html"
        editor_api = EditorApi(self.session, self)
        window = webview.create_window(
            context.get("label") or "ページ編集",
            url=page.as_uri(),
            js_api=editor_api,
            width=1200,
            height=800,
            min_size=(900, 640),
        )
        editor_api.attach(window)
        self._editor_window = window
        script = f"window.loadEditor({int(number)}, {int(slot_index)})"

        def push() -> None:
            self._notify_editor(script)

        window.events.loaded += push
        if window.events.loaded.is_set():
            push()
        window.events.closed += self._on_editor_closed

    def _focus_editor(self, window, number: int, slot_index: int) -> None:
        context = self.session.edit_context()
        window.set_title(context.get("label") or "ページ編集")
        window.show()
        self._notify_editor(f"window.loadEditor({int(number)}, {int(slot_index)})")

    def _on_editor_closed(self) -> None:
        self._editor_window = None
        try:
            self.session.finish_edit()
        except Exception:
            pass
        self._refresh_main()

    def _refresh_main(self) -> None:
        if self._closing:
            return
        window = self._window
        if window is None:
            return
        try:
            window.evaluate_js("window.refreshApp()")
        except Exception:
            pass

    def _notify_editor(self, script: str) -> None:
        window = self._editor_window
        if window is None:
            return
        try:
            if window.events.closed.is_set():
                return
            window.evaluate_js(script)
        except Exception:
            pass

    def _listen_for_drops(self) -> None:
        self._listen_for_drops = lambda: None
        from webview.dom import DOMEventHandler
        from webview.dom.event import DOMEvent

        document = self._window.dom.document
        if not hasattr(document.events, "drop"):
            document.events.drop = DOMEvent("drop", document)
        document.events.drop += DOMEventHandler(self._dropped, prevent_default=True)


class EditorApi:
    def __init__(self, session: Session, main: Api) -> None:
        self.session = session
        self.main = main
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    def context(self) -> dict:
        return self._run(self.session.edit_context)

    def editor(self, number: int, slot_index: int = 0) -> dict:
        return self._run(lambda: self.session.editor(int(number), int(slot_index)))

    def set_pages(self, number: int, slot_index: int, pages: list) -> dict:
        result = self._run(lambda: self.session.set_pages(int(number), pages, int(slot_index)))
        self.main._refresh_main()
        return result

    def reset_pages(self, number: int, slot_index: int = 0) -> dict:
        result = self._run(lambda: self.session.reset_pages(int(number), int(slot_index)))
        self.main._refresh_main()
        return result

    def preview(self, number: int, slot_index: int, page_index: int, zoom: float = 1.15) -> dict:
        return self._run(lambda: self.session.preview(int(number), int(slot_index), int(page_index), float(zoom)))

    def piece(self, number: int, source: int, page: int, part: int, zoom: float = 0.45, slot_index: int | None = None) -> dict:
        slot = None if slot_index is None else int(slot_index)
        return self._run(lambda: self.session.piece(int(number), int(source), int(page), int(part), float(zoom), slot))

    def _run(self, fn):
        try:
            return fn()
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}


def _norm_name(name: str) -> str:
    return unicodedata.normalize("NFC", name or "")


def resolve_dropped_paths(files, pending, cache: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """同じファイルの2回目は、WebView2 がパスを付けないことがある。前回のパスを使う。"""
    remembered = dict(cache)
    by_name: dict[str, list[str]] = {}
    for name, full in pending or []:
        if full and os.path.isfile(full):
            key = _norm_name(name)
            by_name.setdefault(key, []).append(full)
            remembered[key] = full
    resolved = []
    for item in files or []:
        name = _norm_name(item.get("name") or "")
        full = item.get("pywebviewFullPath") or ""
        if not (full and os.path.isfile(full)):
            choices = by_name.get(name) or []
            full = choices[-1] if choices else remembered.get(name, "")
        if full and os.path.isfile(full):
            resolved.append(full)
            remembered[_norm_name(os.path.basename(full))] = full
    return resolved, remembered


def _js(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
