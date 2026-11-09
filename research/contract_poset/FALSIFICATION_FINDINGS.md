# Falsification result: implicit initialization defeats import-only evidence reuse

**Verdict:** The preregistered static-import closure predictor was falsified. It claimed reuse in three revisions whose independent public behavioral-oracle observations changed. The Git blobs belonging to all explicitly discovered import-closure modules remained unchanged.

## Precommit protocol

The protocol was committed at `640352a1b16182e9f145a549c227fb650347c492` before the evaluation. It pinned three previously unused source repositories (Blinker, HPACK, and Hyperframe), their exact commits, 70 historical first-parent revisions per repository, one public behavioral oracle each, and a specified package-initializer adversarial mutation for each. A changed successful oracle observation paired with a `REUSE` prediction counted as a counterexample.

## Observations

| Repository | Historical comparisons | Assessable including adversarial | Missing changes predicted safe | Estimated net oracle-time savings |
| --- | ---: | ---: | ---: | ---: |
| Blinker | 70 | 71 | 1 | 3.8% |
| HPACK | 70 | 50 | 1 | 12.9% |
| Hyperframe | 70 | 36 | 1 | -5.7% |
| **Total** | **210** | **157/213** | **3** | **6.2%** |

All three misses were deliberately constructed initializer changes, not historical production defects. None of the 154 assessable historical revisions produced a missed observable change. The 56 unassessable comparisons were retained in the report as unresolved, not counted as successful predictions.

### Minimal counterexample mechanism

A Python import of `package.module` executes `package/__init__.py`. The predictor tracked only the source modules reached by explicit AST imports of the module. In each repository, that closure omitted `package/__init__.py`.

Each adversarial Git commit changed **only** this omitted initializer, monkey-patching the public implementation at import time:

- Blinker: `Signal.send` returned no connected callbacks.
- HPACK: `Encoder.encode` returned an empty header block.
- Hyperframe: `DataFrame.serialize` produced a valid empty DATA frame rather than the original payload.

The original implementation source blobs stayed identical, the predictor returned `REUSE`, and each independent oracle observed changed behavior.

Formally, if `I(S)` is the vector of blob identities for the import-only closure and `O(S)` is the independent oracle observation, the counterexamples satisfy:

```text
I(S) = I(S')
O(S) != O(S')
```

Thus equality of the tracked static closure is **not sufficient** for observational equivalence. This is about the tested naive predictor, not a theorem that Git-backed verification can never be sound. A model that explicitly accounts for Python package initialization would not make these particular mistakes.

## Interpretation of the performance result

The measured 6.2% saving is a counterfactual from the actual full-oracle subprocess durations plus indexing overhead. It excludes checkout and clone time and is conditional on 157 assessable comparisons. It **does not** constitute a completed, representative test of the preregistered 50% economic threshold, because 56 cases were unassessable under the frozen Python 3.13 oracles.

The broader, practical lesson is that source identity makes reuse cheap only after we have justified the relevant semantic dependency boundary. Git hashing establishes byte equality, not the completeness of that boundary.

## Evidence and reproduction

- [Frozen protocol](falsification_preregistration.json)
- [Exact experimental driver](falsification.py)
- [Machine-readable observations](falsification_observed.json)
- [Successful GitHub Actions run](https://github.com/laurajoyhutchins/h11/actions/runs/42631274931)
- Full ephemeral report SHA-256: `44116cfcb6bbe81e3aa6d741620b81ac3d9ab9d633d98095b139ad1bdc73f296`.

No adversarial changes were pushed to the three third-party repositories. Original h11 master and the source-identical synthetic history were unchanged.

**Research outcome:** Reject static-import-closure identity as a sound standalone criterion for behavioral evidence reuse. The next research question is which additional dependency relationships must be established, and how to test their completeness without simply rerunning the full behavioral oracle set.
