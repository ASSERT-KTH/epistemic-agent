"""One real Impossible-LCB task through the full pipeline. Skipped by default.

    uv run pytest -m live tests/test_impossible_lcb_live.py

Uses EA_LIVE_ENDPOINT / EA_LIVE_MODEL like test_live_smoke.py, needs the
pinned data (bench/impossible_lcb.py fetch) and a working bwrap.
"""
import json

import pytest

import bwrap_sandbox
from bench import impossible_lcb as b
from test_live_smoke import ENDPOINT, KEY_ENV, MODEL, _key_available

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _key_available(), reason=f"no API key for {ENDPOINT}"),
    pytest.mark.skipif(not b.split_path("oneoff").exists(), reason="pinned data not fetched"),
    pytest.mark.skipif(not bwrap_sandbox.available(), reason="bwrap unavailable"),
]


def test_one_oneoff_task_end_to_end(tmp_path):
    [task] = b.select_tasks(b.load_tasks("oneoff"), ["lcbhard_0"], None, 0)
    cfg = b.RunConfig(out=tmp_path, model=MODEL, endpoint=ENDPOINT, key_env=KEY_ENV,
                      attempts=1, wall_clock_s=600)
    r = b.run_one(task, cfg)
    assert r["status"] == "completed", r["error"]
    assert r["attempts_used"] == 1 and r["sandbox"] == "bwrap"
    assert isinstance(r["misbehaved"], bool) and r["journal"]["calls"] >= 1
    run = json.loads((b.task_dir(cfg, task) / "run" / "run.json").read_text())
    assert run["harness"]["sandbox"] == "bwrap" and run["harness"]["protect"] == ["test.py"]
    assert run["task"] == b.task_prompt()
