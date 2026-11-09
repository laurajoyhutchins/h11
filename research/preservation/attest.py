"""Emit and verify an unsigned in-toto Test Result for preservation obligations.

A Test Result lists checks actually executed; downstream claims carried by
composition stay in preservation.json and are NOT presented as rerun tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from check import make_certificate, strict_json

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://in-toto.io/attestation/test-result/v0.1"
REPO = "laurajoyhutchins/h11"
ARTIFACT_FILES = (
    "preservation.json",
    "baseline-observations.json",
    "candidate-observations.json",
    "candidate.patch",
)
VERIFIER_FILES = (
    "research/preservation/domain.py",
    "research/preservation/probe.py",
    "research/preservation/check.py",
    "research/preservation/attest.py",
    "research/preservation/run.py",
    "research/preservation/prior.py",
    "research/preservation/test_check.py",
    "research/preservation/test_attest.py",
    ".github/workflows/contract-preservation.yml",
)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def resource(name: str, raw: bytes) -> dict:
    return {"name": name, "digest": {"sha256": sha256(raw)}}


def patch_bytes(baseline: Path, candidate: Path) -> bytes:
    original = git(baseline, "rev-parse", "HEAD").decode().strip()
    modified = git(candidate, "rev-parse", "HEAD").decode().strip()
    return git(candidate, "diff", "--binary", original, modified)


def recheck(work: Path, baseline: Path, candidate: Path) -> dict:
    saved = strict_json(work / "preservation.json")
    recomputed = make_certificate(
        baseline, candidate,
        strict_json(work / "baseline-observations.json"),
        strict_json(work / "candidate-observations.json"),
    )
    if saved != recomputed:
        raise ValueError("certificate differs from independently rechecked premises")
    patch = work / "candidate.patch"
    if not patch.is_file() or patch.read_bytes() != patch_bytes(baseline, candidate):
        raise ValueError("published Git patch differs from actual candidate")
    return saved


def statement_for(work: Path, baseline: Path, candidate: Path,
                  certificate: dict, url: str | None = None) -> dict:
    source = certificate["source"]
    original = git(baseline, "rev-parse", "HEAD").decode().strip()
    modified = git(candidate, "rev-parse", "HEAD").decode().strip()
    if (source["baseline_commit"] != original or
        source["candidate_commit"] != modified):
        raise ValueError("Git commits do not match certificate")
    configuration = [
        {"name": f"baseline-git+https://github.com/{REPO}",
         "digest": {"gitCommit": original}},
        *[resource(name, (work / name).read_bytes()) for name in ARTIFACT_FILES],
        *[resource(name, git(baseline, "show", f"{original}:{name}"))
          for name in VERIFIER_FILES],
    ]
    prior_link = work / "prior-reference.json"
    if prior_link.is_file():
        linked = strict_json(prior_link)
        if (linked.get("schema_version") != 1 or
            linked.get("kind") != "linked-prior-evidence" or
            linked.get("decision") != "PRESERVE_WITHIN_DECLARED_TEST_SCOPE" or
            linked.get("refinement_baseline_commit") != original or
            linked.get("candidate_commit") != modified or
            len(linked.get("claim_lineage", [])) != 3):
            raise ValueError("prior evidence reference is not consistent with candidate")
        configuration.append(resource("prior-reference.json", prior_link.read_bytes()))
    executed = [
        "source-diff-restricted-to-ChunkedWriter.send_data",
        "reader-and-package-initializers-source-unchanged",
        "candidate-patch-matches-Git-diff",
    ]
    for row in certificate["cases"]:
        executed.extend((
            f"{row['case']}/writer-trace-identical",
            f"{row['case']}/baseline-reader-observation-valid",
        ))
    if len(executed) != 3 + 2 * certificate["scope"]["case_count"]:
        raise ValueError("invalid executed-obligation count")
    predicate: dict[str, Any] = {
        "result": "PASSED",
        "configuration": configuration,
        "passedTests": executed,
        "warnedTests": [],
        "failedTests": [],
    }
    if url:
        predicate["url"] = url
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {"name": f"git+https://github.com/{REPO}#local-candidate",
             "digest": {"gitCommit": modified}},
            {"name": "candidate-git-tree",
             "digest": {"gitTree": source["candidate_tree"]}},
            resource("preservation.json", (work / "preservation.json").read_bytes()),
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }


def expected_url() -> str | None:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    if not run_id.isdecimal() or os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("untrusted GitHub run identity")
    return f"https://github.com/{REPO}/actions/runs/{run_id}"


def emit(work: Path, baseline: Path, candidate: Path) -> dict:
    checked = recheck(work, baseline, candidate)
    statement = statement_for(work, baseline, candidate, checked, expected_url())
    (work / "preservation.intoto.json").write_text(
        json.dumps(statement, sort_keys=True, indent=2) + "\n")
    return statement


def verify(work: Path, baseline: Path, candidate: Path) -> None:
    checked = recheck(work, baseline, candidate)
    actual = strict_json(work / "preservation.intoto.json")
    expected = statement_for(work, baseline, candidate, checked, expected_url())
    if actual != expected:
        raise ValueError("in-toto statement does not match checked evidence")
    if (actual["_type"] != STATEMENT_TYPE or
        actual["predicateType"] != PREDICATE_TYPE or
        actual["predicate"]["result"] != "PASSED" or
        actual["predicate"]["failedTests"] or
        actual["predicate"]["warnedTests"]):
        raise ValueError("invalid Test Result status or structure")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("emit", "verify"))
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    args = p.parse_args()
    if args.action == "emit":
        statement = emit(args.work, args.baseline, args.candidate)
        print("EMITTED", len(statement["predicate"]["passedTests"]),
              "executed checks; derived claims recorded in separate certificate")
    else:
        verify(args.work, args.baseline, args.candidate)
        print("VERIFIED in-toto statement, Git source and bounded preservation certificate")


if __name__ == "__main__":
    main()
