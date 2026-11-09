"""Bind a previous authenticated h11 Test Result to a new writer refinement.

This reuses the already-tested Git/JUnit/in-toto consumer instead of inventing
another attestation validator. The legacy fixtures are loaded from the exact
source tested by the previous run. No candidate reader execution occurs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from domain import corpus

READER = "http1.chunked.reader"
WRITER = "http1.chunked.writer"
COMPOSITION = "http1.chunked.composition"
LEGACY_IDS = ("legacy-empty", "legacy-single", "legacy-trailers", "legacy-binary")


def load_legacy_cases(source: Path) -> tuple:
    spec = importlib.util.spec_from_file_location(
        "_previous_h11_roundtrip",
        source / "research/ci_evidence/test_roundtrip.py",
    )
    if spec is None or spec.loader is None:
        raise ValueError("old fixed-input test module not available")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.FIXTURES)


def bind(source: Path, prior: Path, metadata: dict[str, Any],
         certificate: dict) -> dict[str, Any]:
    ci_path = source / "research/ci_evidence"
    sys.path.insert(0, str(ci_path))
    try:
        from consume import verified_bundle
        import manifest
        digest_source = manifest.sha256
    finally:
        sys.path.remove(str(ci_path))
    dependencies = verified_bundle(source, prior, metadata)
    commit = certificate["source"]["baseline_commit"]
    decision = manifest.compare(source, dependencies, commit, manifest.environment())
    if decision["decision"] != "REUSE":
        raise ValueError("previous source evidence does not apply: " + repr(decision))
    rows = {x["case"]: x for x in certificate["cases"]}
    if len(rows) != len(certificate["cases"]) or not set(LEGACY_IDS) <= set(rows):
        raise ValueError("legacy inputs missing or duplicate certificate cases")
    cases = {x["id"]: x for x in corpus()}
    fixtures = load_legacy_cases(source)
    if len(fixtures) != len(LEGACY_IDS):
        raise ValueError("older composition fixture count changed")
    for case_id, (payloads, trailers) in zip(LEGACY_IDS, fixtures):
        expected = {
            "payloads": [item.hex() for item in payloads],
            "trailers": [[k.hex(), v.hex()] for k, v in trailers],
        }
        if {key: cases[case_id][key] for key in expected} != expected:
            raise ValueError("new corpus differs from previously verified input: " + case_id)
        if not rows[case_id]["candidate_writer_equal"]:
            raise ValueError("candidate writer failed old source input: " + case_id)

    from hashlib import sha256
    def digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()
    claims = json.loads((prior / "claim-results.json").read_text())["claims"]
    if {x["id"] for x in claims} < {READER, WRITER, COMPOSITION}:
        raise ValueError("prior claims not present")
    run_id = metadata["id"]
    return {
        "schema_version": 1,
        "kind": "linked-prior-evidence",
        "verified_run_id": run_id,
        "verified_run_url": f"https://github.com/laurajoyhutchins/h11/actions/runs/{run_id}",
        "original_verified_commit": dependencies["source_commit"],
        "refinement_baseline_commit": commit,
        "candidate_commit": certificate["source"]["candidate_commit"],
        "decision": "PRESERVE_WITHIN_DECLARED_TEST_SCOPE",
        "original_evidence": {
            filename: {"sha256": digest(prior / filename)}
            for filename in (
                "test-result.intoto.json", "results.xml",
                "claim-results.json", "dependencies.json",
            )
        },
        "claim_lineage": [
            {
                "previous_claim": READER,
                "new_claim": "chunked.reader.bounded",
                "rule": "prior source dependency manifest is unchanged",
                "scope": "existing 37-test native suite; environment matched",
            },
            {
                "previous_claim": WRITER,
                "new_claim": "chunked.writer.bounded",
                "rule": "new writer output trace exactly equals old writer for each old fixture",
                "scope": "only four previously used Data/EndOfMessage event fixtures",
            },
            {
                "previous_claim": COMPOSITION,
                "new_claim": "chunked.composition.bounded",
                "rule": "old reader and writer composition cases are preserved by identical byte traces",
                "scope": "four previous event fixtures times six original segment sizes",
            },
        ],
        "exact_previous_fixture_cases": list(LEGACY_IDS),
        "limits": [
            "Prior in-toto statement unsigned; run identity supplied by authenticated GitHub API",
            "Original composition test vectors preserved, not all possible HTTP behavior",
            "Local candidate is reconstructed from Git patch and baseline, not a pushed commit",
            "Previous source manifest is a declared dependency boundary, not semantic completeness",
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--trusted-run", type=Path, required=True)
    p.add_argument("--certificate", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    data = bind(
        a.source.resolve(), a.prior.resolve(),
        json.loads(a.trusted_run.read_text()),
        json.loads(a.certificate.read_text()),
    )
    a.output.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    print("PRIOR_EVIDENCE_BOUND", data["verified_run_id"],
          "3 prior claims; 4 old input fixtures; 24 old composition cases")


if __name__ == "__main__":
    main()
