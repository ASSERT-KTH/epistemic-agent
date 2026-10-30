"""
anthropic_backend.py — run the epistemic harness on Claude through the Anthropic
Messages API, with prompt caching.

agentknit speaks the OpenAI chat-completions protocol. Anthropic's
OpenAI-compatible endpoint does not cache prompts, and an agent loop resends
its whole history on every call, so without a cache every call pays the full
input price again. This module translates one chat-completions request into a
Messages API request (official `anthropic` SDK), and the response back into
agentknit's response objects. epistemic_agent.py routes a request here when
the endpoint's host is api.anthropic.com; every other endpoint is unchanged.

What it does on top of the translation:
  caching    the system prompt carries a cache breakpoint and the request uses
             automatic caching, so each call reads the previous calls' prefix
             from the cache instead of paying for it again;
  thinking   adaptive thinking with summarized display (configurable), and
             the thinking blocks of each assistant turn are replayed unchanged
             on the next call, as the API requires inside a tool-use loop
             (agentknit's OpenAI-shaped history cannot hold them, so they are
             kept here, keyed by the turn's tool-call ids);
  sampling   no temperature: Opus 4.7+ rejects sampling parameters;
  logging    one line per model call in `anthropic.jsonl` (out dir): stop
             reason, raw usage, cost in USD, thinking summaries, refusal
             details. Totals are available from `totals()` for run.json.

A refusal (`stop_reason: refusal`) ends the turn with a short assistant text
and is counted separately, so a refused run is never mistaken for an agent
that stopped or gave up.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import anthropic
from agentknit.openai_compat import _Choice, _Function, _Message, _Response, _ToolCall, _Usage

ANTHROPIC_HOSTS = ("api.anthropic.com",)
THINKING_MODES = ("adaptive", "off")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_MAX_TOKENS = 64000
# Requests that ask for fewer output tokens than this (agentknit's compaction
# summaries) run without thinking, which would otherwise eat the budget.
MIN_TOKENS_FOR_THINKING = 16000

# USD per million tokens: input, output, cache write (5 min), cache read.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4-8": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-5-5": (4.0, 20.0, 5.00, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.50, 0.20),
}

_settings: dict[str, Any] = {"thinking": "adaptive", "effort": "xhigh", "log": None, "max_cost_usd": None}
_lock = threading.Lock()
_replay: dict[tuple[str, ...], list[dict[str, Any]]] = {}   # tool-call ids -> content blocks
_totals: dict[str, Any] = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                           "cost_usd": 0.0, "refusals": 0, "stop_reasons": {}, "cost_cap_hit": False}
_clients: dict[str, anthropic.Anthropic] = {}


def handles(base_url: str) -> bool:
    """True when agentknit's endpoint is the Anthropic API."""
    return (urlparse(base_url).hostname or "") in ANTHROPIC_HOSTS


def configure(*, thinking: str = "adaptive", effort: str = "xhigh", log: Path | None = None,
              max_cost_usd: float | None = None) -> None:
    if thinking not in THINKING_MODES:
        raise ValueError(f"thinking must be one of {THINKING_MODES}")
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {EFFORTS}")
    _settings.update(thinking=thinking, effort=effort, log=log, max_cost_usd=max_cost_usd)


def settings() -> dict[str, Any]:
    return {"backend": "anthropic-messages", "thinking": _settings["thinking"],
            "thinking_display": "summarized" if _settings["thinking"] == "adaptive" else None,
            "effort": _settings["effort"], "prompt_caching": "automatic + system breakpoint",
            "max_cost_usd": _settings["max_cost_usd"],
            "temperature": "not sent (rejected by Opus 4.7+)"}


def totals() -> dict[str, Any]:
    with _lock:
        return {**_totals, "cost_usd": round(_totals["cost_usd"], 4),
                "stop_reasons": dict(_totals["stop_reasons"])}


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    inp, out, write, read = price
    return (usage.get("input_tokens", 0) * inp + usage.get("output_tokens", 0) * out
            + usage.get("cache_creation_input_tokens", 0) * write
            + usage.get("cache_read_input_tokens", 0) * read) / 1e6


# ── request translation (chat completions -> Messages API) ───────────────────

def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text", ""))
        elif isinstance(part, str):
            parts.append(part)
    return "\n".join(parts)


def _tool_input(arguments: str) -> dict[str, Any]:
    try:
        value = json.loads(arguments or "{}")
    except ValueError:
        return {"_unparseable_arguments": arguments}
    return value if isinstance(value, dict) else {"_value": value}


def _assistant_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    ids = tuple(c.get("id", "") for c in calls)
    if ids:
        with _lock:
            stored = _replay.get(ids)
        if stored is not None:
            return stored        # the exact blocks the model produced, thinking included
    blocks: list[dict[str, Any]] = []
    text = _text_of(message.get("content"))
    if text.strip():
        blocks.append({"type": "text", "text": text})
    for call in calls:
        fn = call.get("function") or {}
        blocks.append({"type": "tool_use", "id": call.get("id", ""), "name": fn.get("name", ""),
                       "input": _tool_input(fn.get("arguments", "{}"))})
    return blocks


def translate_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """OpenAI-shaped history -> (system blocks, Messages API messages).

    Leading system messages become the system prompt; a later one becomes user
    text. Tool results become `tool_result` blocks in a user turn, and
    consecutive turns of the same role are merged, as the API expects."""
    system: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        if role == "system":
            text = _text_of(m.get("content"))
            if not out:
                if text.strip():
                    system.append({"type": "text", "text": text})
            elif text.strip():
                add("user", [{"type": "text", "text": f"[system]\n{text}"}])
        elif role == "user":
            text = _text_of(m.get("content"))
            if text.strip():
                add("user", [{"type": "text", "text": text}])
        elif role == "assistant":
            add("assistant", _assistant_blocks(m))
        elif role == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                          "content": _text_of(m.get("content")) or "(no output)"}])
    if system:
        system[-1]["cache_control"] = {"type": "ephemeral"}
    return system, out


def translate_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    for t in tools or []:
        fn = t.get("function") or t
        result.append({"name": fn["name"], "description": fn.get("description", ""),
                       "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
    return result


# ── response translation ─────────────────────────────────────────────────────

def _to_response(msg: Any) -> _Response:
    blocks = [b.model_dump(exclude_none=True) for b in msg.content]
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = [_ToolCall(id=b["id"], function=_Function(b["name"], json.dumps(b.get("input") or {})))
             for b in blocks if b.get("type") == "tool_use"]
    if calls:
        with _lock:
            _replay[tuple(c.id for c in calls)] = blocks
    if msg.stop_reason == "refusal":
        details = getattr(msg, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        text = (text + "\n" if text else "") + f"[model refused the request; category: {category}]"
        calls = []
    u = msg.usage
    read = u.cache_read_input_tokens or 0
    write = u.cache_creation_input_tokens or 0
    prompt = (u.input_tokens or 0) + read + write
    usage = _Usage(total_tokens=prompt + (u.output_tokens or 0), prompt_tokens=prompt,
                   completion_tokens=u.output_tokens or 0, cached_tokens=read,
                   cache_creation_tokens=write, has_cache_proof=True)
    response = _Response([_Choice(_Message("assistant", text or None, calls or None))], usage,
                         provider="anthropic")
    thinking = [b.get("thinking", "") for b in blocks if b.get("type") == "thinking"]
    response.reasoning = "\n\n".join(t for t in thinking if t) or None
    return response


def _record(model: str, msg: Any, seconds: float, thinking_on: bool) -> None:
    u = msg.usage
    usage = {"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0,
             "cache_read_input_tokens": u.cache_read_input_tokens or 0,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
    cost = cost_usd(model, usage)
    with _lock:
        _totals["model_calls"] += 1
        for k, v in usage.items():
            _totals[k] += v
        _totals["cost_usd"] += cost or 0.0
        _totals["stop_reasons"][msg.stop_reason] = _totals["stop_reasons"].get(msg.stop_reason, 0) + 1
        if msg.stop_reason == "refusal":
            _totals["refusals"] += 1
        n = _totals["model_calls"]
    log = _settings.get("log")
    if log is None:
        return
    details = getattr(msg, "stop_details", None)
    line = {"n": n, "t": time.time(), "seconds": round(seconds, 2), "id": msg.id, "model": msg.model,
            "stop_reason": msg.stop_reason, "thinking": thinking_on, "usage": usage,
            "cost_usd": None if cost is None else round(cost, 6),
            "thinking_summaries": [b.thinking for b in msg.content
                                   if b.type == "thinking" and getattr(b, "thinking", "")],
            "stop_details": details.model_dump() if details is not None and hasattr(details, "model_dump") else None}
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with _lock, Path(log).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


# ── entry point ──────────────────────────────────────────────────────────────

def _client(api_key: str, timeout: float) -> anthropic.Anthropic:
    with _lock:
        if api_key not in _clients:
            _clients[api_key] = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=5)
        return _clients[api_key]


def create(oa_client: Any, *, model: str, messages: list[dict[str, Any]],
           tools: list[dict[str, Any]] | None = None, tool_choice: str | None = None,
           max_tokens: int | None = None,
           on_content_delta: Callable[[str], None] | None = None,
           on_reasoning_delta: Callable[[str], None] | None = None,
           **_ignored: Any) -> _Response:
    """Drop-in for agentknit's `chat.completions.create` against api.anthropic.com.

    `oa_client` is agentknit's OpenAI client: its resolved API key and timeout
    are reused. temperature, user, extra_body and agentknit's callbacks other
    than the two delta streams are ignored."""
    cap = _settings.get("max_cost_usd")
    with _lock:
        spent = _totals["cost_usd"]
        if cap is not None and spent >= cap:
            _totals["cost_cap_hit"] = True
    if cap is not None and spent >= cap:
        # End the turn without calling the API: the run stops, and run.json
        # records status "cost_cap" (epistemic_agent._finish_run).
        return _Response([_Choice(_Message("assistant", f"[harness: cost cap of ${cap:.2f} reached]", None))],
                         _Usage())
    system, msgs = translate_messages(messages)
    max_tokens = max_tokens or DEFAULT_MAX_TOKENS
    thinking_on = _settings["thinking"] == "adaptive" and max_tokens >= MIN_TOKENS_FOR_THINKING
    params: dict[str, Any] = dict(model=model, max_tokens=max_tokens, messages=msgs,
                                  cache_control={"type": "ephemeral"},
                                  output_config={"effort": _settings["effort"]})
    if system:
        params["system"] = system
    api_tools = translate_tools(tools)
    if api_tools and tool_choice != "none":
        params["tools"] = api_tools
        params["tool_choice"] = {"type": "auto"}
    elif api_tools:
        params["tools"] = api_tools
        params["tool_choice"] = {"type": "none"}
    params["thinking"] = ({"type": "adaptive", "display": "summarized"} if thinking_on
                          else {"type": "disabled"})
    client = _client(oa_client._api_key, getattr(oa_client, "_timeout", 600.0) or 600.0)
    started = time.time()
    with client.messages.stream(**params) as stream:
        for event in stream:
            if event.type == "text" and on_content_delta is not None:
                on_content_delta(event.text)
            elif event.type == "thinking" and on_reasoning_delta is not None:
                on_reasoning_delta(event.thinking)
        msg = stream.get_final_message()
    _record(model, msg, time.time() - started, thinking_on)
    return _to_response(msg)
