"""利用者向けセットアップの約束。NSIS のコンパイルは別途行う。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_version_is_1_4_0():
    assert 'version = "1.4.0"' in _read(ROOT / "pyproject.toml")


def test_dev_launchers_stay():
    assert (ROOT / "起動.bat").is_file()
    assert (ROOT / "停止.bat").is_file()
    assert (ROOT / "packaging" / "LexCrew-PDF.bat").is_file()
    assert (ROOT / "packaging" / "停止.bat").is_file()


def test_build_emits_setup_and_keeps_the_dev_zip():
    build = _read(ROOT / "packaging" / "build.ps1")
    assert "LexCrew-PDF-Setup-$version.exe" in build
    assert "LexCrew-PDF-$version-win64.zip" in build
    assert "makensis" in build
    assert "LexCrew-PDF.bat" in build
    assert "停止.bat" in build


def test_installer_is_per_user_and_leaves_case_data():
    text = _read(ROOT / "installer" / "setup.nsi")
    assert "RequestExecutionLevel user" in text
    assert 'InstallDir "$LOCALAPPDATA\\Programs\\${APP_DIR}"' in text
    assert '!define APP_DIR "LexCrew-PDF"' in text
    assert 'MUI_FINISHPAGE_RUN_TEXT "デスクトップにショートカットを作る"' in text
    assert "MUI_FINISHPAGE_RUN_FUNCTION CreateDesktopShortcut" in text
    assert 'MUI_FINISHPAGE_SHOWREADME_TEXT "今すぐ起動"' in text
    assert "MUI_FINISHPAGE_SHOWREADME_FUNCTION RunApp" in text
    assert "MUI_FINISHPAGE_RUN_NOTCHECKED" not in text
    assert "MUI_FINISHPAGE_SHOWREADME_NOTCHECKED" not in text
    assert r"Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_DIR}" in text
    assert "CurrentVersion\\Run" not in text
    assert '/x "LexCrew-PDF.bat"' in text
    assert '/x "停止.bat"' in text
    assert '/x "Shortcut.ps1"' in text
    assert "Stop-App.ps1" in text
    uninstall = text.split('Section "Uninstall"', 1)[1]
    assert uninstall.index("Stop-App.ps1") < uninstall.index('RMDir /r "$INSTDIR"')
    install = text.split("Section", 1)[1].split('Section "Uninstall"', 1)[0]
    assert install.index("Stop-App.ps1") < install.index('RMDir /r "$INSTDIR"')
    for line in text.splitlines():
        if "RMDir" in line or line.strip().startswith("Delete "):
            assert "LexCrew-PDF-Downloads" not in line
            assert "layout.json" not in line


def test_user_docs_describe_setup_update_and_uninstall():
    readme = _read(ROOT / "README.md")
    guide = _read(ROOT / "packaging" / "使い方.txt")
    for text in (readme, guide):
        assert "LexCrew-PDF-Setup-1.4.0.exe" in text
        assert "Programs\\LexCrew-PDF" in text
        assert "LexCrew PDF" in text
        assert "デスクトップにショートカットを作る" in text
        assert "今すぐ起動" in text
        assert "LexCrew-PDF-Downloads" in text
        assert "layout.json" in text
        assert "アンインストール" in text
    assert "この zip を全部展開" not in guide
    assert "開発用" in readme
    assert "LexCrew-PDF-1.4.0-win64.zip" in readme
