# Synthetic Git history: checkpoint verification (2026-11-08)

This report is intentionally stored on `research/synthetic-history-evidence`, **not** on the reconstructed history branch, to preserve final-tree equality.

## Fixed reference points

- Source `master` commit: `62c5068c971579d61fa1b55373390e12f25fd856`.
- Synthetic explanatory head: `0a774d3953a5ab4f63fcb31ba77be0e54d71189d`.
- **Both have Git tree:** `5a1cacdb9d0d6e8d18e8161924ae18130da6c130`.
- Synthetic graph: 13 commits including 2 merges, anchored on the original source commit rather than an independent root.

## Local verification performed

Environment: CPython 3.13.5, pytest 9.0.2, Linux x86-64.

The local Python installation contains the same implementation source as the fork: SHA verification against GitHub established exact blob identity for `h11/__init__.py`, `_abnf.py`, `_connection.py`, `_events.py`, `_headers.py`, `_readers.py`, `_receivebuffer.py`, `_state.py`, `_util.py`, `_writers.py`, and `py.typed`. The single differing installed file, `_version.py`, was recovered directly via the GitHub connector and its original blob SHA `c8a0b4893126596bb925cd00135f420f6b0725d7` verified. These source files are byte-identical to the corresponding fork blobs.

Eight cumulative implementation checkpoints were reconstructed in local temporary directories. All eight passed isolated `python -S` import/protocol smoke probes and compilation checks. Isolation prevented falling back accidentally to the globally installed h11.

The fully integrated Connection checkpoint passed **15/15 independent pytest behavior cases**, covering client/server exchanges, fragmented input, headers, malformed messages, content-length conflicts, chunked encoding, premature EOF, state-transition rejection, and the exact development-version marker.

| Check | Result | Limits |
| --- | --- | --- |
| Final Git tree equality | **PASS** | Full original Git source tree, 69 blobs |
| Implementation file blob hashes | **PASS** | 11 Python files + `py.typed` |
| Intermediate isolated smoke probes | **8/8 PASS** | Through Connection stage only |
| Intermediate Python syntax | **8/8 PASS** | Through Connection stage only |
| Independent targeted pytest suite | **15/15 PASS** | These are not upstream tests |
| Original h11 pytest suite | **NOT RUN** | Upstream test sources unavailable in local VM |
| Packaging/docs/fuzz/CI checks | **NOT RUN** | Git structural checkpoints only |
| Controlled developer/agent navigation test | **NOT RUN** | Contract lookup audit only |

An initial draft probe expected an invalid transition for server `Response` in IDLE; the abstract state machine actually allows that transition. The probe was corrected to use the prohibited `Data` event, then passed. This was a test assumption error, not a discovered h11 defect.

## Navigation index (not a speed benchmark)

| Architectural question | Synthetic introduction | Source |
| --- | --- | --- |
| Which state transitions are legal? | [architecture(04)](https://github.com/laurajoyhutchins/h11/commit/7a384f41e01541ea1cdaa795d90746407bc253a1) | `h11/_state.py` |
| How are headers normalized and validated? | [architecture(02)](https://github.com/laurajoyhutchins/h11/commit/e482722939a4ad19bea96be0fe4a948751d66380) | `h11/_headers.py` |
| How is fragmented input buffered? | [architecture(05)](https://github.com/laurajoyhutchins/h11/commit/db1fff06d47fd43ace98c387fded033bd813d77a) | `h11/_receivebuffer.py` |
| How does byte input become protocol events? | [architecture(06)](https://github.com/laurajoyhutchins/h11/commit/15507e1ac95264e34e7a8d600538c83676b5c1d5) | `h11/_readers.py` |
| How are events written to bytes? | [architecture(07a)](https://github.com/laurajoyhutchins/h11/commit/0b9365e45d5b9bc21aede22f8b146edd9deda871) | `h11/_writers.py` |
| What composes the complete connection? | [architecture(08)](https://github.com/laurajoyhutchins/h11/commit/ec634e84d3efb2bb58cc5bae5887abaed2bdba79) | `h11/_connection.py` |

The mapping shows the history can serve as an architectural index. **It does not establish improved investigation speed** over ordinary code search.

## Important limitations

1. Early commits can run internal modules in a Python namespace package, but cannot be installed as a complete `h11` distribution because the real `__init__.py` imports later modules and is introduced at the Connection stage.
2. GitHub commit creation through the connected API requires a parent; the explanatory graph is attached to upstream history rather than rooted independently.
3. This is a verified **exact-blob structural decomposition**, not yet a fully verified series of distributable intermediate libraries.

## Next verification on a checkout

```sh
git clone https://github.com/laurajoyhutchins/h11.git
cd h11
git switch --detach ec634e84d3efb2bb58cc5bae5887abaed2bdba79
python -m pip install pytest
python -m pytest -q h11/tests
```

The last command **has not been executed** during this verification. It uses the original upstream tests available in the repository's synthetic Connection checkpoint.

After upstream tests, a controlled agent/human investigation comparing source-search-first with history-first is necessary to evaluate the actual documentation value.
