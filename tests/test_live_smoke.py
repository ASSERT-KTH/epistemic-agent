"""End-to-end smoke run against a real model endpoint.

Skipped by default. Run with:
    uv run pytest -m live
Pick the endpoint and model with EA_LIVE_ENDPOINT and EA_LIVE_MODEL
(default: SciLifeLab OpenLLM, Qwen3-235B-A22B). Needs a key in the env var
named by EA_LIVE_KEY_ENV (default OPENLLM_API_KEY) or in the keyring under
the endpoint's hostname; the test is skipped if neither is present.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = os.environ.get("EA_LIVE_ENDPOINT", "https://openllm.scilifelab.se/api")
MODEL = os.environ.get("EA_LIVE_MODEL", "Qwen3-235B-A22B")
KEY_ENV = os.environ.get("EA_LIVE_KEY_ENV", "OPENLLM_API_KEY")


def _key_available() -> bool:
    if os.environ.get(KEY_ENV):
        return True
    try:
        import keyring
        return keyring.get_password(urlparse(ENDPOINT).hostname, "api_key") is not None
    except Exception:
        return False


@pytest.mark.skipif(not _key_available(), reason=f"no API key for {ENDPOINT}")
def test_one_task_end_to_end(tmp_path):
    ws, out = tmp_path / "ws", tmp_path / "out"
    ws.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "epistemic_agent.py"),
         "--out-dir", str(out), "--task-id", "live/smoke",
         "--endpoint", ENDPOINT, "--key-env", KEY_ENV, MODEL,
         "Create hello.py that prints hello world, then run it to check it works"],
        cwd=ws, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    run = json.loads((out / "run.json").read_text())
    assert run["status"] == "completed", run["error"]
    assert run["model"] == MODEL and run["endpoint"] == ENDPOINT
    assert run["harness"]["hermetic"] is True
    assert run["journal"]["accepted"] >= 1
    assert run["usage"]["model_calls"] >= 1 and run["usage"]["prompt_tokens"] > 0
    assert (out / "usage.jsonl").read_text().strip()
    assert (out / "RATIONALE.md").exists()

    # The agent did the task, and its workspace holds only its own files.
    assert (ws / "hello.py").exists()
    assert not (ws / ".epistemic").exists() and not (ws / "RATIONALE.md").exists()

    # Every accepted bash call carries a type from the vocabulary and a reason.
    sys.path.insert(0, str(ROOT))
    import epistemic_agent as ea
    entries = [json.loads(l) for l in (out / "journal.jsonl").read_text().splitlines()]
    for entry in entries:
        if not entry.get("rejected"):
            assert entry["act"] in ea.ACT_TYPES
            assert len(entry["reason"]) >= ea.MIN_REASON_CHARS
            # Effects (F1): every executed call has them, with its full output on disk.
            assert (out / entry["effects"]["output"]).exists()

    # Consistency (F2): every executed call was checked (monitor mode, the default),
    # and re-checking the stored journal offline gives the same verdicts. Whether
    # the model mislabels a call is data, not a test failure.
    import consistency
    executed = [e for e in entries if not e.get("rejected")]
    assert all(isinstance(e.get("violations"), list) for e in executed)
    offline = consistency.check_journal(entries, ())
    assert [r["violations"] for r in offline] == [e["violations"] for e in executed]
    assert run["harness"]["policy"] == "monitor"

    # The call that wrote hello.py is identified by its effects, not its declaration.
    creators = [e for e in entries if "hello.py" in (e.get("effects") or {}).get("created", [])]
    assert len(creators) == 1
    assert "hello" in (out / creators[0]["effects"]["diff"]).read_text()
