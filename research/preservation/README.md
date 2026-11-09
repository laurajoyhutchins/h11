# Preserve contract evidence across a real implementation change

This research branch keeps production h11 unchanged. The CI experiment
constructs two local Git trees: the unchanged writer and a new writer
implementation that builds HTTP chunk-length hex digits bitwise instead of
using Python's percent formatter. Their only Git source change is inside
`ChunkedWriter.send_data`. The rewritten implementation is not pushed.

## Claims and proof obligations

The contract is restricted to **112 explicit valid input traces** and a
nonthrowing, ordered byte-collecting writer callback. Four traces are exact
inputs from the earlier native composition tests. Six segment sizes were
tested in that earlier suite; the new baseline additionally executes its
reader on four segment sizes for all 112 traces.

The checker enforces the following:

1. The candidate differs from its immediate Git parent solely inside
   `ChunkedWriter.send_data`; all other Git-tracked source is identical.
2. The baseline and candidate have exactly equal *ordered write-callback
   traces* on all 112 input traces. Concatenated wire bytes alone are not
   enough to establish this.
3. The baseline reader reconstructs expected payload, trailers and unread
   suffix for all 112 inputs and four fragmentation sizes (448 observations).
4. Because the reader source is unchanged and the candidate writer emits
   the same bytes for these inputs, the composition observations are carried
   by trace congruence **without executing the candidate reader**.
5. The pre-existing native CI evidence is validated through its existing
   Git/JUnit/in-toto consumer, including exact file identities, test
   observations, GitHub run metadata, and matching execution environment.
6. The four original composition fixtures are checked byte-for-byte
   against that prior test's own source. This carries its **24 previous
   composition observations** (four fixtures × six segment sizes) under
   the declared assumptions.

The previous reader test claim survives under its prior Git dependency
boundary. The old **standalone writer test claim is only partially
transported**: the four original composition fixtures are covered, but
not every input in the standalone writer test. `prior-reference.json`
marks this distinction explicitly. No claim of universal Python
equivalence, complete HTTP correctness, or automatic semantic dependency
discovery is made.

## Standard evidence artifacts

The workflow emits:

| File | Contents |
| --- | --- |
| `preservation.json` | 112 checked trace equalities, source identity and the premises for two carried downstream claims |
| `prior-reference.json` | Authenticated prior evidence identity, SHA-256 hashes, claim lineage, original fixture mapping, and partial/full transfer boundaries |
| `preservation.intoto.json` | Unsigned in-toto Statement v1 / Test Result v0.1 with **227 executed checks**, not falsely claiming downstream tests ran |
| `candidate.patch` | Git diff from the publicly accessible baseline to the local candidate, checked byte-for-byte against the actual Git objects |
| `baseline-observations.json`, `candidate-observations.json` | Deterministic baseline and candidate observations |

Other artifacts include a deliberately defective writer observation.
The harness must reject that mutation, a forged candidate observation,
an altered in-toto status, a forged prior in-toto result, and a
supposedly successful result for a failed prior GitHub run.

The original producer evidence comes from
[GitHub Actions run 42667731213](https://github.com/laurajoyhutchins/h11/actions/runs/42667731213).
The full proof-obligation and provenance integration passes in
[the linked preservation run](https://github.com/laurajoyhutchins/h11/actions/runs/42677871962).

## Reproduction

Use a full checkout of `research/contract-preservation` with
CPython 3.13, `pytest==9.2.0`, Git, and the GitHub CLI
authenticated to read Actions artifacts.

```bash
python -m pip install pytest==9.2.0
PYTHONPATH=research/preservation python -m unittest \
    discover -s research/preservation -p 'test_*.py' -v

mkdir -p /tmp/h11-old-evidence /tmp/h11-preservation-work
gh api repos/laurajoyhutchins/h11/actions/runs/42667731213 \
    > /tmp/h11-prior-run.json
gh run download 42667731213 --repo laurajoyhutchins/h11 \
    --name native-contract-evidence --dir /tmp/h11-old-evidence

python research/preservation/run.py \
    --source . --work /tmp/h11-preservation-work \
    --prior-artifacts /tmp/h11-old-evidence \
    --trusted-run /tmp/h11-prior-run.json
```


The in-toto statement is **unsigned**; GitHub's authenticated run metadata
is a trust input, not a cryptographic attestation signature. The candidate
commit is local to the CI runner; its patch and resulting Git tree identity
are published for independent reconstruction. The composition rule assumes
the pinned reader is deterministic in the tested context. Environment,
external dependencies, dynamic imports and arbitrary callback behavior are
outside the proven boundary. Claims of behavior beyond the finite domain
must return **unsupported**, not silently inherit this certificate.
