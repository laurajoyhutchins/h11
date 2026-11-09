# Native contract verification in existing CI

This is an additive pilot in the real Python h11 repository. The checked-out h11 package and its existing pytest tests are authoritative. No historical evidence ledger is relabeled as a fresh result.

The runner invokes the real test_ChunkedReader and test_ChunkedWriter tests, 30 new chunked-codec composition cases exercising payloads, trailers, fragmentation and unread suffixes, and the existing Python package-initializer regression tests.

Artifacts generated from each CI execution:

- results.xml: ordinary pytest JUnit XML with individual testcases.
- test-result.intoto.json: unsigned in-toto Statement v1 / Test Result v0.1. Subjects bind the exact Git commit, tree, and SHA-256 of relevant source files. Configuration binds test sources and JUnit XML bytes.
- limitations.sarif: SARIF 2.1.0 warning on the intentionally unsound research-only import-closure control, grounded in a freshly rerun regression. This is not a security vulnerability claim.
- claim-results.json: an explicit mapping of four bounded claims to observed tests, not formal proof or an automatic permission to reuse evidence.

The runner refuses green results if required test groups disappear, tests fail or skip, the checkout differs from the triggering commit, or tests mutate tracked sources. It never imports archived experiment results.

Reproduction from a checkout with pytest installed:

    PYTHONPATH=research/ci_evidence python -m unittest -v test_exporter
    python research/ci_evidence/run.py --expected-commit "$(git rev-parse HEAD)" --output-dir /tmp/h11-native-evidence

This workflow is scoped to the research/native-contract-ci-evidence branch and does not change the upstream test matrix. It reuses Git, pytest, JUnit XML, in-toto and SARIF. The statement is unsigned and its run linkage does not provide a cryptographic signature.


## Source-identity evidence consumer

The companion consumer in `consume.py` verifies:

- The prior statement is in-toto Statement v1 / Test Result v0.1 and reports PASSED.
- The JUnit testcase observations, required claim ledger, and all evidence digests agree.
- The statement's source blobs and config digests match actual Git objects at the prior commit.
- A generated `dependencies.json` manifest matches the complete tracked h11 package and explicitly named test/configuration files, including Python package initializers.
- The producer run metadata is obtained via authenticated GitHub API, with the expected repository, workflow, branch, exact commit, and successful conclusion.
- The current execution fingerprint matches the recorded fingerprint, and the current tracked and untracked package inputs are clean.

It returns `REUSE` only for identical dependencies within that declared boundary. Changes to any tracked package source, test, or configuration file produce `REVERIFY`. Invalid attestations, missing manifests, dirty checkouts, or environment changes produce `UNKNOWN`. The research CI workflow runs native tests on both non-reuse outcomes. None of these decisions is a proof that arbitrary Python has no undeclared runtime dependencies.

The pinned pilot producer run is [42667731213](https://github.com/laurajoyhutchins/h11/actions/runs/42667731213). The actual downstream consumer run [42669878323](https://github.com/laurajoyhutchins/h11/actions/runs/42669878323) reused all four bounded claims and skipped h11's native tests after validating the prior evidence. That same run introduced a local-only bug into the chunked reader and verified that the new Git commit was classified `REVERIFY`; h11's original reader test failed, as expected. No adversarial revision was pushed to the remote repository.

Reproduce the consumer with Python 3.13 and pytest 9.2.0 in a full Git checkout:

```bash
PYTHONPATH=research/ci_evidence python -m unittest -v test_consume
GH_TOKEN=... gh api repos/laurajoyhutchins/h11/actions/runs/42667731213 \
    > /tmp/trusted-run.json
GH_TOKEN=... gh run download 42667731213 \
    --repo laurajoyhutchins/h11 --name native-contract-evidence \
    --dir /tmp/h11-prior-evidence
python research/ci_evidence/consume.py \
    --prior-artifacts /tmp/h11-prior-evidence \
    --trusted-run /tmp/trusted-run.json \
    --target-commit "$(git rev-parse HEAD)" \
    --output /tmp/h11-reuse-decision.json
```

The current workflow pins a specific successful producer run for this controlled test. It is not a general artifact-discovery or trust service.

## Held-out adversarial and historical evaluation

The separate [held-out workflow](https://github.com/laurajoyhutchins/h11/actions/runs/42669783406) compared historical first-parent revisions 71 through 90 in three public repositories, beyond the original study's 70 revisions per repository. Independent fixed oracles were executed in an ephemeral runner for every candidate. A second arm compared adjacent revisions to model normal incremental CI.

| Held-out arm | Reuse | Reverify | Unknown | Assessable | Missed changes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Each revision vs pinned head | 0 | 20 | 40 | 14/60 | 0 |
| Adjacent revision pairs | 8 | 5 | 47 | 13/60 | 0 |

The head-relative arm and adjacent arm used the same 60 historical revision positions. All eight reuse decisions came from Blinker. No reusable pair was demonstrated for HPACK or Hyperframe in this historical window. The 46 or 47 unassessable comparisons cannot count as evidence that reuse is sound. Local-only challenges checked initializer changes, added modules, documentation-only changes, and execution-environment mismatch.

The adjacent experiment's measured target execution times were about 4.65 seconds for the full arm and 2.40 seconds for the selective arm. Those tiny samples are sensitive to process startup and scheduling noise; only **8/60 candidate oracle executions** were actually avoided. The target of at least 50% wall-clock savings was not reliably met, and the baseline producer, GitHub artifact retrieval, and environment setup introduce additional costs. This is a successful *mechanism and falsification harness*, not a demonstrated economic advantage for quick tests.

For independent local replay:

```bash
PYTHONPATH=research/ci_evidence python -m unittest -v test_heldout
python research/ci_evidence/heldout.py \
    --protocol research/contract_poset/falsification_preregistration.json \
    --checkout-root /tmp/h11-reuse-holdout \
    --history-count 20 \
    --output /tmp/h11-reuse-heldout.json
```


## Boundaries

The statements are unsigned. Trust currently depends on GitHub Actions artifact transport and authenticated run metadata, not cryptographic signing of attestations. The whole tracked-package policy is deliberately much less selective than precise, mechanically verified dependency closure. Dynamic reads outside the tracked source boundary, external packages, mutable environment, and arbitrary runtime import effects have *not* been proven absent. The external held-out comparator exercises source identity only, not full in-toto consumption. Selective verification therefore remains a bounded research mode, not a general-purpose replacement for ordinary tests.
