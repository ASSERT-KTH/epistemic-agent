"""run.json and usage.jsonl, exercised through main() with a fake model run."""
import json
import sys

import pytest

from conftest import REASON

FAKE_KEY = "sk-THIS-MUST-NEVER-APPEAR-IN-RUN-JSON"


@pytest.fixture
def fake_run(harness, tmp_path, monkeypatch):
    """Replace run_task with a fake that opens a real agentknit session (so the
    hermetic wrapper and listeners run), emits usage events, and makes calls."""
    import agentknit._core as core
    ea = harness
    monkeypatch.setenv("OPENLLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    behaviour = {"raise": None}

    def run_task(schema, task, **opts):
        session = core.init_session(schema, non_interactive=True,
                                    system_prompt_supplement=opts["system_prompt_supplement"],
                                    session_dir=opts.get("session_dir"))
        core._emit(session, "usage", prompt=100, completion=20, total=120, cached=50, cache_write=0)
        core._emit(session, "rate_limit_wait", delay=1.5, resume_at="x", fmt="")
        ea.t_bash("echo a", "collect-info", REASON)
        ea.t_bash("echo b", "verfy", REASON)
        core._emit(session, "usage", prompt=130, completion=10, total=140, cached=100, cache_write=0)
        if behaviour["raise"]:
            raise behaviour["raise"]

    monkeypatch.setattr(ea, "run_task", run_task)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--out-dir", str(out),
                                      "--task-id", "lcb/42", "do the task"])
    return ea, out, behaviour


def _run_json(out):
    return json.loads((out / "run.json").read_text())


def test_run_json_records_a_completed_run(fake_run):
    ea, out, _ = fake_run
    ea.main()
    run = _run_json(out)
    assert run["status"] == "completed" and run["error"] is None
    assert run["task_id"] == "lcb/42" and run["task"] == "do the task"
    assert run["model"] == ea.DEFAULT_MODEL and run["endpoint"] == ea.DEFAULT_ENDPOINT
    assert run["harness"]["hermetic"] is True
    assert len(run["system_prompt_sha256"]) == 64
    assert run["versions"]["agentknit"] == "0.1017.0"
    assert run["repo"]["commit"] and isinstance(run["repo"]["dirty"], bool)
    assert run["journal"] == {"entries": 2, "accepted": 1, "rejected": 1, "contradicted_calls": 0,
                              "findings": {"violation": 0, "warning": 0, "protected": 0}}
    assert run["harness"]["policy"] == "monitor" and run["harness"]["protect"] == []
    assert run["finished_at"] and run["wall_clock_s"] >= 0


def test_usage_is_summed_and_streamed(fake_run):
    ea, out, _ = fake_run
    ea.main()
    usage = _run_json(out)["usage"]
    assert usage["model_calls"] == 2
    assert usage["prompt_tokens"] == 230 and usage["completion_tokens"] == 30
    assert usage["cached_tokens"] == 150 and usage["total_tokens"] == 260
    assert usage["rate_limit_wait_s"] == 1.5
    lines = [json.loads(l) for l in (out / "usage.jsonl").read_text().splitlines()]
    assert [l["n"] for l in lines] == [1, 2]
    assert lines[0]["prompt"] == 100 and lines[1]["cached"] == 100


def test_run_json_never_contains_key_material(fake_run):
    ea, out, _ = fake_run
    ea.main()
    text = (out / "run.json").read_text()
    assert FAKE_KEY not in text
    assert "keyring" not in text


def test_failed_run_is_recorded_as_error(fake_run):
    ea, out, behaviour = fake_run
    behaviour["raise"] = RuntimeError("endpoint exploded")
    with pytest.raises(RuntimeError):
        ea.main()
    run = _run_json(out)
    assert run["status"] == "error"
    assert "endpoint exploded" in run["error"]
    assert run["journal"]["entries"] == 2


def test_interrupted_run_is_recorded(fake_run):
    ea, out, behaviour = fake_run
    behaviour["raise"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        ea.main()
    assert _run_json(out)["status"] == "interrupted"


def test_prompt_hash_is_stable_across_runs(fake_run, tmp_path, monkeypatch):
    ea, out, _ = fake_run
    ea.main()
    first = _run_json(out)["system_prompt_sha256"]
    out2 = tmp_path / "out2"
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--out-dir", str(out2), "do the task"])
    ea.main()
    assert _run_json(out2)["system_prompt_sha256"] == first


def test_unrecovered_api_error_is_an_error_run(fake_run):
    """agentknit reports a failed model call as an event and returns normally;
    the run must not be recorded as completed."""
    import agentknit._core as core
    ea, out, _ = fake_run
    real = ea.run_task

    def failing(schema, task, **opts):
        real(schema, task, **opts)
        session = core.init_session(schema, non_interactive=True,
                                    system_prompt_supplement=opts["system_prompt_supplement"])
        core._emit(session, "error", text="Server disconnected", fmt="")
    ea.run_task = failing
    with pytest.raises(SystemExit) as exc:
        ea.main()
    assert "Server disconnected" in str(exc.value.code)
    run = _run_json(out)
    assert run["status"] == "error" and "Server disconnected" in run["error"]


def test_recovered_api_error_keeps_the_run_completed(fake_run):
    """An error followed by a successful model call (agentknit retried) is not fatal."""
    import agentknit._core as core
    ea, out, _ = fake_run
    seen = {}

    def flaky(schema, task, **opts):
        session = core.init_session(schema, non_interactive=True,
                                    system_prompt_supplement=opts["system_prompt_supplement"])
        core._emit(session, "error", text="Server disconnected", fmt="")
        core._emit(session, "usage", prompt=1, completion=1, total=2, cached=0, cache_write=0)
        seen["ok"] = True
    ea.run_task = flaky
    ea.main()
    run = _run_json(out)
    assert run["status"] == "completed" and run["api_errors"][0]["after_model_calls"] == 0
