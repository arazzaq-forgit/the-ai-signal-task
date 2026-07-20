import sys
from pathlib import Path

# Make `src` importable when running pytest from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.db import DB_PATH, init_db


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    """Every test gets a fresh, isolated SQLite file instead of touching the
    real data/state.db — tests should never depend on or mutate real
    pipeline output."""
    test_db_path = tmp_path / "test_state.db"
    monkeypatch.setattr("src.db.DB_PATH", test_db_path)
    init_db()
    yield
