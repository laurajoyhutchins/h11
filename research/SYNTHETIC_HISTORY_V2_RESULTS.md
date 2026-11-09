# Synthetic history experiment: verified v2

## Result

**All 13 synthetic checkpoints pass h11's original pytest tests on Python 3.13**, and the final v2 Git tree is identical to the original source tree. No source files in `master` or the synthetic-history branches were modified.

- Source commit: `62c5068c971579d61fa1b55373390e12f25fd856`
- v2 final commit: `e8c7aeb18731b31cc68d0e658daab6d07773c85e`
- Both tree IDs: `5a1cacdb9d0d6e8d18e8161924ae18130da6c130`
- [Passing GitHub Actions run](https://github.com/laurajoyhutchins/h11/actions/runs/42549554689)
- [Machine-readable checkpoint result](synthetic_history_v2_verification.json)
- [Corrected synthetic history](https://github.com/laurajoyhutchins/h11/commits/research/synthetic-history-v2)

| Stage | Original tests |
| --- | ---: |
| 01 Foundation | 6 passed |
| 02 Header implementation | 6 passed |
| 03 Events + header tests | 12 passed |
| 04 State machine | 22 passed |
| 05 Receive buffer | 26 passed |
| 06 Reader | 26 passed |
| 07 Writer branch | 26 passed |
| 07b Reader/writer merge | 26 passed |
| 08 Connection | 78 passed |
| 09a Packaging branch | 78 passed |
| 09b Documentation branch | 78 passed |
| 10 Packaging/docs merge | 78 passed |
| 11 Complete repository | 78 passed |

There were **540 successful upstream pytest test invocations** across the checkpoints, **not** 540 distinct test cases. The complete library exposes 78 passing tests. Environment: Ubuntu 24.04, CPython 3.13.18, pytest 9.0.2, one GitHub Actions job. The workflow explicitly fails if any checkpoint fails or if final tree identity differs.

### Why v2 was necessary

v1 grouped each module's tests with the module it exercises. However, the original `h11/tests/test_headers.py` imports `h11._events.Request`, which is introduced after `h11/_headers.py`. Thus the v1 header checkpoint could not collect its test suite, even though the production module had no corresponding runtime dependency. v2 introduces the original `test_headers.py` alongside `_events.py`, allowing all 13 checkpoints to pass without changing a single upstream source blob.

The lesson is that **test dependencies are not always the same as implementation dependencies**. They should be modeled as first-class edges when constructing explanatory history.

### Execution caveats

The early original snapshots do not contain a public `h11/__init__.py`. The workflow creates an **empty temporary test-only import shim**, checks module isolation, invokes the original pytest suite, and deletes the shim afterward. The shim is not a source commit, but it means those early Git trees are not literally independently installable packages. The later five checkpoints run with the original `__init__.py`.

The synthetic Git graph still descends from the original Git head because the connected commit-object API requires a parent. It is *not* an independent root or a recovered true development chronology.

## Navigation comparison (exploratory pilot)

A local deterministic BM25 retrieval test used **nine architecture-location questions**, matching source code against summaries from the published synthetic commits. Both corpora used the same tokenization and ranker.

| Metric | Source module search | Synthetic commit summaries |
| --- | ---: | ---: |
| Candidate documents | 11 | 8 |
| Correct location ranked #1 | 6/9 | 7/9 |
| Correct location among top 3 | 8/9 | 9/9 |
| Mean rank of correct location | 2.111 | 1.333 |

This is **not a controlled productivity study**: queries were authored retrospectively, summaries were manually selected from published commit descriptions, candidate corpora differ in size and composition, and no developer/agent was timed. The numbers only show that commit descriptions are a plausible searchable architectural index. The pilot does *not* prove faster comprehension or better reasoning.

## Remaining work

1. Assess installability and public API evolution at early checkpoints, independently of the temporary test shim.
2. Run compatibility checks on additional supported Python versions if meaningful for the experiment.
3. Design a blinded evaluation with unfamiliar questions, equal search budget, and expert-graded answer correctness, comparing ordinary repository search versus source search plus explanatory history.
4. If reusable beyond h11, implement a generator that derives dependency layers and makes exact Git trees deterministically, recording test dependencies separately from production dependencies.

All code changes for verification live on `research/synthetic-history-evidence`, not on either explanatory source branch.
