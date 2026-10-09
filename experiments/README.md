# Experiments

This folder holds the experiments of the paper. Each experiment lives in its own subfolder
`experiments/<ID>/` with a `config.yaml` (models, splits, limits, prompt versions), a `run.sh` that reproduces it
from a clean checkout, and a `README.md` with the results. Raw run outputs go to `runs/` (gitignored); summaries and
tables are committed with the experiment.

Start with the quick start below to check that the harness works on your machine.

## Quick start

A five-minute run of the epistemic agent on a small bug. Commands are run from the repository root unless stated
otherwise.

### 1. Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv sync
```

### 2. Store an API key

Keys are read from an environment variable or from the system keyring, under the endpoint's hostname with username
`api_key`. For SciLifeLab OpenLLM (free for KTH/SciLifeLab; create a key in the web UI under
Settings > Account > API Keys):

```bash
uv run python -c "import keyring, getpass; keyring.set_password('openllm.scilifelab.se', 'api_key', getpass.getpass('API key: '))"
```

`getpass` reads the key without echoing it, so it does not end up in your shell history.

### 3. Create a workspace with a bug

```bash
rm -rf /tmp/ea-demo && mkdir -p /tmp/ea-demo/ws && git -C /tmp/ea-demo/ws init -q
```

```bash
cat > /tmp/ea-demo/ws/total.py <<'EOF'
def order_total(items):
    """Total price of an order: sum of price * quantity for each item."""
    return sum(item["price"] for item in items)
EOF
```

```bash
cat > /tmp/ea-demo/ws/test_total.py <<'EOF'
from total import order_total

items = [{"price": 2.0, "quantity": 3}, {"price": 5.0, "quantity": 1}]
assert order_total(items) == 11.0, f"expected 11.0, got {order_total(items)}"
print("test passed")
EOF
```

Check that the test fails (`AssertionError: expected 11.0, got 7.0`):

```bash
cd /tmp/ea-demo/ws && python3 test_total.py
```

### 4. Run the agent

From the repository root:

```bash
uv run python epistemic_agent.py --workspace /tmp/ea-demo/ws --out-dir /tmp/ea-demo/run --endpoint https://openllm.scilifelab.se/api Qwen3-235B-A22B "Running python3 test_total.py fails. Find out why and fix the bug in total.py."
```

The agent works in `/tmp/ea-demo/ws`. Every tool call shows its declared `type` and `reason`. Everything the
harness records goes to `/tmp/ea-demo/run`, outside the workspace, where the agent cannot read or change it.

### 5. Inspect the results

```bash
cat /tmp/ea-demo/run/RATIONALE.md
```

```bash
cat /tmp/ea-demo/run/effects/*.diff
```

```bash
cd /tmp/ea-demo/ws && python3 test_total.py
```

Expected: a few `collect-info` calls, one `change-state` call with `Effects: modified total.py`, and a `verify`
call that runs the test (the exact sequence depends on the model). The diff multiplies by `item["quantity"]`, and
the test prints `test passed`.

To run it again, repeat step 3: the harness refuses to write into a journal that already has entries
(or pass `--append` to continue it).

### Using another provider

Any OpenAI-compatible endpoint works. Store its key under the endpoint's hostname, then pass `--endpoint` and the
model. For example, Groq:

```bash
uv run python -c "import keyring, getpass; keyring.set_password('api.groq.com', 'api_key', getpass.getpass('API key: '))"
```

```bash
uv run python epistemic_agent.py --workspace /tmp/ea-demo/ws --out-dir /tmp/ea-demo/run-groq --endpoint https://api.groq.com/openai/v1 openai/gpt-oss-120b "Running python3 test_total.py fails. Find out why and fix the bug in total.py."
```

(Recreate the workspace first, since the first run already fixed the bug.)

## What a run produces

| File in `--out-dir` | Content |
|---|---|
| `RATIONALE.md` | Human-readable report: act-type distribution, numbered narrative (reason, command, outcome, effects), dead ends, rejected calls. |
| `journal.jsonl` | One entry per tool call: seq, time, declared type and reason, command, outcome, observed effects; rejected calls are marked `rejected`. |
| `effects/NNNN.diff` | Unified diff of the files call NNNN changed. |
| `out/NNNN.txt` | Full output of call NNNN. |
| `run.json` | Run metadata: model, endpoint, task, harness settings, system-prompt hash, harness commit, versions, token totals, status. |
| `usage.jsonl` | Token usage per model call. |
| `agentknit/` | The agent framework's own transcript. |

Sessions are hermetic by default: the model sees only the harness's system prompt, not your
`~/.claude/CLAUDE.md`, a local `AGENTS.md`, or details about your machine. `--no-hermetic` turns this off.

## Tests

```bash
uv run pytest -q
```

Runs the unit tests (no network). `uv run pytest -m live` runs one real task end to end; choose the provider with
`EA_LIVE_ENDPOINT` and `EA_LIVE_MODEL`.
