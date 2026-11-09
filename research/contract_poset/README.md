# Git Merkle objects as a projection of two partial orders

This experiment asks whether existing Git objects can represent software construction states **without reconstructing a synthetic chronological story**.

**Result:** yes for source-module dependency closures, with an explicit and important separation between structural and semantic claims.

## Two different posets

1. **Structural import poset.** Nodes are exact, original Python source modules, identified by source-relative paths and original Git blob SHA-1 IDs. An edge `a -> b` means `b` statically imports `a` at runtime. The implementation uses the transitive reduction for display, but checks the full closure. This establishes module dependencies, *not* semantic implication.
2. **Explicitly attested contract poset.** Nodes are the previously authored chunked-reader, chunked-writer, and composition claims. Their dependency edges are declared in [h11_claim_links.json](h11_claim_links.json), which links the original [contract ledger](../contract_history/contracts.json) to the earlier [independent verification summary](../contract_verify/h11_verified_summary.json). They are **not inferred** from import edges or Git commit parents.

For a finite poset `P`, let `J(P)` denote its set of order ideals: subsets closed under prerequisites. These ideals form a distributive lattice under `A ∧ B = A ∩ B` and `A ∨ B = A ∪ B`.

The h11 source-only runtime-import graph has **11 modules, 11 transitive-reduced cover edges, and exactly 39 order ideals**. The explicit three-claim graph has **five** order ideals:

```text
               {reader, writer, composition}
                          |
                    {reader, writer}
                      /         \
                  {reader}     {writer}
                      \         /
                            {}
```

The diagram describes available sets of claims under explicitly supplied prerequisites. It is not the Git commit graph.

## Projection onto actual existing Git objects

The analyzer verifies the original tree `5a1cacdb9d0d6e8d18e8161924ae18130da6c130` at commit `62c5068c971579d61fa1b55373390e12f25fd856` and compares every source module's discovered blob ID with the existing Git tree.

It then reads each of the six already-existing synthetic history commits, **without producing new commits or trees**. For every stage it checks:

- Actual Git commit OID, parent OIDs, and Git tree OID exactly match the existing ledger.
- Every staged blob is identical to its original pinned upstream blob, including non-Python files.
- Every staged module subset is a downward-closed ideal of the original static import poset.
- Every generated stage extends the *module union* of its generated-stage parents, with the original Git commit recognized as an **external anchor**.
- The antichain of maximal modules reconstructs precisely the staged ideal.

| Existing Git checkpoint | Modules present | Structural interpretation |
| --- | ---: | --- |
| foundation | 6 | Common prerequisites |
| chunked-reader | 7 | Foundation + reader module |
| chunked-writer | 7 | Foundation + writer module |
| codec-composition | 8 | Exact join of reader and writer module ideals |
| connection | 11 | Additional connection-related implementation modules |
| complete | 11 | Same module ideal, more original non-module files |

The reader/writer meet contains **six** modules. Their union/join contains **eight**. The already-existing two-parent Git merge has exactly that union of module states.

**Two crucial distinctions:**

- The `connection` and `complete` commits have **different Git tree OIDs but the same module ideal**. Projection from Git snapshots to structural states is therefore many-to-one.
- The synthetic `foundation` commit has the complete original commit as its actual Git parent, yet the `foundation` tree is *smaller*. So Git ancestry cannot be interpreted as monotonic progression through source-module ideals. The genuine Git parent edge is an anchoring mechanism, not a semantic prerequisite.

Git commits are content-addressed nodes with parent links (a Merkle DAG); Git tree objects are Merkle trees representing filesystem snapshots. Neither directly specifies which behavioral claims are true. A source-module ideal union also does not establish that implementations compose without conflicts or bugs.

## Usage

Only trusted local source checkout and Git objects are read; no target package is executed:

```bash
python research/contract_discovery/discover_v2.py /path/to/original-h11 \
  --package h11 --tests h11/tests \
  --output /tmp/h11-discovery.json

python research/contract_poset/poset.py /path/to/evidence-branch-checkout \
  --discovery /tmp/h11-discovery.json \
  --stages research/contract_history/generated_commits.json \
  --contracts research/contract_history/contracts.json \
  --links research/contract_poset/h11_claim_links.json \
  --verified research/contract_verify/h11_verified_summary.json \
  --ref 62c5068c971579d61fa1b55373390e12f25fd856 \
  --ref e8d9391373d3ae3234abe4fe24d2ad0bc8116a81 \
  --ref HEAD \
  --output /tmp/h11-poset.json
```

### Existing Git refs, without history reconstruction

The same tool projects arbitrary **existing** commit refs onto the pinned source-module basis. It allows unrelated additional files but marks changed module blobs `INCOMPATIBLE_SOURCE_VERSION`, rather than silently treating another implementation as the original.

The expanded experiment used three existing Git revisions:

| Git revision | Tree object | Paths added beyond original | Module state |
| --- | --- | ---: | --- |
| Original upstream commit `62c5068` | `5a1cacd` | 0 | All 11 modules |
| Existing generated-history final `e8d9391` | `5a1cacd` | 0 | All 11 modules |
| Research evidence commit `c7b3b2c` | `c17c8a1` | 59 | All 11 modules |

All three mapped to the **same source-module ideal ID**. The first two commits are different but have the same Git tree. The research revision has a different Git tree containing additional evidence, but exactly the same production module blobs. This is a direct projection of already-existing Git objects: no synthetic history needs to be created.

The source commit and all synthetic stage Git objects must be reachable in the supplied repository. The workflow checks these through the repository's full Git checkout, and uses a separate worktree to generate discovery JSON from the pinned source revision.

The Git object projection has no non-standard Python dependencies. It is verified by ten local structural/lattice tests and a pinned Git integration run.

- [Implementation](poset.py)
- [Unit tests](test_poset.py)
- [Pinned observations](h11_observed.json)
- [Passing GitHub Actions run](https://github.com/laurajoyhutchins/h11/actions/runs/42565274439)

The complete report generated in CI is identified by SHA-256 `cadbefe192861b873307b35770df35e22ee0dd39b709ab07d02c3643ee932453`. The observed JSON is a compact summary; it does not duplicate the full generated report.

## Carrying previous evidence across Git branches

The [source-identity evidence index](evidence_index.py) consumes the discovered runtime import graph, existing contract specifications, explicit semantic prerequisites, and prior independent-oracle evidence. It checks exact Git blob IDs and file modes for the entire declared source closure of each claim, rather than merely its defining source file.

A claim is `REUSE_ELIGIBLE` only if its earlier bounded oracle reported verification and killed at least one selected semantic mutant; every file in its source closure has the identical original Git object; no dynamic or unresolved imports remain; and all its explicitly declared prerequisite claims are eligible. Otherwise the index returns `REVERIFY_REQUIRED` with precise reasons and affected modules. Even comment-only edits conservatively invalidate source-identity reuse.

The index works on arbitrary existing Git revisions and **does not require a synthetic stage ledger**:

```bash
python research/contract_poset/evidence_index.py /path/to/repository \
  --discovery /tmp/h11-discovery.json \
  --contracts research/contract_history/contracts.json \
  --links research/contract_poset/h11_claim_links.json \
  --verified research/contract_verify/h11_verified_summary.json \
  --ref 62c5068c971579d61fa1b55373390e12f25fd856 \
  --ref HEAD \
  --output /tmp/evidence-reuse.json
```

The [passing experiment](https://github.com/laurajoyhutchins/h11/actions/runs/42566035112) ran 20 tests, including two independent disposable Git branches and a real two-parent merge:

| Revision | Reader evidence | Writer evidence | Composition evidence |
| --- | --- | --- | --- |
| Original Git source | Eligible | Eligible | Eligible |
| Documentation-only commit | Eligible | Eligible | Eligible |
| Reader implementation changed | Reverify | Eligible | Reverify |
| Writer implementation changed | Eligible | Reverify | Reverify |
| Merge of independent changes | Reverify | Reverify | Reverify |

The original source revision, existing source-identical synthetic-final revision, and current research revision all retain source-identity eligibility for three previously reported bounded contract claims. Scratch mutation commits were local to CI and were not pushed. [Machine-readable evidence](evidence_reuse_observed.json) retains the matrix and CI report digest.

**Interpretation limit:** `REUSE_ELIGIBLE` does not mean fresh verification was executed or that a changed whole program or merge is safe. The earlier independent evidence was established in isolated oracle contexts using temporary package shims. A changed initializer, an added integration path, external dependencies, or a different execution environment may still affect behavior. The index consumes a prior verification summary and does not independently authenticate that remote workflow on every read.

## Frozen falsification retest: generated package initialization edges

The original 213-comparison protocol was committed before its first results and has not been modified. After its import-only predictor missed three package-initializer mutations, the evaluation driver gained a **separate opt-in mode**: `--include-package-initializers`. The original default remains the frozen control.

Under the corrected mode, each imported Python module also depends on existing parent package `__init__.py` modules. The generator recursively includes imports appearing inside those initializer modules. Nested package parents are included; no dependency list is hand-written.

Run the original and corrected predictors on the same pinned protocol:

```bash
python research/contract_poset/falsification.py \
  --protocol research/contract_poset/falsification_preregistration.json \
  --checkout-root /tmp/import-control \
  --output /tmp/import-control.json
python research/contract_poset/falsification.py \
  --protocol research/contract_poset/falsification_preregistration.json \
  --checkout-root /tmp/init-corrected \
  --include-package-initializers \
  --output /tmp/init-corrected.json
```

The [passing side-by-side CI replay](https://github.com/laurajoyhutchins/h11/actions/runs/42633777477) compared all 210 historical and three previously constructed adversarial revisions with the same independent behavioral oracle on each revision. The corrected closure added exactly one package initializer per repository.

| Metric | Frozen control | Generated initializer closure |
| --- | ---: | ---: |
| Attempted comparisons | 213 | 213 |
| Assessable | 157 | 157 |
| Missed observable changes | **3** | **0** |
| Estimated oracle execution time saved | 5.0% | 0.8% |

Every original miss was an explicit `__init__.py` mutation. The corrected predictor now chooses `REVERIFY` for all three. Five unit tests additionally cover root and nested initializers, imports made by initializers, missing optional namespace initializers, and cyclic imports.

This is a bounded correction, not a proof that Python's complete behavioral dependencies have been recovered. The 56 unassessable historical revisions remain unassessable. The corrected predictor still cannot prove semantic closure for dynamic imports, runtime state, configuration or external environment. The observed efficiency remains far short of the originally proposed 50% target.

Evidence: [machine-readable retest summary](initializer_retest_observed.json), [frozen protocol](falsification_preregistration.json), [unit tests](test_initializer_closure.py). The full control, corrected and comparison JSON files are retained as a GitHub Actions artifact on the passing run, with SHA-256 hashes in the summary.

## Where this points

The source import poset may be a useful **index** into the already-existing Git Merkle DAG. A separate attestation ledger can attach bounded semantic contract evidence and dependency links without introducing a second storage system or inventing a unique chronology.

A future development task could specify a contract and expected prerequisites, then name exact Git source objects and evidence required to establish it. Agent branches could advance independently, but an integration node would still need explicit checks that combined behavior preserves its contracts.

Not established by this experiment: that static import dependencies constitute full semantic prerequisites; that every structural ideal is a separately installable or runnable package; that independently verified claims remain valid after arbitrary Git merges; or that this arrangement improves developer productivity.
