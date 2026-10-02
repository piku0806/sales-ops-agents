import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SALESOPS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from salesops import crm_db
    from salesops.config import get_settings

    s = get_settings()
    crm_db.init_db(s.crm_db, reset=True)
    return s
