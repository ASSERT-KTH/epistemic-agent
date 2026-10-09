import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import epistemic_agent as ea  # noqa: E402

REASON = "find out whether the harness journals this call correctly"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Run every test in a fresh cwd with a fresh out-dir."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    out = tmp_path / "out"
    ea._configure(out)
    yield ea
    ea._configure(None)


def read_journal(ea):
    return ea._load_journal()
