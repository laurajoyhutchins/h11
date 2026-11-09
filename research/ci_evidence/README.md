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
