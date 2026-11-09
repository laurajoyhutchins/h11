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

## Where this points

The source import poset may be a useful **index** into the already-existing Git Merkle DAG. A separate attestation ledger can attach bounded semantic contract evidence and dependency links without introducing a second storage system or inventing a unique chronology.

A future development task could specify a contract and expected prerequisites, then name exact Git source objects and evidence required to establish it. Agent branches could advance independently, but an integration node would still need explicit checks that combined behavior preserves its contracts.

Not established by this experiment: that static import dependencies constitute full semantic prerequisites; that every structural ideal is a separately installable or runnable package; that independently verified claims remain valid after arbitrary Git merges; or that this arrangement improves developer productivity.
