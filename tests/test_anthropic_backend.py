"""The Anthropic backend: request translation, prompt caching, thinking-block
replay inside a tool-use loop, refusals, and an offline end-to-end run of the
harness against a scripted Messages API."""
import json
import sys

import anthropic
import pytest
from anthropic.types import Message

import anthropic_backend as ab
import epistemic_agent as ea

MODEL = "claude-opus-4-8"
USAGE = {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 1000,
         "cache_creation_input_tokens": 100}


def message(content, stop_reason="tool_use", **extra):
    return Message.model_validate({"id": "msg_1", "type": "message", "role": "assistant", "model": MODEL,
                                   "content": content, "stop_reason": stop_reason,
                                   "stop_sequence": None, "usage": USAGE, **extra})


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.msg


class FakeClient:
    """Plays back scripted responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def stream(self, **params):
        self.requests.append(json.loads(json.dumps(params)))
        return FakeStream(self.responses.pop(0))


@pytest.fixture(autouse=True)
def fresh_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(ab, "_replay", {})
    monkeypatch.setattr(ab, "_totals", {**ab._totals, "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                                        "cost_usd": 0.0, "refusals": 0, "stop_reasons": {},
                                        "cost_cap_hit": False})
    ab.configure(thinking="adaptive", effort="xhigh", log=tmp_path / "anthropic.jsonl")
    yield
    ab.configure(log=None)


def test_handles_only_the_anthropic_api():
    assert ab.handles("https://api.anthropic.com/v1")
    assert not ab.handles("https://openllm.scilifelab.se/api")


def test_translation_merges_tool_results_and_caches_the_system_prompt():
    history = [
        {"role": "system", "content": "be epistemic"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "looking", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "ls"}'}},
            {"id": "t2", "type": "function", "function": {"name": "bash", "arguments": "{bad"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "a.sol"},
        {"role": "tool", "tool_call_id": "t2", "content": ""},
    ]
    system, msgs = ab.translate_messages(history)
    assert system == [{"type": "text", "text": "be epistemic", "cache_control": {"type": "ephemeral"}}]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}}
    assert msgs[1]["content"][2]["input"] == {"_unparseable_arguments": "{bad"}
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["t1", "t2"]
    assert msgs[2]["content"][1]["content"] == "(no output)"


def test_tools_translate_to_input_schema():
    tools = [{"type": "function", "function": {"name": "bash", "description": "d",
                                               "parameters": {"type": "object", "properties": {}}}}]
    assert ab.translate_tools(tools) == [{"name": "bash", "description": "d",
                                          "input_schema": {"type": "object", "properties": {}}}]


def test_thinking_blocks_are_replayed_and_requests_are_cached(tmp_path):
    first = message([{"type": "thinking", "thinking": "plan: list files", "signature": "sig"},
                     {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"command": "ls"}}])
    second = message([{"type": "text", "text": "done"}], stop_reason="end_turn")
    fake = FakeClient([first, second])
    ab._clients["k"] = fake
    oa = type("OA", (), {"_api_key": "k", "_timeout": 60})()
    history = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    r1 = ab.create(oa, model=MODEL, messages=history, tools=[{"type": "function", "function": {
        "name": "bash", "parameters": {"type": "object"}}}], tool_choice="auto", temperature=0)
    call = r1.choices[0].message.tool_calls[0]
    assert (call.id, call.function.name, json.loads(call.function.arguments)) == ("toolu_1", "bash", {"command": "ls"})
    assert r1.reasoning == "plan: list files"
    assert (r1.usage.prompt_tokens, r1.usage.cached_tokens, r1.usage.cache_creation_tokens) == (1110, 1000, 100)
    history += [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "toolu_1", "type": "function", "function": {"name": "bash", "arguments": call.function.arguments}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "a.sol"}]
    r2 = ab.create(oa, model=MODEL, messages=history, tool_choice="auto")
    assert r2.choices[0].message.content == "done" and not r2.choices[0].message.tool_calls
    req1, req2 = fake.requests
    assert req1["cache_control"] == {"type": "ephemeral"} and "temperature" not in req1
    assert req1["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert req1["output_config"] == {"effort": "xhigh"}
    replayed = req2["messages"][1]["content"]
    assert replayed[0] == {"type": "thinking", "thinking": "plan: list files", "signature": "sig"}
    assert req2["messages"][2]["content"][0]["type"] == "tool_result"
    lines = [json.loads(x) for x in (tmp_path / "anthropic.jsonl").read_text().splitlines()]
    assert [x["stop_reason"] for x in lines] == ["tool_use", "end_turn"]
    expected = (10 * 5 + 20 * 25 + 100 * 6.25 + 1000 * 0.5) / 1e6
    assert lines[0]["cost_usd"] == pytest.approx(expected)
    assert ab.totals()["cost_usd"] == pytest.approx(2 * expected, abs=1e-4)


def test_short_requests_run_without_thinking():
    fake = FakeClient([message([{"type": "text", "text": "summary"}], stop_reason="end_turn")])
    ab._clients["k"] = fake
    ab.create(type("OA", (), {"_api_key": "k"})(), model=MODEL,
              messages=[{"role": "user", "content": "summarize"}], max_tokens=4000)
    assert fake.requests[0]["thinking"] == {"type": "disabled"}


def test_refusal_ends_the_turn_and_is_counted():
    fake = FakeClient([message([{"type": "tool_use", "id": "x", "name": "bash", "input": {}}],
                               stop_reason="refusal",
                               stop_details={"type": "refusal", "category": "cyber", "explanation": None})])
    ab._clients["k"] = fake
    r = ab.create(type("OA", (), {"_api_key": "k"})(), model=MODEL, messages=[{"role": "user", "content": "t"}])
    assert r.choices[0].message.tool_calls is None
    assert "refused" in r.choices[0].message.content
    assert ab.totals()["refusals"] == 1


def test_harness_end_to_end_offline(tmp_path, monkeypatch):
    """A full one-shot run of epistemic_agent.py against the scripted API: the
    typed bash call is journaled, and run.json carries backend settings, usage
    and cost."""
    ws, out = tmp_path / "ws", tmp_path / "out"
    ws.mkdir()
    (ws / "a.sol").write_text("contract A {}\n")
    bash = {"command": "ls", "type": "collect-info",
            "reason": "find out which contracts the workspace holds before reading any"}
    fake = FakeClient([
        message([{"type": "thinking", "thinking": "look first", "signature": "s"},
                 {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": bash}]),
        message([{"type": "text", "text": "The workspace holds a.sol."}], stop_reason="end_turn"),
    ])
    monkeypatch.setattr(ab, "_client", lambda key, timeout: fake)
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--workspace", str(ws), "--out-dir", str(out),
                                      "--endpoint", "https://api.anthropic.com/v1", "--key-env",
                                      "TEST_ANTHROPIC_KEY", MODEL, "List the contracts."])
    try:
        ea.main()
    finally:
        ea._configure(None)
    journal = [json.loads(x) for x in (out / "journal.jsonl").read_text().splitlines()]
    assert [(e["tool"], e.get("type") or e.get("act")) for e in journal] == [("bash", "collect-info")]
    run = json.loads((out / "run.json").read_text())
    assert run["status"] == "completed"
    assert run["backend"]["backend"] == "anthropic-messages" and run["backend"]["effort"] == "xhigh"
    assert run["anthropic_usage"]["model_calls"] == 2 and run["anthropic_usage"]["cost_usd"] > 0
    assert len((out / "anthropic.jsonl").read_text().splitlines()) == 2
    assert fake.requests[1]["messages"][1]["content"][0]["type"] == "thinking"


def test_cost_cap_stops_without_calling_the_api(tmp_path):
    ab.configure(log=tmp_path / "a.jsonl", max_cost_usd=0.001)
    fake = FakeClient([message([{"type": "tool_use", "id": "a", "name": "bash", "input": {}}])])
    ab._clients["k"] = fake
    oa = type("OA", (), {"_api_key": "k"})()
    ab.create(oa, model=MODEL, messages=[{"role": "user", "content": "t"}])     # $0.00168 > cap
    r = ab.create(oa, model=MODEL, messages=[{"role": "user", "content": "t"}])
    assert len(fake.requests) == 1
    assert "cost cap" in r.choices[0].message.content and ab.totals()["cost_cap_hit"]
