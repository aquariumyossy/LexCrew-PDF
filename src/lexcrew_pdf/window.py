"""LexCrew-PDFの窓。"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import unicodedata
from ctypes import wintypes
from pathlib import Path

from .layout import FILE_DIALOG_TYPES, require_source_file
from .session import Session, downloads_dir

# ハンドルを関数の中だけに置くと、ガベージコレクションでミューテックスが外れる。
_instance_handle = None
_APP_USER_MODEL_ID = "LexCrew.PDF"
_WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def output_root() -> Path:
    override = os.environ.get("LEXCREW_FOLDER", "").strip()
    if override:
        return Path(override)
    return downloads_dir()


def boot() -> Session:
    session = Session(output_root())
    session.view()
    print("cards-ready", flush=True)
    return session


def tell(message: str) -> None:
    if sys.stdout is None or sys.stderr is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW(None, message, "LexCrew-PDF", 0x40)
        return
    print(message, file=sys.stderr)


def acquire_single_instance() -> bool:
    global _instance_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, "Local\\LexCrew-PDF")
    error = ctypes.get_last_error()
    if not handle:
        raise SystemExit("起動を確認できません。")
    if error == 183:
        kernel32.CloseHandle(handle)
        return False
    _instance_handle = handle
    return True


def focus_existing() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    hwnd = user32.FindWindowW(None, "LexCrew-PDF")
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)
    return bool(user32.SetForegroundWindow(hwnd))


def set_app_user_model_id() -> None:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
    shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)


def load_webview():
    try:
        import webview
        from webview.platforms import winforms
    except ImportError as exc:
        raise SystemExit("画面を開く部品がありません。") from exc
    if getattr(winforms, "renderer", None) != "edgechromium":
        raise SystemExit(
            "Microsoft Edge WebView2 ランタイムが必要です。\n" + _WEBVIEW2_URL
        )
    return webview


def main() -> None:
    try:
        _run()
    except SystemExit as exc:
        if isinstance(exc.code, str) and exc.code:
            tell(exc.code)
            raise SystemExit(1) from None
        raise
    except Exception:
        tell("起動できません。")
        raise SystemExit(1) from None


def _run() -> None:
    if not acquire_single_instance():
        if not focus_existing():
            tell("すでに起動しています。")
        return
    icon = package_root() / "LexCrew-PDF.ico"
    # pythonw のまま ID だけ付けると、対応するショートカットが無い開発起動でタスクバーの絵が崩れる。
    if icon.is_file():
        set_app_user_model_id()
    session = boot()
    webview = load_webview()
    api = Api(session)
    page = package_root() / "ui" / "index.html"
    window = webview.create_window(
        "LexCrew-PDF",
        url=page.as_uri(),
        js_api=api,
        width=1080,
        height=760,
        min_size=(760, 520),
    )
    api.attach(window)
    if icon.is_file():
        webview.start(icon=str(icon))
    else:
        webview.start()


def reveal_folder(folder: Path) -> None:
    try:
        os.startfile(os.fspath(folder))
    except OSError:
        return


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

    def set_grayscale(self, enabled: bool) -> dict:
        view = self._run(lambda: self.session.set_grayscale(bool(enabled)))
        self._notify_editor("window.reloadAppearance()")
        return view

    def set_first_number(self, number: int) -> dict:
        view = self._run(lambda: self.session.set_first_number(number))
        self._notify_editor("window.invalidatePreview()")
        return view

    def set_merge_branches(self, enabled: bool) -> dict:
        return self._run(lambda: self.session.set_merge_branches(bool(enabled)))

    def set_page_number_style(self, enabled, color, size, font, place, pattern="n/N") -> dict:
        from .stamp import StampFontMissing

        def save():
            try:
                return self.session.set_page_number_style(bool(enabled), color, size, font, place, pattern)
            except StampFontMissing as exc:
                return {**self.session.view(), "ok": False, "message": str(exc)}

        view = self._run(save)
        if view.get("ok") is not False:
            self._notify_editor("window.reloadAppearance()")
        return view

    def set_stamp_style(self, color, size, font) -> dict:
        from .stamp import StampFontMissing

        def save():
            try:
                return self.session.set_stamp_style(color, size, font)
            except StampFontMissing as exc:
                return {**self.session.view(), "ok": False, "message": str(exc)}

        view = self._run(save)
        if view.get("ok") is not False:
            self._notify_editor("window.reloadAppearance()")
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
            file_types=FILE_DIALOG_TYPES,
        )
        if not chosen:
            return self.session.view()

        def apply():
            for path in chosen:
                require_source_file(Path(path))
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

    def piece(
        self,
        number: int,
        source: int,
        page: int,
        part: int,
        zoom: float = 0.45,
        slot_index: int | None = None,
        output_index: int | None = None,
    ) -> dict:
        slot = None if slot_index is None else int(slot_index)
        index = None if output_index is None else int(output_index)
        return self._run(lambda: self.session.piece(
            int(number), int(source), int(page), int(part), float(zoom), slot, index,
        ))

    def generate(self) -> dict:
        result = self._run(self.session.generate)
        written = result.get("written") or ()
        output = result.get("outputDir") or ""
        if written and output:
            reveal_folder(Path(output))
        return result

    def clear(self) -> dict:
        editor = None
        with self.session._lock:
            editor = self._editor_window
            self._editor_window = None
            view = self.session.clear()
        if editor is not None:
            try:
                editor.destroy()
            except Exception:
                pass
        return view

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
        page = package_root() / "ui" / "edit.html"
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
        return self._commit(lambda: self.session.set_pages(int(number), pages, int(slot_index)))

    def reset_pages(self, number: int, slot_index: int = 0) -> dict:
        return self._commit(lambda: self.session.reset_pages(int(number), int(slot_index)))

    def add_mask(self, number: int, slot_index: int, source: int, page: int, part: int, x: float, y: float, w: float, h: float) -> dict:
        return self._commit(lambda: self.session.add_mask(
            int(number), int(slot_index), int(source), int(page), int(part), x, y, w, h,
        ))

    def remove_mask(self, number: int, slot_index: int, source: int, page: int, x: float, y: float, w: float, h: float) -> dict:
        return self._commit(lambda: self.session.remove_mask(
            int(number), int(slot_index), int(source), int(page), x, y, w, h,
        ))

    def set_trim(
        self,
        number: int,
        slot_index: int,
        source: int,
        page: int,
        part: int,
        top: int,
        right: int,
        bottom: int,
        left: int,
    ) -> dict:
        return self._commit(lambda: self.session.set_trim(
            int(number),
            int(slot_index),
            int(source),
            int(page),
            int(part),
            top,
            right,
            bottom,
            left,
        ))

    def set_skew(self, number: int, slot_index: int, source: int, page: int, tenths: int) -> dict:
        return self._commit(lambda: self.session.set_skew(
            int(number),
            int(slot_index),
            int(source),
            int(page),
            tenths,
        ))

    def set_stamp_offset(self, number: int, slot_index: int, dx: int, dy: int) -> dict:
        from .stamp import StampFontMissing

        def save():
            try:
                return self.session.set_stamp_offset(int(number), int(slot_index), dx, dy)
            except StampFontMissing as exc:
                return {"ok": False, "message": str(exc)}

        return self._commit(save)

    def _commit(self, fn):
        try:
            with self.session._lock:
                if self.main._living_editor() is None:
                    return self.session.view()
                result = fn()
        except ValueError as exc:
            result = {"ok": False, "message": str(exc)}
        if self.main._living_editor() is not None:
            self.main._refresh_main()
        return result

    def preview(self, number: int, slot_index: int, page_index: int, zoom: float = 1.15, bare: bool = False) -> dict:
        return self._run(lambda: self.session.preview(
            int(number), int(slot_index), int(page_index), float(zoom), bool(bare),
        ))

    def piece(
        self,
        number: int,
        source: int,
        page: int,
        part: int,
        zoom: float = 0.45,
        slot_index: int | None = None,
        output_index: int | None = None,
    ) -> dict:
        slot = None if slot_index is None else int(slot_index)
        index = None if output_index is None else int(output_index)
        return self._run(lambda: self.session.piece(
            int(number), int(source), int(page), int(part), float(zoom), slot, index,
        ))

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
