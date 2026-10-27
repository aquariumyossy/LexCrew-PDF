import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_originals(tmp_path_factory, monkeypatch):
    """原本の複製をテストごとに分け、利用者の LocalAppData へ書かない。"""
    root = tmp_path_factory.mktemp("lexcrew-app")
    monkeypatch.setenv("LEXCREW_ORIGINALS", str(root / "originals"))
