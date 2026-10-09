"""Streaming is on by default and streamed requests ask for token usage."""
import sys

import epistemic_agent as ea


def test_schema_enables_streaming_by_default():
    schema = ea._build_schema("m", "https://x/api", "K")
    assert schema["provider_api_support"]["streaming"]["supported"] is True
    assert ea._build_schema("m", "https://x/api", "K", stream=False)["provider_api_support"]["streaming"]["supported"] is False


def test_cli_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "do the task"])
    assert ea.parse_args().stream is True
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--no-stream", "do the task"])
    assert ea.parse_args().stream is False


def _captured(monkeypatch, **kwargs):
    seen = {}

    def fake_create(self, *, messages, **kw):
        seen.update(kw, messages=messages)
        return "resp"
    monkeypatch.setattr(ea, "_orig_completions_create", fake_create)
    ea._strict_completions_create(None, messages=[{"role": "user", "content": "x", "ts": "t"}], **kwargs)
    return seen


def test_streamed_request_asks_for_usage(monkeypatch):
    seen = _captured(monkeypatch, model="m", on_content_delta=lambda s: None, extra_body={"user": "u"})
    assert seen["extra_body"] == {"user": "u", "stream_options": {"include_usage": True}}
    assert seen["messages"] == [{"role": "user", "content": "x"}]       # ts still stripped


def test_non_streamed_request_is_unchanged(monkeypatch):
    seen = _captured(monkeypatch, model="m", extra_body={"user": "u"})
    assert seen["extra_body"] == {"user": "u"}


def test_malformed_tool_arguments_are_wrapped_as_valid_json(monkeypatch):
    """Seen in a pilot: an extra '}' in a tool call's arguments made SciLifeLab's
    vLLM reject every later request with HTTP 400."""
    import json
    bad = '{"command": "ls", "type": "collect-info", "reason": "r"}}'
    good = '{"command": "pwd"}'
    msgs = [{"role": "assistant", "content": None, "ts": "t", "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "bash", "arguments": bad}},
        {"id": "2", "type": "function", "function": {"name": "bash", "arguments": good}}]}]
    seen = {}

    def fake_create(self, *, messages, **kw):
        seen["messages"] = messages
    monkeypatch.setattr(ea, "_orig_completions_create", fake_create)
    ea._strict_completions_create(None, messages=msgs, model="m")
    calls = seen["messages"][0]["tool_calls"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"_unparseable_arguments": bad}
    assert calls[1]["function"]["arguments"] == good
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == bad     # session history untouched
