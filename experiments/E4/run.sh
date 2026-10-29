#!/usr/bin/env bash
# E4: the epistemic agent on PoCo / Proof-of-Patch, four configurations
# (C1 PoC, C2 + give_up, C3 + patch, C4 + patch + give_up). Plan: experiments/E4/PLAN.md.
#
# Usage (from the repository root, in a terminal or tmux):
#   experiments/E4/run.sh check-key           is the API key valid? (lists the model; costs nothing)
#   experiments/E4/run.sh prepare [ids...]    build the pristine base workspaces (default: all 21)
#   experiments/E4/run.sh smoke               findings 077 and 091 x 4 configs (8 runs)
#   experiments/E4/run.sh full                21 findings x 4 configs (84 runs); needs a committed harness
#   experiments/E4/run.sh retry smoke|full    re-run tasks that ended in an agent error or a timeout
#   experiments/E4/run.sh status smoke|full   progress, from any terminal, while it runs
#   experiments/E4/run.sh collect smoke|full  results CSV into experiments/E4/results/
# PROVIDER selects the model (default kimi):
#   kimi       k3 on the Kimi Coding Plan (api.kimi.com/coding/v1), key KIMI_API_KEY, temperature 1
#   anthropic  claude-opus-4-8 via the Messages API, key ANTHROPIC_API_KEY, effort xhigh, $ cost cap
# Runs go to runs/E4/<provider>/<phase>. The key is read from $ENV_FILE (default
# /mnt/ssd2/sofia/.env) unless already set in the environment. It is never printed.
set -euo pipefail
cd "$(dirname "$0")/../.."

# ── configuration (fixed by the protocol) ────────────────────────────────────
PROVIDER="${PROVIDER:-kimi}"
case "$PROVIDER" in
  kimi)      MODEL="k3"; ENDPOINT="https://api.kimi.com/coding/v1"; KEY_ENV="KIMI_API_KEY"
             PROVIDER_ARGS=(--temperature 1) ;;
  anthropic) MODEL="claude-opus-4-8"; ENDPOINT="https://api.anthropic.com/v1"; KEY_ENV="ANTHROPIC_API_KEY"
             PROVIDER_ARGS=() ;;
  *) echo "error: PROVIDER must be kimi or anthropic" >&2; exit 1 ;;
esac
EFFORT="xhigh"          # Anthropic only
THINKING="adaptive"     # Anthropic only
WALL_CLOCK="${WALL_CLOCK:-2700}"       # seconds per task
MAX_COST="${MAX_COST:-8}"              # USD per run (harness cost cap)
MAX_PROMPT_TOKENS="${MAX_PROMPT_TOKENS:-15000000}"  # per-run prompt-token budget (status token_cap)
JOBS="${JOBS:-4}"
SMOKE_FINDINGS=(077 091)
OUT_ROOT="runs/E4/$PROVIDER"
ENV_FILE="${ENV_FILE:-/mnt/ssd2/sofia/.env}"

load_key() {
  if [[ -z "${!KEY_ENV:-}" ]]; then
    [[ -r "$ENV_FILE" ]] || { echo "error: $KEY_ENV not set and $ENV_FILE not readable" >&2; exit 1; }
    local value
    value="$(sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\{0,1\}$KEY_ENV=//p" "$ENV_FILE" \
             | tail -1 | tr -d "\r\"'" )"
    export "$KEY_ENV=$value"
  fi
  [[ -n "${!KEY_ENV:-}" ]] || { echo "error: no $KEY_ENV in $ENV_FILE" >&2; exit 1; }
}

require_clean_tree() {
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "error: uncommitted changes in tracked files; final runs must come from a committed harness" >&2
    exit 1
  fi
}

run_phase() {  # phase findings...
  local phase="$1"; shift
  local sel=(); [[ $# -gt 0 ]] && sel=(--findings "$@")
  echo "=== E4 $phase, $PROVIDER/$MODEL, effort $EFFORT, ${WALL_CLOCK}s and \$$MAX_COST per run, $JOBS jobs, harness $(git rev-parse --short HEAD)$( [[ -n "$(git status --porcelain --untracked-files=no)" ]] && echo ' (dirty)') ===" >&2
  uv run python bench/poco.py prepare "${sel[@]}"
  uv run python bench/poco.py run --out "$OUT_ROOT/$phase" "${sel[@]}" --model "$MODEL" \
    --endpoint "$ENDPOINT" --key-env "$KEY_ENV" "${PROVIDER_ARGS[@]}" --effort "$EFFORT" --thinking "$THINKING" --wall-clock "$WALL_CLOCK" --max-cost-usd "$MAX_COST" --max-prompt-tokens "$MAX_PROMPT_TOKENS" \
    --jobs "$JOBS" "${EXTRA[@]}"
}

EXTRA=()
cmd="${1:-}"; shift || true
case "$cmd" in
  check-key)
    load_key
    if [[ $PROVIDER == anthropic ]]; then
      hdr=(-H "x-api-key: ${!KEY_ENV}" -H "anthropic-version: 2023-06-01")
    else
      hdr=(-H "Authorization: Bearer ${!KEY_ENV}")
    fi
    code=$(curl -s -m 30 -o /dev/null -w "%{http_code}" "$ENDPOINT/models" "${hdr[@]}")
    [[ "$code" == 200 ]] && echo "key ok ($PROVIDER, $MODEL)" || { echo "key rejected: HTTP $code" >&2; exit 1; }
    ;;
  prepare)
    uv run python bench/poco.py prepare ${1:+--findings "$@"}
    ;;
  smoke)
    load_key
    run_phase smoke "${SMOKE_FINDINGS[@]}"
    ;;
  scenario1)  # C1 on all findings; harness may be uncommitted, so snapshot it into the run dir
    load_key
    snap="$OUT_ROOT/scenario1/provenance/$(date -u +%Y-%m-%dT%H%M)"; mkdir -p "$snap"
    git rev-parse HEAD > "$snap/HEAD"; git diff > "$snap/tracked.diff"
    git ls-files --others --exclude-standard -z | tar --null -T - -czf "$snap/untracked.tgz"
    EXTRA=(--configs C1)
    run_phase scenario1
    ;;
  full)
    require_clean_tree
    load_key
    run_phase full
    ;;
  retry)
    phase="${1:?usage: run.sh retry smoke|full}"
    [[ "$phase" == full ]] && require_clean_tree
    load_key
    EXTRA=(--retry-errors)
    if [[ "$phase" == smoke ]]; then run_phase smoke "${SMOKE_FINDINGS[@]}"; else run_phase full; fi
    ;;
  status)
    uv run python bench/poco.py status "$OUT_ROOT/${1:?usage: run.sh status smoke|full}"
    ;;
  collect)
    phase="${1:?usage: run.sh collect smoke|full}"
    mkdir -p experiments/E4/results
    uv run python bench/poco.py collect "$OUT_ROOT/$phase" > "experiments/E4/results/$phase.csv"
    echo "wrote experiments/E4/results/$phase.csv" >&2
    ;;
  *)
    sed -n '2,15p' "$0"; exit 1
    ;;
esac
