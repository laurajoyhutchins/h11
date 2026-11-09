# Prioritizing independent contract verification

The `select.py` tool allocates a **fixed budget of verification attention** across the source-only candidates returned by `discover_v2.py`. It never reads a contract ledger, executes target code, or generates a behavioral oracle. Its output is a sorted research queue, **not** a list of verified contracts.

## Use

From `research/synthetic-history-evidence`:

```bash
python research/contract_discovery/discover_v2.py /checkout/jinja \
  --package jinja2 --source-dir src --tests tests \
  --output /tmp/discovery.json

python research/selection/select.py \
  --discovery /tmp/discovery.json --budget 3 \
  --output /tmp/selection.json
```

The output contains the ranked selection, all source-derived candidates, each candidate's source Git blob SHAs, test-import and downstream-import witnesses, closure size, explicit score components, selection diversity bonuses and `INSUFFICIENT_EVIDENCE` for every entry. It is JSON and byte-deterministic given identical input and budget.

## Frozen scoring rule

The score was [registered before examining the Jinja implementation](jinja_preregistration.json).

For each candidate, the focus modules are its one observed-test module, the two sides of an independent sibling pair, or the defining/derived modules of a class inheritance edge.

- Test-import points: `3 × min(number of original tests directly importing any focus module, 4)`.
- Downstream points: `2 × min(number of other source modules transitively depending on any focus module, 4)`.
- Source-size points: `min(4, ceil(sum of focus-module LOC / 120))`.
- Family bonus: 4 for independent siblings; 3 for cross-module inheritance; 1 for in-module inheritance; 2 for test-imported closures.
- Closure cost penalty: `min(3, max(0, import closure size - 4) // 4)`.
- Dynamic import penalty: 4 when any module in the static closure has a dynamic import signal.

Choose up to three greedily. At each step, add `2 × min(3, uncovered focus modules)` and 2 points if no candidate from that family has been selected yet. Break ties by lexicographic candidate ID. Remove candidates with exactly the same focus module set to avoid choosing identical implementation slices repeatedly.

The score is **not** a calibrated risk, impact, completeness, or correctness probability. It is a reproducible attempt to balance leverage, available test entry points, structural novelty, and investigation cost.

## Preregistered Jinja holdout

Pinned third unseen repository: `pallets/jinja` at `5ef70112a1ff19c05324ff889dd30405b1002044`. The criterion and commit were frozen before inspecting its source.

| Repository | Modules | Structural candidates | Selected |
| --- | ---: | ---: | ---: |
| h11 | 11 | 36 | 3 |
| ItsDangerous | 8 | 20 | 3 |
| Click | 17 | 56 | 3 |
| Jinja | 25 | 124 | 3 |

The three Jinja selections were `Environment -> NativeEnvironment` (score 26), `jinja2.nodes` (23), and `Environment -> SandboxedEnvironment` (22). All 124 Jinja candidates remained `INSUFFICIENT_EVIDENCE` when run through `verify.py` with no independent behavioral oracles. The pinned checkouts remained clean.

[GitHub acceptance run](https://github.com/laurajoyhutchins/h11/actions/runs/42560558525) passed 31 standard-library unit tests across selector, discoverers, and verifier. The workflow ran the same selector twice on each source and confirmed byte-identical output.

[Machine-readable observed results](jinja_observed.json) records every selected candidate, score, source reference and selected JSON SHA-256. The original source-only candidate graphs and selected JSON can be regenerated with the commands above; ephemeral runner files were not uploaded as an Actions artifact.

## An important negative finding

On h11, our original, **independently mutation-tested** reader/writer composition contract was **not selected in the top three**.

The ranking chose two Sentinel-derived classes and the event module instead, because widely imported support types scored highly. That is evidence of an actual prioritization weakness. Deterministic structural scoring is not the same as recognizing a valuable behavioral boundary.

We deliberately did not adjust the frozen weights after seeing Jinja. The next evaluation should **measure the value of selected boundaries against independent oracles and fault models**, ideally using an additional untouched holdout and comparing against a simple random or file-size baseline. Do not score the experiment by candidate count alone.

## Limitations

Static test imports do not show execution or coverage. Inheritance may express implementation mechanics rather than contract strengthening. The scoring favors high-reach source and does not independently establish expected consequences of a behavioral fault. No Jinja behavioral property has been verified. No runtime instrumentation or new target code is required for the selection operation.

All research modifications are isolated to `research/synthetic-history-evidence`. Upstream repositories and generated source-identical histories are unchanged.
