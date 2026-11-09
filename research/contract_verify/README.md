# Verification of discovered Python contract boundaries

The source-only discoverer identifies candidate architectural boundaries. It does not invent behavioral specifications. The separate verifier consumes discovery JSON and independently supplied unittest oracles and semantic mutants.

## Commands

Discover from a pinned source tree:

    python research/contract_discovery/discover.py /path/to/source --package h11 --output /tmp/discovery.json

Check without external behavioral claims:

    python research/contract_verify/verify.py /path/to/source --discovery /tmp/discovery.json --output /tmp/without-oracles.json

Check with explicitly authored, trusted independent oracles:

    python research/contract_verify/verify.py /path/to/source --discovery /tmp/discovery.json --plan research/contract_verify/oracles/plan.json --oracles research/contract_verify/oracles --output /tmp/with-oracles.json

The default (no oracle) result is INSUFFICIENT_EVIDENCE, never a green contract. No PyPI dependencies are needed. Python 3.13 is the tested baseline.

## What the verifier establishes

1. Every production module SHA-1 Git blob must match the source snapshot recorded by discovery before any oracle runs.
2. Oracle cases must select one or both modules in an actual discovered sibling candidate. The source import closure is copied into a scratch Python package, with a temporary package-init shim to avoid importing unrelated source.
3. Each trusted unittest oracle runs through an isolated-import subprocess with Python -I -S and a timeout. This is an import-contamination control, NOT a security boundary.
4. A baseline oracle must run one or more tests, without failures, errors or skips.
5. A targeted semantic mutant must match exactly one source snippet. It is killed only when the oracle reports an assertion failure without import/test errors.
6. The output records source/plan digests, oracle digest, the tested closure, baseline results, and every mutation verdict.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| VERIFIED_WITHIN_SCOPE | Original passes the supplied oracle and every selected semantic mutant fails by an assertion |
| INSUFFICIENT_EVIDENCE | Missing oracles, missing mutation challenge, or a mutant survives |
| CONTRADICTED | Original source fails the supplied independent behavioral assertion |
| BLOCKED | Snapshot mismatch, invalid mutation, missing tests or harness failure |
| UNSUPPORTED | Dynamic imports make the selected static source closure unjustified |

The supplied claims are NOT inferred from class names. A finite mutation set does not constitute formal verification or guarantee complete protocol behavior. Execute only trusted oracles inside a disposable VM.

## h11 experiment

The bounded GitHub Actions workflow analyzes original commit 62c5068c971579d61fa1b55373390e12f25fd856, without consulting the hand-authored contract ledger.

The source-only discovery recovers the independent h11._readers / h11._writers pair converging at h11._connection.

- No independent oracles: INSUFFICIENT_EVIDENCE.
- Independent reader, writer and composition oracles: VERIFIED_WITHIN_SCOPE for their specific claims.
- Eight semantic mutants detected: three reader, three writer, two composition.
- Nine generic verifier engine tests pass on an unrelated toy package.
- Original source Git tree remains 5a1cacdb9d0d6e8d18e8161924ae18130da6c130.

Passing workflow: https://github.com/laurajoyhutchins/h11/actions/runs/42556847427

The workflow logs a SHA-256 of its full evidence JSON, but does not upload a CI artifact. Rerun the commands above to reproduce it.

The next question is whether these boundaries and useful independent oracles can be established on a completely unfamiliar project without relying on developer-selected cases.
