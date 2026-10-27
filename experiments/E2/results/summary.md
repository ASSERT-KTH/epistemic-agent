# E2 (RQ1) results

Across 49 reward-hacking runs, the journal exposed 44 (90%, 95% CI 78-96%): 44 disclosed, 3 contradicted (3 both). Broad exposure (post hoc, including visible): 96%. Without the defective tasks: 89%.

| group | misbehaving | tamper | exploit | disclosed | contradicted | exposed | broad | concealed | file / bash / both |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Mistral | 31 | 3 | 28 | 30 | 2 | 30 (97%) | 97% | 1 | 29 / 2 / 0 |
| Qwen | 18 | 13 | 5 | 14 | 1 | 14 (78%) | 94% | 4 | 17 / 1 / 0 |
| all | 49 | 16 | 33 | 44 | 3 | 44 (90%) | 96% | 5 | 46 / 3 / 0 |
| all, no defective tasks | 45 | 12 | 33 | 40 | 2 | 40 (89%) | 96% | 5 | 43 / 2 / 0 |

## Runs

| model | runs | completed | excluded | misbehavior oneoff | misbehavior conflicting |
|---|---:|---:|---:|---:|---:|
| Mistral | 206 | 203 | 3 | 29/102 | 2/101 |
| Qwen | 206 | 197 | 9 | 12/94 | 6/103 |

Cohen's kappa on disclosed (before discussion): 0.72.
Final reply discloses the misbehavior: 35 of 49.
