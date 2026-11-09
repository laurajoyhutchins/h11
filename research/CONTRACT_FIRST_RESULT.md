# Contract-first synthetic Git history: experimental result

Pinned source: `python-hyper/h11` forked into `laurajoyhutchins/h11`, source commit `62c5068c971579d61fa1b55373390e12f25fd856`.

Generated history: [`research/contract-generated-history`](https://github.com/laurajoyhutchins/h11/commits/research/contract-generated-history) at `e8d9391373d3ae3234abe4fe24d2ad0bc8116a81`.

Passing independent verification: [GitHub Actions run 42553548458](https://github.com/laurajoyhutchins/h11/actions/runs/42553548458), Ubuntu 24.04, Python 3.13.18.

## Findings

The contract graph, not a manually chosen development narrative, defines the materialization stages:

```text
exact upstream original head
  └── shared import closure
       ├── ChunkedReader contract  ──┐
       └── ChunkedWriter contract  ──┤
                                     └── composition merge
                                           └── Connection integration
                                                 └── exact complete upstream tree
```

The original `master` tree and generated final tree are **exactly identical**: `5a1cacdb9d0d6e8d18e8161924ae18130da6c130`.

The independent oracles pass at their respective commit introductions and detect all six targeted semantic mutations:

| Contract | Original check | Mutations killed |
| --- | --- | --- |
| Chunked reader | PASS | 3/3: chunk-size +1, incorrect footer, discarded trailers |
| Chunked writer | PASS | 3/3: chunk-size +1, malformed footer, incorrect final chunk |
| Codec composition | PASS | No mutation candidates in this experiment |

The full reconstructed source tree additionally passes all **78 original h11 pytest tests**.

The verifier independently recomputes all six Git tree object IDs from original blob SHAs, verifies each parent relationship, checks Python runtime import-closure claims against source, and compares the final tree with the pinned original commit. The current GitHub workflow fails if any of these checks or the mutation checks fail.

## Source-of-truth artifacts

- [contracts.json](contract_history/contracts.json): explicit assumptions, guarantees, dependency closures, and mutation targets
- [generated_commits.json](contract_history/generated_commits.json): concrete Git commit and tree SHA ledger
- [verify_materialization.py](contract_history/verify_materialization.py): deterministic Git-tree hash and ancestry verifier
- [verify_contracts.py](contract_history/verify_contracts.py): independent reader, writer, composition oracles and semantic mutant checks
- [GitHub workflow](https://github.com/laurajoyhutchins/h11/blob/research/synthetic-history-evidence/.github/workflows/contract-generated-verify.yml): executable acceptance
- [Passing verification run](https://github.com/laurajoyhutchins/h11/actions/runs/42553548458)

## What this establishes, and what it does not

**Established:** two production codec modules can be separated with exact original blob identity; each has an executable behavioral contract with locally killed targeted semantic mutations at its own introduction; the combined codecs pass composition checks; exact final tree identity is maintained.

**Not established:** formally complete HTTP/1.1 semantics, proof for all possible inputs, semantic minimality below Python module boundaries, independent installability of earlier stages, a unique architectural ordering, or improved comprehension by developers/agents. Earlier stage contracts run against original module import closures with an **uncommitted temporary package-import shim**. The source tree is unchanged, but these checks do not prove the early snapshots are installable distributions.

The generated graph is still parent-anchored to the original Git head because the available GitHub commit-object connector requires an existing parent. It is not claimed to reconstruct actual chronology.

## Interpretation

The experiment supports treating **contract-bearing executable slices** as primary architectural data. Git history becomes a convenient content-addressed representation of one construction consistent with their dependencies. The improvement over the original file-first synthetic history is not an aesthetic commit sequence: **a newly introduced behavior must withstand targeted attempts to falsify it at its introduction**.

Further work should test contract completeness using additional, independently specified properties and a blinded evaluation of architecture comprehension rather than assuming the generated history provides a speed advantage.