"""Carry h11's prior finite claims using a universal Lean writer-trace theorem.

Separates (1) a Lean-kernel theorem about a mathematical encoding model,
(2) exact syntactic source correspondence and trusted Python semantics,
(3) previously verified *finite* downstream claims. The new in-toto Test
Result records checks actually executed, not simulated downstream tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from attest import verify as verify_finite
from check import strict_json
from formal_bridge import proof_result, verify_bridge, PROOF
from prior import bind

STATEMENT = "https://in-toto.io/Statement/v1"
RESULT = "https://in-toto.io/attestation/test-result/v0.1"
REPO = "laurajoyhutchins/h11"


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs(root: Path, baseline: Path, candidate: Path, work: Path,
                prior_artifacts: Path, metadata: Path) -> dict:
    # Re-execute old certificate checks, not merely compare precomputed JSON.
    verify_finite(work, baseline, candidate)
    finite = strict_json(work / "preservation.json")
    old = bind(baseline, prior_artifacts, strict_json(metadata), finite)
    if old != strict_json(work / "prior-reference.json"):
        raise ValueError("prior evidence lineage changed after finite certificate")
    proved = proof_result(root)
    bridged = verify_bridge(root, baseline, candidate)
    if finite["source"] != bridged["source_restriction"]:
        raise ValueError("source bridge and finite certificate disagree")
    if (proved["proof_git_commit"] !=
        bridged["source_restriction"]["baseline_commit"]):
        raise ValueError("proof did not belong to original Git commit")
    return {"finite": finite, "prior": old, "proof": proved, "bridge": bridged}


def certificate(data: dict, work: Path) -> dict:
    finite = data["finite"]
    prior = data["prior"]
    proved = data["proof"]
    bridged = data["bridge"]
    original = finite["source"]["baseline_commit"]
    candidate = finite["source"]["candidate_commit"]
    return {
        "schema_version": 1,
        "kind": "universal-writer-model-preservation",
        "baseline_commit": original,
        "candidate_local_commit": candidate,
        "candidate_tree": finite["source"]["candidate_tree"],
        "formal_proof": proved,
        "exact_python_ast_bridge": bridged,
        "evidence": {
            "finite_certificate_sha256": hash_file(work / "preservation.json"),
            "finite_in_toto_sha256": hash_file(work / "preservation.intoto.json"),
            "prior_reference_sha256": hash_file(work / "prior-reference.json"),
        },
        "claims": [
            {
                "id": "chunked.writer.ordered-callback-traces",
                "status": "FORMALLY_PROVED_IN_LEAN_MODEL_CONDITIONAL_ON_PYTHON_BRIDGE",
                "quantification": (
                    "every finite list of byte payloads, including zero-length "
                    "payloads, with an unchanged EOM callback sequence"
                ),
                "theorem": "HexPreservation.messageTrace_eq_for_all_inputs",
                "fresh_candidate_reader_executions": 0,
            },
            {
                "id": "http1.chunked.reader",
                "status": "PREVIOUS_FINITE_EVIDENCE_RETAINED",
                "original_run": prior["verified_run_id"],
                "rule": "read-only source dependencies unchanged inside prior manifest",
                "fresh_candidate_reader_executions": 0,
            },
            {
                "id": "http1.chunked.composition",
                "status": "PRIOR_FINITE_CASES_CARRIED_BY_UNIVERSAL_WRITER_CONGRUENCE",
                "original_run": prior["verified_run_id"],
                "original_cases_preserved": 24,
                "rule": (
                    "unchanged reader + equal writer callback traces "
                    "for all byte payload sequences implies preservation of "
                    "the 24 previously observed composition cases"
                ),
                "fresh_candidate_reader_executions": 0,
            },
        ],
        "trusted_assumptions": [
            "Standard nonnegative CPython integer bitwise and %x formatting semantics",
            "bytes input and nonthrowing ordered callback",
            "matching Python execution environment and unchanged reader dependencies",
            "prior unsigned Test Result authenticated via GitHub Actions run metadata",
        ],
        "limits": (
            "Universal theorem concerns writer callback traces only; reader "
            "correctness remains finite/test-bound. Syntactic Python bridge "
            "and host runtime semantics are trusted, not proved by Lean. "
            "No universal HTTP correctness or unbounded resource guarantee."
        ),
    }


def statement(cert: dict, work: Path) -> dict:
    checks = [
        "Lean4.35.0/bitwiseDigits_eq_toDigits",
        "Lean4.35.0/chunkTrace_eq_for_all_payloads",
        "Lean4.35.0/messageTrace_eq_for_all_inputs",
        "baseline-Python-AST-matches-formal-model",
        "candidate-Python-AST-matches-formal-model",
        "source-Git-diff-is-restricted",
        "prior-in-toto-and-JUnit-authenticated-and-verified",
        "prior-case-lineage-matches",
        "finite-certificate-in-toto-reverified",
    ]
    configuration = [
        {"name": "source-proof",
         "digest": {"sha256": cert["formal_proof"]["proof_sha256"]}},
        *[
            {"name": path, "digest": {"sha256": hash_file(work / path)}}
            for path in ("preservation.json", "preservation.intoto.json",
                         "prior-reference.json", "universal-preservation.json")
        ],
    ]
    return {
        "_type": STATEMENT,
        "subject": [
            {
                "name": f"git+https://github.com/{REPO}#local-writer-refactor",
                "digest": {"gitCommit": cert["candidate_local_commit"]},
            },
            {
                "name": "candidate-git-tree",
                "digest": {"gitTree": cert["candidate_tree"]},
            },
        ],
        "predicateType": RESULT,
        "predicate": {
            "result": "PASSED",
            "configuration": configuration,
            "passedTests": checks,
            "warnedTests": [],
            "failedTests": [],
        },
    }


def assemble(root: Path, baseline: Path, candidate: Path, work: Path,
             prior_artifacts: Path, metadata: Path) -> tuple[dict, dict]:
    data = load_inputs(root, baseline, candidate, work, prior_artifacts, metadata)
    cert = certificate(data, work)
    # The statement binds the just-serialized certificate bytes.
    return cert, statement(cert, work)


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("emit", "verify"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--prior-artifacts", type=Path, required=True)
    p.add_argument("--trusted-run", type=Path, required=True)
    args = p.parse_args()
    cert_path = args.work / "universal-preservation.json"
    statement_path = args.work / "universal-preservation.intoto.json"
    data = load_inputs(args.root, args.baseline, args.candidate, args.work,
                       args.prior_artifacts, args.trusted_run)
    cert = certificate(data, args.work)
    if args.action == "emit":
        write(cert_path, cert)
        write(statement_path, statement(cert, args.work))
        print("UNIVERSAL_MODEL_PROVED", len(cert["claims"]),
              "claims tracked; downstream claims conditional and finite")
    else:
        if strict_json(cert_path) != cert:
            raise ValueError("universal certificate does not match checked inputs")
        if strict_json(statement_path) != statement(cert, args.work):
            raise ValueError("universal in-toto statement does not match checked inputs")
        print("UNIVERSAL_EVIDENCE_VERIFIED", cert["candidate_local_commit"])


if __name__ == "__main__":
    main()
