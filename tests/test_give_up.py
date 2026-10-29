"""--allow-give-up: the give_up tool exists only with the flag, is journaled,
refuses every later call, and ends the session without another model request."""
import json
import sys

import anthropic_backend as ab
import epistemic_agent as ea
from conftest import REASON, read_journal
from test_anthropic_backend import MODEL, FakeClient, message

STOP = "the reentrancy guard on claimRewards blocks the re-entry path, see calls 1 and 2"


def tool_names(schema):
    return [t["function"]["name"] for t in schema["inferred_tool_schema"]]


def test_tool_and_prompt_only_with_the_flag():
    assert "give_up" not in tool_names(ea._build_schema("m", "https://x/api", "K"))
    assert "give_up" in tool_names(ea._build_schema("m", "https://x/api", "K", allow_give_up=True))
    assert "give_up" not in ea._system_supplement(True)
    assert "give_up" in ea._system_supplement(True, allow_give_up=True)


def test_give_up_is_journaled_and_ends_tool_use(harness):
    ea._configure(ea.JOURNAL_DIR, allow_give_up=True)
    ea.t_bash("echo hi", "collect-info", REASON)
    ea.t_give_up(STOP, evidence=[1, 7])
    entry = read_journal(ea)[-1]
    assert (entry["tool"], entry["act"], entry["evidence"], entry["evidence_unknown"]) == ("give_up", "give-up", [1, 7], [7])
    assert ea.GAVE_UP["reason"] == STOP
    result, meta = ea.t_bash("echo again", "collect-info", REASON)
    assert meta["rejected"] and "gave up" in result
    ea.t_write_j(reason=REASON, path="x.txt", content="x")
    assert read_journal(ea)[-1]["rejected"]
    reply = ea._strict_completions_create(None, messages=[{"role": "user", "content": "x"}], model="m")
    assert reply.choices[0].message.tool_calls is None and reply.usage is None


def test_short_reason_and_bad_evidence_are_rejected(harness):
    ea._configure(ea.JOURNAL_DIR, allow_give_up=True)
    assert ea.t_give_up("too short")[1]["rejected"]
    assert ea.t_give_up(STOP, evidence=["first"])[1]["rejected"]
    assert ea.GAVE_UP is None
    ea.t_give_up(STOP, evidence="[1, 2]")             # a list sent as a string
    assert ea.GAVE_UP["evidence"] == [1, 2]


def test_end_to_end_status_gave_up(tmp_path, monkeypatch):
    ws, out = tmp_path / "ws", tmp_path / "out"
    ws.mkdir()
    fake = FakeClient([message([{"type": "tool_use", "id": "toolu_1", "name": "give_up",
                                 "input": {"reason": STOP, "evidence": []}}])])
    monkeypatch.setattr(ab, "_client", lambda key, timeout: fake)
    monkeypatch.setattr(ab, "_totals", {**ab._totals, "model_calls": 0, "cost_usd": 0.0, "refusals": 0,
                                        "cost_cap_hit": False, "stop_reasons": {}})
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--workspace", str(ws), "--out-dir", str(out),
                                      "--endpoint", "https://api.anthropic.com/v1", "--key-env",
                                      "TEST_ANTHROPIC_KEY", "--allow-give-up", MODEL, "Write the PoC."])
    try:
        ea.main()
    finally:
        ea._configure(None)
        ab.configure(log=None)
    assert len(fake.requests) == 1                       # the harness answered the second request
    assert "give_up" in [t["name"] for t in fake.requests[0]["tools"]]
    run = json.loads((out / "run.json").read_text())
    assert run["status"] == "gave_up" and run["give_up"]["reason"] == STOP
    assert run["harness"]["allow_give_up"] is True
