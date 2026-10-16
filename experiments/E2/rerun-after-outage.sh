#!/usr/bin/env bash
# experiments/E2/rerun-after-outage.sh — E2 full run, Mistral: re-run the tasks
# lost to the SciLifeLab outage of 2026-10-13 (see the README, "Deviations").
#
# Waits until the Mistral backend answers a 3-token request, then re-runs, with
# the protocol's settings, exactly the tasks whose result is an agent error that
# says the gateway could not reach the model server ("Connect call failed").
# Other unfinished results (timeouts, other errors) are not touched.
#
#   nohup experiments/E2/rerun-after-outage.sh >> runs/E2/full-mistral.log 2>&1 &
#
# PROBE_EVERY (seconds, default 300) and MAX_WAIT (seconds, default 172800) set
# the probing; DRY_RUN=1 prints the selected tasks and exits.
set -euo pipefail
cd "$(dirname "$0")/../.."

MODEL="Mistral-Large-3-675B-Instruct-2512-NVFP4"
ENDPOINT="https://openllm.scilifelab.se/api"
OUT="runs/E2/full"
EXPECTED_HEAD="d923f23"
PROBE_EVERY="${PROBE_EVERY:-300}"
MAX_WAIT="${MAX_WAIT:-172800}"
log() { echo "[$(date +%H:%M:%S)] outage re-run: $*"; }

# Same harness as the rest of the full run: committed, unchanged.
if [[ "$(git rev-parse --short HEAD)" != "$EXPECTED_HEAD" ]]; then
  log "error: HEAD is $(git rev-parse --short HEAD), the full run used $EXPECTED_HEAD"; exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  log "error: uncommitted changes in tracked files"; exit 1
fi

# The selection depends only on the recorded error, never on a run's outcome.
selected() {  # prints "split task_id" lines
  uv run python - "$OUT" "$MODEL" <<'EOF'
import json, sys
from pathlib import Path
out, model = Path(sys.argv[1]), sys.argv[2]
slug = model.replace("/", "_").replace(":", "_")
for f in sorted((out / slug).glob("*/*/result.json")):
    r = json.loads(f.read_text())
    if r.get("status") == "agent_error" and "Connect call failed" in (r.get("error") or ""):
        print(r["split"], r["task_id"])
EOF
}

mapfile -t TASKS < <(selected)
log "${#TASKS[@]} task(s) lost to the outage: ${TASKS[*]/ //}"
[[ ${#TASKS[@]} -eq 0 ]] && exit 0
[[ "${DRY_RUN:-0}" == 1 ]] && exit 0

# Wait for the backend. The key is read from the keyring and never printed.
probe() {
  uv run python - "$ENDPOINT" "$MODEL" <<'EOF'
import json, sys, urllib.parse, urllib.request
import keyring
endpoint, model = sys.argv[1], sys.argv[2]
key = keyring.get_password(urllib.parse.urlparse(endpoint).hostname, "api_key")
req = urllib.request.Request(endpoint + "/chat/completions",
    data=json.dumps({"model": model, "max_tokens": 3,
                     "messages": [{"role": "user", "content": "Say OK"}]}).encode(),
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception as exc:
    print(f"probe failed: {str(exc)[:120]}", file=sys.stderr)
    sys.exit(1)
EOF
}

waited=0
until probe; do
  if (( waited >= MAX_WAIT )); then log "backend still down after ${MAX_WAIT}s, giving up"; exit 1; fi
  log "backend down, next probe in ${PROBE_EVERY}s"
  sleep "$PROBE_EVERY"; waited=$((waited + PROBE_EVERY))
done
log "backend answers; starting the re-run"

# A re-run deletes the task directory; keep the failed records as evidence.
EVIDENCE="runs/E2/outage-2026-10-13"
for t in "${TASKS[@]}"; do
  src="$OUT/$(echo "$MODEL" | tr '/:' '__')/${t/ //}"
  mkdir -p "$EVIDENCE/${t/ //}"
  cp -a "$src/result.json" "$src/run" "$EVIDENCE/${t/ //}/"
done
log "failed records kept in $EVIDENCE"

# One invocation per split, so that a task id selected in one split does not
# re-run its namesake in the other split (e.g. a timeout there).
for split in oneoff conflicting; do
  ids=$(printf '%s\n' "${TASKS[@]}" | awk -v s="$split" '$1 == s {print $2}' | paste -sd, -)
  [[ -z "$ids" ]] && continue
  log "$split: $ids"
  uv run python bench/impossible_lcb.py run --split "$split" --tasks "$ids" \
    --model "$MODEL" --endpoint "$ENDPOINT" --out "$OUT" \
    --attempts 3 --wall-clock 3600 --jobs 4 --prompt-variant paper --retry-errors
done
log "done"
