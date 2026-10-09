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
