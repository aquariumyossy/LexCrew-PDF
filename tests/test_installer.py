"""利用者向けセットアップの約束。危険な削除や権限の変更で落ちる。"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _code(path: Path) -> str:
    lines = []
    for line in _read(path).splitlines():
        stripped = line.strip()
        if stripped.startswith(";") or stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def _section(code: str, uninstall: bool) -> str:
    if uninstall:
        chunk = code.split('Section "Uninstall"', 1)[1]
    else:
        chunk = code.split('Section "Uninstall"', 1)[0].split("\nSection\n", 1)[1]
    return chunk.split("\nSectionEnd", 1)[0]


def _function(code: str, name: str) -> str:
    marker = f"Function {name}\n"
    start = code.index(marker)
    rest = code[start + len(marker) :]
    return rest[: rest.index("\nFunctionEnd")]


def test_version_is_1_4_1():
    project = _read(ROOT / "pyproject.toml")
    assert 'version = "1.4.1"' in project
    assert '"pymupdf==1.28.2"' in project
    assert '"pywebview==6.2.1"' in project


def test_dev_launchers_stay():
    assert (ROOT / "起動.bat").is_file()
    assert (ROOT / "停止.bat").is_file()
    assert (ROOT / "packaging" / "LexCrew-PDF.bat").is_file()
    assert (ROOT / "packaging" / "停止.bat").is_file()
    assert not (ROOT / "installer" / "Stop-App.ps1").exists()


def test_build_packs_the_tree_from_before_smoke():
    build = _read(ROOT / "packaging" / "build.ps1")
    assert "LexCrew-PDF-Setup-$version.exe" in build
    assert "LexCrew-PDF-$version-win64.zip" in build
    assert "python-3.13.17-embed-amd64.zip" in build
    assert "https://www.python.org/ftp/python/3.13.17/" in build
    assert "9E35319BFFEDAB8B36AD44D8F377CB4F1733BCEC257A0B6D04D94F01486DDB38" in build
    assert "python-3.13.14" not in build
    assert "makensis" in build
    assert ".Replace('\\','/')" not in build
    assert "LexCrew-PDF.bat" in build
    assert "停止.bat" in build
    assert "Stop-App.ps1" not in build
    assert "/DSTOP" not in build
    assert "$packedFiles" in build
    smoke = build.index("smoke.ps1")
    assert build.index("CreateFromDirectory") < smoke
    assert build.index("$packedFiles") < smoke
    assert build.index("packedFiles.Contains") > smoke
    usage = build.index("installer\\使い方.txt")
    assert smoke < usage
    assert usage < build.index("& $makensis")


_FAKE_PYTHON = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

log = Path(os.environ["LEXCREW_FAKE_LOG"])
args = sys.argv[1:]
with log.open("a", encoding="utf-8") as handle:
    handle.write("PY " + " ".join(args) + "\\n")
text = " ".join(args)
if "importlib.metadata" in text:
    print(os.environ.get("LEXCREW_PYMUPDF", "1.28.2"))
    print(os.environ.get("LEXCREW_PYWEBVIEW", "6.2.1"))
    raise SystemExit(0)
if "-m" in args and "pip" in args:
    if any(arg.startswith("pymupdf==") for arg in args):
        kind = "deps"
    elif "setuptools" in args:
        kind = "tools"
    elif any(arg.startswith("pip==") or arg.startswith("pip>=") for arg in args):
        kind = "upgrade"
    else:
        kind = "other"
    with log.open("a", encoding="utf-8") as handle:
        handle.write("PIP " + kind + "\\n")
    if kind == "upgrade":
        code = int(os.environ.get("LEXCREW_PIP_EXIT", "0"))
        if code == 0:
            root = Path(sys.argv[0]).resolve().parent
            vendor = root / "Lib" / "site-packages" / "pip" / "_vendor"
            vendor.mkdir(parents=True, exist_ok=True)
            certifi = os.environ.get("LEXCREW_CERTIFI", "2026.10.19")
            (vendor / "vendor.txt").write_text(
                "    certifi==" + certifi + "\\n",
                encoding="utf-8",
            )
        raise SystemExit(code)
    raise SystemExit(0)
raise SystemExit(0)
"""

_BUILD_WRAPPER = r"""
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
New-Item -ItemType File -Force -Path $env:LEXCREW_FAKE_LOG | Out-Null
if ($env:LEXCREW_HASH_MODE -ne "real") {
    function Get-FileHash {
        param([string]$LiteralPath, [string]$Path, [string]$Algorithm)
        [pscustomobject]@{ Hash = $env:LEXCREW_EMBED_HASH }
    }
}
function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile)
    [System.IO.File]::AppendAllText($env:LEXCREW_FAKE_LOG, "WEB $Uri`n")
    $text = if ($Uri -like "*get-pip.py") { "FRESH" } else { "NOT-A-ZIP" }
    [System.IO.File]::WriteAllText($OutFile, $text)
}
function Expand-Archive {
    param([string]$LiteralPath, [string]$DestinationPath, [switch]$Force)
    New-Item -ItemType Directory -Force -Path $DestinationPath | Out-Null
    Set-Content -LiteralPath (Join-Path $DestinationPath "python313._pth") -Value "python313.zip" -Encoding ascii
    $exe = Join-Path $DestinationPath "python.exe"
    Copy-Item -LiteralPath $env:LEXCREW_FAKE_PYTHON -Destination $exe
    & chmod +x $exe
}
& $env:LEXCREW_BUILD_SCRIPT
"""


def _embed_hash() -> str:
    match = re.search(r'\$embedHash = "([0-9A-F]+)"', _read(ROOT / "packaging" / "build.ps1"))
    assert match is not None
    return match.group(1)


def _run_build(
    tmp: Path,
    *,
    pymupdf: str = "1.28.2",
    pywebview: str = "6.2.1",
    pip_exit: int = 0,
    certifi: str = "2026.10.19",
    real_hash: bool = False,
    seed_get_pip: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh がありません")
    sandbox = tmp / "repo"
    packaging = sandbox / "packaging"
    packaging.mkdir(parents=True)
    script = packaging / "build.ps1"
    shutil.copy(ROOT / "packaging" / "build.ps1", script)
    (sandbox / "pyproject.toml").write_text('version = "1.4.1"\n', encoding="utf-8")
    fake = sandbox / ".venv" / "Scripts" / "python.exe"
    fake.parent.mkdir(parents=True)
    fake.write_text(_FAKE_PYTHON, encoding="utf-8")
    fake.chmod(0o755)
    if seed_get_pip is not None:
        cache = packaging / "cache"
        cache.mkdir()
        (cache / "get-pip.py").write_text(seed_get_pip, encoding="utf-8")
    if real_hash:
        cache = packaging / "cache"
        cache.mkdir(exist_ok=True)
        (cache / "python-3.13.17-embed-amd64.zip").write_bytes(b"not-the-embed-zip")
    log = sandbox / "fake.log"
    wrapper = sandbox / "wrap.ps1"
    wrapper.write_text(_BUILD_WRAPPER, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "LEXCREW_FAKE_LOG": str(log),
            "LEXCREW_FAKE_PYTHON": str(fake),
            "LEXCREW_BUILD_SCRIPT": str(script),
            "LEXCREW_PYMUPDF": pymupdf,
            "LEXCREW_PYWEBVIEW": pywebview,
            "LEXCREW_PIP_EXIT": str(pip_exit),
            "LEXCREW_CERTIFI": certifi,
            "LEXCREW_HASH_MODE": "real" if real_hash else "mock",
            "LEXCREW_EMBED_HASH": _embed_hash(),
        }
    )
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(wrapper)],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return proc, sandbox


def _sitecustomize(sandbox: Path) -> Path:
    return sandbox / "dist" / "LexCrew-PDF" / "runtime" / "Lib" / "site-packages" / "sitecustomize.py"


def _build_log(sandbox: Path) -> str:
    return (sandbox / "fake.log").read_text(encoding="utf-8")


def test_build_pins_runtime_and_refreshes_get_pip(tmp_path: Path):
    proc, sandbox = _run_build(tmp_path, seed_get_pip="STALE")
    assert _sitecustomize(sandbox).is_file(), proc.stderr
    assert (sandbox / "packaging" / "cache" / "get-pip.py").read_text(encoding="utf-8") == "FRESH"
    log = _build_log(sandbox)
    assert "pip==26.2.2" in log
    assert log.index("PIP tools") < log.index("PIP deps") < log.index("PIP upgrade")


def test_build_stops_when_pip_upgrade_fails(tmp_path: Path):
    proc, sandbox = _run_build(tmp_path, pip_exit=1)
    assert proc.returncode != 0
    assert "pip を更新できません。" in proc.stderr
    assert not _sitecustomize(sandbox).exists()


@pytest.mark.parametrize("certifi", ["2026.6.17", "2026.10.18"])
def test_build_stops_when_vendored_certifi_is_old(tmp_path: Path, certifi: str):
    proc, sandbox = _run_build(tmp_path, certifi=certifi)
    assert proc.returncode != 0
    assert "pip の certifi が 2026.10.19 未満です。" in proc.stderr
    assert not _sitecustomize(sandbox).exists()


def test_build_accepts_newer_vendored_certifi(tmp_path: Path):
    proc, sandbox = _run_build(tmp_path, certifi="2026.11.1")
    assert _sitecustomize(sandbox).is_file(), proc.stderr


def test_build_stops_when_embed_hash_mismatches(tmp_path: Path):
    proc, sandbox = _run_build(tmp_path, real_hash=True)
    assert proc.returncode != 0
    assert "埋め込み Python のハッシュが一致しません。" in proc.stderr
    assert not _sitecustomize(sandbox).exists()


@pytest.mark.parametrize(
    ("pymupdf", "pywebview"),
    [("2.0", "6.2.1"), ("1.28.2", "6.3")],
)
def test_build_stops_when_bundled_versions_differ(tmp_path: Path, pymupdf: str, pywebview: str):
    proc, sandbox = _run_build(tmp_path, pymupdf=pymupdf, pywebview=pywebview)
    assert proc.returncode != 0
    assert "同梱する版が違います。PyMuPDF は 1.28.2、pywebview は 6.2.1 です。" in proc.stderr
    assert not _sitecustomize(sandbox).exists()


def test_installer_deletes_only_its_own_payload():
    code = _code(ROOT / "installer" / "setup.nsi")
    assert re.findall(r"RequestExecutionLevel\s+(\S+)", code) == ["user"]
    assert "ExecWait" not in code
    assert "nsExec" not in code
    assert "/IM" not in code
    assert "CurrentVersion\\Run" not in code
    assert "Stop-App.ps1" not in code
    assert "0x08000000" in code
    for line in code.splitlines():
        if "MessageBox" in line:
            assert "/SD" in line, line
        if "SMSTARTUP" in line:
            assert "CreateShortCut" not in line
            assert "File " not in line
        stripped = line.strip()
        if not stripped.startswith("RMDir"):
            continue
        target = re.search(r'"([^"]+)"', stripped).group(1)
        if "/r" in stripped.split('"', 1)[0]:
            assert target in {
                r"$INSTDIR\runtime",
                r"$INSTDIR\src",
                r"$INSTDIR\ui",
            }, stripped
        else:
            assert target == "$INSTDIR", stripped
        assert "LexCrew-PDF-Downloads" not in stripped
        assert "layout.json" not in stripped

    levels = [line for line in code.splitlines() if "RequestExecutionLevel" in line]
    assert levels == ["RequestExecutionLevel user"]
    assert 'CreateShortCut "$SMSTARTUP' not in code

    install = _section(code, uninstall=False)
    uninstall = _section(code, uninstall=True)
    assert install.index("Call StopLexCrew") < install.index("Call RemovePayload")
    assert "Abort" in install[install.index("Call StopLexCrew") : install.index("Call RemovePayload")]
    assert uninstall.index("Call un.StopLexCrew") < uninstall.index("Call un.RemovePayload")
    assert "Abort" in uninstall[
        uninstall.index("Call un.StopLexCrew") : uninstall.index("Call un.RemovePayload")
    ]
    assert uninstall.index("Call un.RemovePayload") < uninstall.index("DeleteRegKey")
    assert uninstall.index("DeleteRegKey") < uninstall.index('Delete "$INSTDIR\\uninstall.exe"')
    assert uninstall.index('Delete "$INSTDIR\\uninstall.exe"') < uninstall.index('RMDir "$INSTDIR"')
    assert "ReadRegStr" in uninstall
    assert "InstallLocation" in uninstall
    assert "UninstDir" in uninstall

    payload = _function(code, "${UN}RemovePayload")
    assert payload.index("IsOurInstall") < payload.index("RMDir")
    ours = _function(code, "${UN}IsOurInstall")
    assert ours.index("IsProtectedDir") < ours.index('"yes"')
    hidden = _function(code, "${UN}ExecHidden")
    assert hidden.index('"error"') < hidden.index("CreateProcessW")
    assert "0x08000000" in hidden
    stop = _function(code, "${UN}StopLexCrew")
    scan = _function(code, "${UN}ScanLexCrew")
    assert "Process32FirstW" in scan
    assert "TerminateProcess" in code
    assert "taskkill.exe" in code
    assert "/PID" in code
    assert "Local\\LexCrew-PDF" in code or "APP_MUTEX" in code
    assert "CloseHandle" in stop
    assert "Abort" not in _function(code, "FindPowerShell")

    on_init = _function(code, ".onInit")
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\${APP_DIR}"' in on_init
    assert install.index('StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\${APP_DIR}"') < install.index(
        "Call StopLexCrew"
    )

    link = _function(code, "CreateLink")
    assert "Shortcut.ps1" in link
    assert "CreateShortCut" in link
    assert '!= "0"' in link
    assert "RunApp" not in link
    desktop = _function(code, "CreateDesktopShortcut")
    assert "CreateLink" in desktop
    assert "RunApp" not in desktop
    run = _function(code, "RunApp")
    assert "CreateShortCut" not in run
    assert "lexcrew_pdf" in run
    legacy = _function(code, "LegacyLinkIsOurs")
    assert "LEGACY_SUFFIX" in legacy
    assert "LEGACY_ARGS" in legacy
    assert legacy.index("LEGACY_SUFFIX") < legacy.rindex('"yes"')
    assert legacy.index("LEGACY_ARGS") < legacy.rindex('"yes"')
    remove_legacy = _function(code, "RemoveLegacyShortcut")
    assert remove_legacy.index("LegacyLinkIsOurs") < remove_legacy.index("Delete ")
    assert r"\runtime\pythonw.exe" in code
    assert "-m lexcrew_pdf" in code

    assert 'InstallDir "$LOCALAPPDATA\\Programs\\${APP_DIR}"' in code
    assert '!define APP_DIR "LexCrew-PDF"' in code
    assert 'MUI_FINISHPAGE_RUN_TEXT "デスクトップにショートカットを作る"' in code
    assert "MUI_FINISHPAGE_RUN_FUNCTION CreateDesktopShortcut" in code
    assert 'MUI_FINISHPAGE_SHOWREADME_TEXT "今すぐ起動"' in code
    assert "MUI_FINISHPAGE_SHOWREADME_FUNCTION RunApp" in code
    assert "MUI_FINISHPAGE_RUN_NOTCHECKED" not in code
    assert "MUI_FINISHPAGE_SHOWREADME_NOTCHECKED" not in code
    assert r"Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_DIR}" in code
    assert '/x "LexCrew-PDF.bat"' in code
    assert '/x "停止.bat"' in code
    assert '/x "Shortcut.ps1"' in code
    welcome = code.split("MUI_WELCOMEPAGE_TEXT", 1)[1].split("!insertmacro", 1)[0]
    for phrase in ("他の Python", "以前のフォルダ", "消しません", "LexCrew-PDF-Downloads", "ショートカット"):
        assert phrase in welcome


def test_user_docs_split_zip_and_setup():
    readme = _read(ROOT / "README.md")
    zip_guide = _read(ROOT / "packaging" / "使い方.txt")
    setup_guide = _read(ROOT / "installer" / "使い方.txt")
    for text in (readme, setup_guide):
        assert "LexCrew-PDF-Setup-1.4.1.exe" in text
        assert "Programs\\LexCrew-PDF" in text
        assert "LexCrew PDF" in text
        assert "デスクトップにショートカットを作る" in text
        assert "今すぐ起動" in text
        assert "LexCrew-PDF-Downloads" in text
        assert "layout.json" in text
        assert "アンインストール" in text
        assert "PC が保護されました" in text
        assert "詳細情報" in text
        assert "実行" in text
        assert "他の Python" in text
        assert "以前のフォルダ" in text
        assert "runtime\\pythonw.exe" in text
        assert "-m lexcrew_pdf" in text
    assert "この zip を全部展開" in zip_guide
    assert "LexCrew-PDF.bat" in zip_guide
    assert "停止.bat" in zip_guide
    assert "PC が保護されました" not in zip_guide
    assert "デスクトップにショートカットを作る" not in zip_guide
    assert "開発用" in readme
    assert "LexCrew-PDF-1.4.1-win64.zip" in readme
    for text in (zip_guide, setup_guide):
        assert "甲第N号証" in text
        assert "スタンプ" in text


def _tiny_ico() -> bytes:
    import struct

    width = height = 16
    xor = bytes([0, 0, 255, 255]) * (width * height)
    mask = bytes(64)
    dib = 40 + len(xor) + len(mask)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, dib, 22)
    info = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0)
    return header + entry + info + xor + mask


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} がありません")
    return path


def test_setup_compiles_with_makensis():
    _require_tool("makensis")
    with tempfile.TemporaryDirectory() as tmp:
        payload = Path(tmp) / "payload"
        (payload / "runtime").mkdir(parents=True)
        (payload / "src" / "lexcrew_pdf").mkdir(parents=True)
        (payload / "ui").mkdir()
        (payload / "runtime" / "pythonw.exe").write_bytes(b"py")
        (payload / "src" / "lexcrew_pdf" / "__main__.py").write_text("ok\n", encoding="utf-8")
        (payload / "ui" / "index.html").write_text("<html></html>\n", encoding="utf-8")
        (payload / "使い方.txt").write_text("guide\n", encoding="utf-8")
        (payload / "LICENSE").write_text("license\n", encoding="utf-8")
        (payload / "LexCrew-PDF.bat").write_text("bat\n", encoding="utf-8")
        (payload / "LexCrew-PDF.ico").write_bytes(_tiny_ico())
        outfile = Path(tmp) / "LexCrew-PDF-Setup-1.4.1.exe"
        cmd = [
            "makensis",
            "-WX",
            "-INPUTCHARSET",
            "UTF8",
            "-DVERSION=1.4.1",
            f"-DOUTFILE={outfile}",
            f"-DPAYLOAD={payload}",
            f"-DICON={payload / 'LexCrew-PDF.ico'}",
            f"-DSHORTCUT={ROOT / 'packaging' / 'Shortcut.ps1'}",
            str(ROOT / "installer" / "setup.nsi"),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        assert outfile.is_file()
        assert outfile.stat().st_size > 10000


def _wine_env(prefix: Path, display: str) -> dict[str, str]:
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    env["WINEDEBUG"] = "-all"
    env["DISPLAY"] = display
    env.pop("WAYLAND_DISPLAY", None)
    return env


def _run(args: list[str], env: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, env=env, check=False, capture_output=True, text=True, timeout=timeout)


def _wait_until_uninstall_exits(env: dict[str, str]) -> None:
    time.sleep(0.6)
    deadline = time.time() + 20
    quiet = 0
    while time.time() < deadline:
        listed = _run(["wine", "tasklist"], env)
        if "uninstall.exe" in listed.stdout.lower():
            quiet = 0
        else:
            quiet += 1
            if quiet >= 2:
                return
        time.sleep(0.25)
    raise AssertionError("uninstall.exe が終わらない")


def test_wine_install_keeps_unrelated_files_and_user_notes():
    _require_tool("makensis")
    _require_tool("wine")
    _require_tool("wineboot")
    _require_tool("Xvfb")
    display = None
    for number in range(61, 80):
        if not Path(f"/tmp/.X11-unix/X{number}").exists():
            display = f":{number}"
            break
    if display is None:
        pytest.skip("空いている X ディスプレイがありません")

    prefix = Path(tempfile.mkdtemp(prefix="lexcrew-wine-"))
    xvfb = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x720x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    env = _wine_env(prefix, display)
    old = other = None
    try:
        time.sleep(0.3)
        boot = _run(["wineboot", "--init"], env, timeout=180)
        assert boot.returncode == 0, boot.stderr
        payload = prefix / "payload"
        (payload / "runtime").mkdir(parents=True)
        (payload / "src" / "lexcrew_pdf").mkdir(parents=True)
        (payload / "ui").mkdir()
        (payload / "runtime" / "pythonw.exe").write_bytes(b"payload")
        (payload / "src" / "lexcrew_pdf" / "__main__.py").write_text("app\n", encoding="utf-8")
        (payload / "ui" / "index.html").write_text("<html></html>\n", encoding="utf-8")
        (payload / "使い方.txt").write_text("guide\n", encoding="utf-8")
        (payload / "LICENSE").write_text("license\n", encoding="utf-8")
        (payload / "LexCrew-PDF.bat").write_text("do-not-ship\n", encoding="utf-8")
        (payload / "LexCrew-PDF.ico").write_bytes(_tiny_ico())
        setup = prefix / "LexCrew-PDF-Setup-1.4.1.exe"
        compiled = _run(
            [
                "makensis",
                "-WX",
                "-INPUTCHARSET",
                "UTF8",
                "-DVERSION=1.4.1",
                f"-DOUTFILE={setup}",
                f"-DPAYLOAD={payload}",
                f"-DICON={payload / 'LexCrew-PDF.ico'}",
                f"-DSHORTCUT={ROOT / 'packaging' / 'Shortcut.ps1'}",
                str(ROOT / "installer" / "setup.nsi"),
            ],
            env,
        )
        assert compiled.returncode == 0, compiled.stderr

        drive = prefix / "drive_c"
        (drive / "unrelated").mkdir()
        (drive / "unrelated" / "keep.txt").write_text("secret\n", encoding="utf-8")
        (drive / "keep-root.txt").write_text("root\n", encoding="utf-8")
        old_runtime = drive / "old-zip" / "runtime"
        old_pkg = drive / "old-zip" / "src" / "lexcrew_pdf"
        old_runtime.mkdir(parents=True)
        old_pkg.mkdir(parents=True)
        shutil.copy(drive / "windows" / "notepad.exe", old_runtime / "pythonw.exe")
        (old_pkg / "__main__.py").write_text("old\n", encoding="utf-8")
        (drive / "old-zip" / "keep.txt").write_text("keep-old\n", encoding="utf-8")
        other_dir = drive / "other-py"
        other_dir.mkdir()
        shutil.copy(drive / "windows" / "notepad.exe", other_dir / "pythonw.exe")

        helper = prefix / "mklnk.nsi"
        helper.write_text(
            "\n".join(
                [
                    "Unicode true",
                    f'OutFile "{prefix / "LexCrew-MakeLink.exe"}"',
                    "RequestExecutionLevel user",
                    "SilentInstall silent",
                    "Section",
                    "  SetShellVarContext current",
                    '  CreateShortCut "$DESKTOP\\LexCrew-PDF.lnk" "C:\\old-zip\\runtime\\pythonw.exe" "-m lexcrew_pdf"',
                    "SectionEnd",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        assert _run(["makensis", "-WX", "-INPUTCHARSET", "UTF8", str(helper)], env).returncode == 0
        assert _run(["wine", str(prefix / "LexCrew-MakeLink.exe")], env).returncode == 0

        old = subprocess.Popen(
            ["wine", r"C:\old-zip\runtime\pythonw.exe"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        other = subprocess.Popen(
            ["wine", r"C:\other-py\pythonw.exe"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.2)
        assert old.poll() is None
        assert other.poll() is None

        installed = _run(["wine", str(setup), "/S", r"/D=C:\unrelated"], env)
        assert installed.returncode == 0, installed.stderr
        deadline = time.time() + 15
        while time.time() < deadline and old.poll() is None:
            time.sleep(0.2)
        assert old.poll() is not None
        assert other.poll() is None

        users = [
            path
            for path in (drive / "users").iterdir()
            if path.is_dir() and path.name.lower() not in {"public"}
        ]
        user = next(path for path in users if (path / "AppData").is_dir())
        inst = user / "AppData" / "Local" / "Programs" / "LexCrew-PDF"
        assert (inst / "runtime" / "pythonw.exe").is_file()
        assert (inst / "lexcrew-pdf.install").read_text(encoding="utf-8").startswith("LexCrew-PDF")
        assert not (inst / "LexCrew-PDF.bat").exists()
        assert (drive / "unrelated" / "keep.txt").read_text(encoding="utf-8") == "secret\n"
        assert not (drive / "unrelated" / "runtime").exists()
        assert (drive / "keep-root.txt").is_file()
        assert (drive / "old-zip" / "keep.txt").is_file()
        assert (drive / "old-zip" / "runtime" / "pythonw.exe").is_file()
        assert not (user / "Desktop" / "LexCrew-PDF.lnk").exists()
        assert (user / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "LexCrew PDF.lnk").is_file()

        (inst / "notes.txt").write_text("notes-keep\n", encoding="utf-8")
        wrong = prefix / "wrong.nsi"
        wrong.write_text(
            "\n".join(
                [
                    "Unicode true",
                    f'OutFile "{prefix / "LexCrew-WrongLink.exe"}"',
                    "RequestExecutionLevel user",
                    "SilentInstall silent",
                    "Section",
                    "  SetShellVarContext current",
                    '  CreateShortCut "$DESKTOP\\LexCrew-PDF.lnk" "C:\\other-py\\pythonw.exe" "-m lexcrew_pdf"',
                    "SectionEnd",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        assert _run(["makensis", "-WX", "-INPUTCHARSET", "UTF8", str(wrong)], env).returncode == 0
        assert _run(["wine", str(prefix / "LexCrew-WrongLink.exe")], env).returncode == 0
        again = _run(["wine", str(setup), "/S"], env)
        assert again.returncode == 0, again.stderr
        assert (inst / "notes.txt").read_text(encoding="utf-8") == "notes-keep\n"
        assert (user / "Desktop" / "LexCrew-PDF.lnk").is_file()
        assert (drive / "unrelated" / "keep.txt").is_file()

        copied = drive / "copied"
        copied.mkdir()
        shutil.copy(inst / "uninstall.exe", copied / "uninstall.exe")
        (copied / "keep.txt").write_text("keep-copied\n", encoding="utf-8")
        _run(["wine", r"C:\copied\uninstall.exe", "/S"], env)
        _wait_until_uninstall_exits(env)
        assert (inst / "notes.txt").read_text(encoding="utf-8") == "notes-keep\n"
        assert not (inst / "runtime").exists()
        assert not (inst / "uninstall.exe").exists()
        assert (copied / "keep.txt").is_file()
        assert (copied / "uninstall.exe").is_file()
        assert (drive / "unrelated" / "keep.txt").is_file()
        assert (drive / "keep-root.txt").is_file()
        reg = _run(
            [
                "wine",
                "reg",
                "query",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\LexCrew-PDF",
            ],
            env,
        )
        assert reg.returncode != 0

        restored = _run(["wine", str(setup), "/S"], env)
        assert restored.returncode == 0, restored.stderr
        assert (inst / "notes.txt").read_text(encoding="utf-8") == "notes-keep\n"
        assert (inst / "runtime" / "pythonw.exe").is_file()
        poisoned = _run(
            [
                "wine",
                "reg",
                "add",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\LexCrew-PDF",
                "/v",
                "InstallLocation",
                "/t",
                "REG_SZ",
                "/d",
                r"C:\unrelated",
                "/f",
            ],
            env,
        )
        assert poisoned.returncode == 0, poisoned.stderr
        _run(
            ["wine", f"C:\\users\\{user.name}\\AppData\\Local\\Programs\\LexCrew-PDF\\uninstall.exe", "/S"],
            env,
        )
        _wait_until_uninstall_exits(env)
        assert (drive / "unrelated" / "keep.txt").read_text(encoding="utf-8") == "secret\n"
        assert (inst / "notes.txt").is_file()
        assert not (inst / "runtime").exists()
        assert not (inst / "uninstall.exe").exists()

        foreign = inst / "runtime"
        foreign.mkdir()
        (foreign / "foreign.txt").write_text("foreign\n", encoding="utf-8")
        blocked = _run(["wine", str(setup), "/S"], env)
        assert blocked.returncode != 0
        assert (foreign / "foreign.txt").read_text(encoding="utf-8") == "foreign\n"
        assert not (inst / "src").exists()
        assert other.poll() is None
    finally:
        for proc in (old, other):
            if proc is not None and proc.poll() is None:
                proc.terminate()
        _run(["wineserver", "-k"], env, timeout=30)
        xvfb.terminate()
        shutil.rmtree(prefix, ignore_errors=True)
