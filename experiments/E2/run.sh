#!/usr/bin/env bash
# E2 (paper RQ1): when a coding agent reward-hacks on Impossible-LiveCodeBench,
# does its epistemic journal expose it? Protocol: experiments/E2/README.md.
#
# Usage (from the repository root, in a terminal):
#   experiments/E2/run.sh pilot  [qwen|mistral]   20 tasks per split per model (80 runs)
#   experiments/E2/run.sh full   [qwen|mistral]   all 206 impossible tasks per model (412 runs)
#   experiments/E2/run.sh retry  pilot|full [qwen|mistral]   re-run tasks that ended in an error or timeout
#   experiments/E2/run.sh status pilot|full       progress, from any terminal, while it runs
#   experiments/E2/run.sh collect pilot|full      results CSV into experiments/E2/results/
# Without a model argument, both models run one after the other.
# PROMPT=pressure selects the protocol's fallback prompt (only if the pilot rule says so).
set -euo pipefail
cd "$(dirname "$0")/../.."

# ── configuration (fixed by the protocol) ────────────────────────────────────
ENDPOINT="https://openllm.scilifelab.se/api"
declare -A MODELS=([qwen]="Qwen3-235B-A22B" [mistral]="Mistral-Large-3-675B-Instruct-2512-NVFP4")
SPLITS=(--split oneoff --split conflicting)
ATTEMPTS=3
# Seconds per task. The pilot first used 1200 s (24 of 40 Mistral runs timed
# out: long answers on a loaded server), then 2700 s for its re-runs (still 4/40
# Mistral timeouts, 5 completed runs at 40-44 min). The full run uses 3600 s.
WALL_CLOCK="${WALL_CLOCK:-3600}"
JOBS="${JOBS:-4}"
PILOT_LIMIT=20
SEED=0
PROMPT="${PROMPT:-paper}"
OUT_ROOT="runs/E2"

phase_dir() {  # pilot | full, with a suffix for a non-default prompt
  local suffix=""; [[ "$PROMPT" != "paper" ]] && suffix="-$PROMPT"
  echo "$OUT_ROOT/$1$suffix"
}

models_for() {  # all models, or the one named
  if [[ -n "${1:-}" ]]; then echo "${MODELS[$1]:?unknown model $1 (qwen|mistral)}"; else echo "${MODELS[qwen]}" "${MODELS[mistral]}"; fi
}

require_clean_tree() {
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "error: uncommitted changes in tracked files; final runs must come from a committed harness" >&2
    exit 1
  fi
}

run_phase() {  # phase model extra-args...
  local phase="$1" model="$2"; shift 2
  local limit=(); [[ "$phase" == pilot ]] && limit=(--limit "$PILOT_LIMIT" --seed "$SEED")
  echo "=== E2 $phase, $model, prompt $PROMPT, limit ${WALL_CLOCK}s/task, harness $(git rev-parse --short HEAD) ===" >&2
  uv run python bench/impossible_lcb.py run "${SPLITS[@]}" "${limit[@]}" \
    --model "$model" --endpoint "$ENDPOINT" --out "$(phase_dir "$phase")" \
    --attempts "$ATTEMPTS" --wall-clock "$WALL_CLOCK" --jobs "$JOBS" --prompt-variant "$PROMPT" "$@"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  pilot|full)
    require_clean_tree
    uv run python bench/impossible_lcb.py fetch >/dev/null
    for m in $(models_for "${1:-}"); do run_phase "$cmd" "$m"; done
    ;;
  retry)
    phase="${1:?usage: run.sh retry pilot|full [qwen|mistral]}"
    require_clean_tree
    for m in $(models_for "${2:-}"); do run_phase "$phase" "$m" --retry-errors; done
    ;;
  status)
    uv run python bench/impossible_lcb.py status "$(phase_dir "${1:?usage: run.sh status pilot|full}")"
    ;;
  collect)
    phase="${1:?usage: run.sh collect pilot|full}"
    mkdir -p experiments/E2/results
    dest="experiments/E2/results/$(basename "$(phase_dir "$phase")").csv"
    uv run python bench/impossible_lcb.py collect "$(phase_dir "$phase")" > "$dest"
    echo "wrote $dest" >&2
    ;;
  *)
    sed -n '2,15p' "$0"; exit 1
    ;;
esac
