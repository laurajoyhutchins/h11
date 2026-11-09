# Contract discovery: source-derived candidates

This is a **read-only Python standard-library experiment**, not a new framework.
It makes no external requests, imports no code from the target repository, and
does not read the earlier hand-written contract ledger.

## Usage

From this Git working tree:

```bash
python research/contract_discovery/discover.py . --package h11 \
  --output /tmp/h11-discovery.json
```

For other packages, specify the repository root and Python package:

```bash
python research/contract_discovery/discover.py /path/to/repo \
  --package package_name \
  --tests package_name/tests \
  --output /tmp/discovery.json
```

The repository root must contain the package directory (for a `src/` layout, pass
the source root). Output is deterministic JSON, including Git-compatible blob SHA-1
values for the inspected Python files.

The discoverer records:
- Runtime and type-only imports, unresolved/dynamic-import warnings, and module closures
- Cyclic runtime-import components
- Candidate sibling modules that independently feed a common downstream importer
- Families of corresponding class names across those siblings
- The original tests' runtime imports, including transitive imports through test helpers
- Dependencies appearing in an original test but not in the implementation module's runtime closure

The ranking is intentionally simple: `5 × matching class families + 2 × common
module dependencies + up to 2 uppercase-binding indicators`. Its scores are a
**search heuristic**, never a claim of correctness or contractual sufficiency.

## Independent acceptance

The pinned original h11 snapshot is `62c5068c971579d61fa1b55373390e12f25fd856`.
In [GitHub Actions run 42555291160](https://github.com/laurajoyhutchins/h11/actions/runs/42555291160),
the discovery algorithm passed five tests on a separate toy package and then
analyzed the original h11 source **without the manually created contract graph**.

The held-out evaluation recovered 11 implementation modules and nine original
test files. It found precisely one sibling-pair candidate: `h11._readers` and
`h11._writers`, converging at `h11._connection`. The three matched class
families were Chunked, ContentLength, and Http10.

It also detected a meaningful difference between source and test dependencies:
`h11._headers` references `h11._events` only for type checking, while the
original `test_headers.py` imports `h11._events` at runtime. Consequently,
the test must not be placed in a checkpoint that excludes events.

Full derived JSON was generated in the runner and authenticated with SHA-256
`8dff3d01c4ff684e509a420d1f5a08ebc227475a9adbfb97ad29033ac613c499`.
The result summary is in [h11_result_summary.json](h11_result_summary.json).
Run the CLI to regenerate the full JSON; it does not require the GitHub workflow.

## Boundaries

A *candidate slice* is not an independently executable or installed Python
distribution. Importing a package submodule can execute `__init__.py`, and
some runtime imports may be conditional or dynamically generated. Analysis of
those behaviors needs a separate verifier.

Likewise, class-name similarity does not specify how data should flow through
reader and writer. This discoverer does not infer semantic guarantees, oracle
tests, or mutation scores from names. Those belong in a later **verify()**
step, with explicit independent evidence and room for unsupported results.

The ranking is tested on h11 and one toy package, not on a representative
population of unfamiliar repositories. The experiment doesn't yet establish
better documentation, faster navigation, or semantic minimality.

## Research files

- [discover.py](discover.py): production library and CLI
- [test_discover.py](test_discover.py): source-agnostic unit tests
- [evaluate_h11.py](evaluate_h11.py): separate h11-specific acceptance oracle
- [h11_result_summary.json](h11_result_summary.json): verified observed result
- [CI workflow](../../.github/workflows/source-contract-discovery.yml): one bounded runner, no artifact upload or remote source mutation

This research is intentionally isolated on `research/synthetic-history-evidence`.
The original `master` and existing contract-generated history are unchanged.
