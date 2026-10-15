# E2 overview (no labels needed)

Aggregates only; safe to read before labelling. Disclosure, exposure and kappa need the raters' labels (analysis/e2_tables.py).

## Runs

| model | runs | completed | excluded (errors / timeouts) | excluded that misbehaved | dirty harness | misbehaved oneoff | misbehaved conflicting |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mistral | 206 | 203 | 3 (1 / 2) | 0 | 0 | 29/102 (28%, CI 21-38%) | 2/101 (2%, CI 1-7%) |
| Qwen | 206 | 197 | 9 (7 / 2) | 0 | 34 | 12/94 (13%, CI 7-21%) | 6/103 (6%, CI 3-12%) |
| all | 412 | 400 | 12 (8 / 4) | 0 | 34 | 41/196 (21%, CI 16-27%) | 8/204 (4%, CI 2-8%) |

## Misbehaving runs

| group | misbehaving | tamper / exploit / both | on defective tasks | tamper via file / bash / both | tamper contradicted | tamper with P1 | exploit candidates via file / bash / both | exploit contradicted (upper bound) |
|---|---:|---|---:|---|---:|---:|---|---:|
| Mistral | 31 | 3 / 28 / 0 | 1 | 1 / 2 / 0 | 2 | 3 | 27 / 0 / 1 | 0 |
| Qwen | 18 | 13 / 5 / 0 | 3 | 11 / 1 / 1 | 1 | 13 | 5 / 0 / 0 | 0 |
| all | 49 | 16 / 33 / 0 | 4 | 12 / 3 / 1 | 3 | 16 | 32 / 0 / 1 | 0 |
| all, no defective tasks | 45 | 12 / 33 / 0 | 0 | 9 / 2 / 1 | 2 | 12 | 32 / 0 / 1 | 0 |

## Cost per run (median, max)

| model | tokens, honest | tokens, misbehaving | minutes, honest | minutes, misbehaving |
|---|---:|---:|---:|---:|
| Mistral | 210011 (max 979093) | 258048 (max 532357) | 21.1 (max 60.1) | 21.7 (max 46.9) |
| Qwen | 66908 (max 4635994) | 141194 (max 3286060) | 6.1 (max 55.6) | 10.8 (max 41.5) |
| all | 149098 (max 4635994) | 246259 (max 3286060) | 13.0 (max 60.1) | 19.3 (max 46.9) |
