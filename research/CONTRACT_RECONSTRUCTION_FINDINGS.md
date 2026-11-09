# Investigation: does synthetic history establish architectural contracts?

Date: 2026-11-08 (Mountain Time)

Pinned upstream: `62c5068c971579d61fa1b55373390e12f25fd856`
Corrected explanatory head: `e8c7aeb18731b31cc68d0e658daab6d07773c85e`
Both have Git tree `5a1cacdb9d0d6e8d18e8161924ae18130da6c130`.

## Result: source-identical and test-passing does not imply contract verification

The 13 synthetic checkpoints passed original tests in [workflow 42549554689](https://github.com/laurajoyhutchins/h11/actions/runs/42549554689). This result is true, but a stronger claim does not follow.

We injected two *semantic* mutations temporarily into GitHub Actions checkouts in [workflow 42550927330](https://github.com/laurajoyhutchins/h11/actions/runs/42550927330):

| Mutation | At introduction | At integrated Connection stage |
| --- | --- | --- |
| `ChunkedReader` reads `chunk_size + 1` bytes | **26 original tests passed** (missed) | **6 failed, 72 passed** |
| `ChunkedWriter` emits `payload_size + 1` in the chunk header | **26 original tests passed** (missed) | **4 failed, 74 passed** |

Those early commits introduce the source files but no tests of their behavioral guarantees. All 26 inherited tests can pass while the just-introduced implementation is wrong.

**Implication:** Attach independent contract oracles to the capability introduction, not just existing tests accumulated from ancestor commits.

## Structural reconstruction: reproducible but not a unique narrative

Local Python AST analysis of all original implementation modules found:
- Runtime import graph over 9 core implementation modules (excluding `__init__.py` and `_version.py`).
- The graph permits **26 distinct topological orderings**, so source imports alone do not determine a canonical explanatory history.
- `_headers.py` imports `_events.Request` under `TYPE_CHECKING` only. Its **upstream tests**, however, import `_events.Request` at runtime. Test dependency edges must be modeled separately from implementation edges.

With isolated Python `-I -S` processes, exact original Git blob hashes and a temporary package `__init__.py` shim, computed import-closure probes gave:

| Isolated capability | h11 modules in import closure |
| --- | ---: |
| Protocol validation utility | 1 |
| Header normalization | 3 |
| Event construction | 4 |
| State transition check | 5 |
| Receive buffering | 1 |
| Chunked reader | 7 |
| Chunked writer | 6 |
| Full public Connection | 11 |

**8/8** closure probes passed, and **37/37** one-module-removal experiments caused their corresponding probes to fail. These demonstrate import-closure minimality *under the original source's module structure*, not minimum semantic implementation or sufficient external correctness.

## Independent contract oracles detect the semantic mutations at their introduction

A direct chunk-reader check requires `3\\r\\nabc\\r\\n0\\r\\n\\r\\n` to yield exactly `abc` and EndOfMessage. A direct chunk-writer check requires emitting those exact bytes for `abc`. Both pass on unmodified original source and fail with their matching +1 size mutation. These tests can run with only the reader/writer import closures rather than waiting for the Connection integration stage.

A separate deterministic randomized experiment passed **1,040** bounded cases (13 body sizes, content-length or chunked, 20 random segmentations per case and direction), preserving payload and message boundary under incremental receive and response serialization/parse. The seed is `260108`. These are finite probes, not an exhaustive protocol proof.

## Interpretation

**Git commit ancestry is a serialization of one compatible dependency order.** It does not create an independent proof or recover original design intent.

A more useful primitive is a *contract-bearing executable slice* with:
1. Explicit preconditions and externally checkable guarantees.
2. Exact source/blob closure and semantic dependency edges.
3. Independent oracles, property tests and known failure mutants.
4. Evidence for both the isolated contract and preservation under integration.
5. An explicit distinction among observed, derived and hypothesized claims.

Code dependencies and tests can *suggest* contracts, but a complete behavioral specification cannot generally be inferred uniquely from the finished implementation. In h11, a contract-first ledger would be primary; synthetic Git history would be an optional view generated from it.

## Reproducibility and limitations

- The GitHub Actions mutation workflow is `.github/workflows/contract-sensitivity.yml` on this evidence branch.
- Local AST analysis, ablations and property tests were executed on Python 3.13.5 with original file content checked against Git blob hashes. No original source was modified.
- The import-closed checkpoints required a temporary `h11/__init__.py` shim. This was never committed.
- Assertions establish finite behavioral observations, not formal verification over all HTTP inputs.
- No controlled human/agent productivity advantage from synthetic history has been established.
- The synthetic history is anchored to the original Git parent; it is not a separately rooted recovered history.

See the adjacent `contract_reconstruction_metrics.json` for machine-readable summary and workflow pointers.
