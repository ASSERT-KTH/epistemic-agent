# Why 34 Qwen full-run results record `harness_dirty: true`

The 34 Qwen tasks re-run by the retry pass (`run.sh retry full qwen`, 2026-10-12, 11:13 to about 14:00 CEST) record
harness commit `d923f23` with `harness_dirty: true`; the other 172 Qwen results record `d923f23` clean.

The dirty flag means tracked files differed from the commit. During the retry pass, `paper.tex` and `.gitignore`
were edited in the same checkout (11:53-11:54 CEST: switch to the IEEEcsmag template; `*.bbl`, `*.blg` added to
`.gitignore`). `qwen-retry-dirty.patch` is the complete uncommitted diff at that time (`git diff` against `d923f23`).
It touches only those two files: no harness, benchmark, sandbox or test code changed, so all 206 Qwen runs ran
identical harness code. Afterwards the paper edits were moved to a separate worktree so that the Mistral runs start
from a clean `d923f23`.
