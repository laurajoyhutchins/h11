"""Fail-closed consumer of h11's GitHub-produced native test evidence.

A source-identity verdict is scoped to the finite pytest claims and declared
whole-package dependency policy. Nothing here proves arbitrary Python behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import xml.etree.ElementTree as ET

import manifest
import run as producer

REPOSITORY = "laurajoyhutchins/h11"
BRANCH = "research/native-contract-ci-evidence"
WORKFLOW = ".github/workflows/native-contract-evidence.yml"
CLAIMS = frozenset(producer.CLAIM_TEST_MARKERS)
SHA1 = re.compile(r"^[0-9a-f]{40}$")


def loaded(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate JSON field " + k)
            out[k] = v
        return out
    return json.loads(path.read_text(), object_pairs_hook=no_duplicates)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_item(items: list[dict], name: str) -> str:
    matches = [item.get("digest", {}).get("sha256") for item in items
               if item.get("name") == name]
    if len(matches) != 1 or not isinstance(matches[0], str) or not re.fullmatch(r"[a-f0-9]{64}", matches[0]):
        raise ValueError("missing or duplicate evidence digest " + name)
    return matches[0]


def git_file(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        stderr=subprocess.DEVNULL,
    )


def checked_run(meta: dict, predicate: dict, base: str) -> None:
    if (meta.get("repository", {}).get("full_name") != REPOSITORY
        or meta.get("head_sha") != base or meta.get("conclusion") != "success"
        or meta.get("status") != "completed"
        or meta.get("head_branch") != BRANCH
        or meta.get("event") not in ("push", "workflow_dispatch")
        or meta.get("path") != WORKFLOW
        or not isinstance(meta.get("id"), int)):
        raise ValueError("untrusted or inconsistent workflow run identity")
    expected = f"https://github.com/{REPOSITORY}/actions/runs/{meta['id']}"
    if predicate.get("url") != expected:
        raise ValueError("test statement does not bind trusted workflow run")


def verified_bundle(repo: Path, prior: Path, trusted_run: dict) -> dict[str, Any]:
    statement = loaded(prior / "test-result.intoto.json")
    recorded = loaded(prior / "claim-results.json")
    deps = loaded(prior / "dependencies.json")
    junit = prior / "results.xml"
    if (statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != "https://in-toto.io/attestation/test-result/v0.1"
        or not isinstance(statement.get("predicate"), dict)
        or not isinstance(statement.get("subject"), list)
        or not isinstance(deps, dict)
        or not isinstance(recorded, dict)):
        raise ValueError("unrecognized evidence or manifest schema")
    predicate = statement["predicate"]
    base = deps.get("source_commit")
    if not isinstance(base, str) or not SHA1.fullmatch(base):
        raise ValueError("invalid originating commit")
    checked_run(trusted_run, predicate, base)
    if not manifest.check_identity(repo, base, deps):
        raise ValueError("manifest differs from source tree")
    subjects = statement["subject"]
    subject_ids = [x for x in subjects if x.get("name") == f"git+https://github.com/{REPOSITORY}"]
    trees = [x for x in subjects if x.get("name") == "git-tree"]
    if (len(subject_ids) != 1 or subject_ids[0].get("digest") != {"gitCommit": base}
        or len(trees) != 1 or trees[0].get("digest") != {"gitTree": deps["source_tree"]}):
        raise ValueError("statement subjects disagree with Git manifest")
    for name in producer.SOURCE_FILES:
        actual = sha256(git_file(repo, base, name))
        if digest_item(subjects, name) != actual:
            raise ValueError("source digest mismatch " + name)
    configuration = predicate.get("configuration")
    if not isinstance(configuration, list):
        raise ValueError("missing test configuration digests")
    for name in producer.CONFIG_FILES:
        if digest_item(configuration, name) != sha256(git_file(repo, base, name)):
            raise ValueError("configuration digest mismatch " + name)
    for name in ("dependencies.json", "results.xml"):
        if digest_item(configuration, name) != sha256((prior / name).read_bytes()):
            raise ValueError("evidence artifact digest mismatch " + name)
    passed, failed, skipped, groups = producer.parse_junit(junit)
    if (predicate.get("result") != "PASSED" or predicate.get("passedTests") != passed
        or predicate.get("failedTests") != failed or predicate.get("warnedTests") != skipped
        or failed or skipped):
        raise ValueError("verification was not fully passing")
    if (recorded.get("source_commit") != base or
        recorded.get("source_tree") != deps["source_tree"] or
        recorded.get("status") != "PASSED"):
        raise ValueError("claim ledger does not match Git source")
    observed = recorded.get("claims", [])
    if (not isinstance(observed, list) or len(observed) != len(CLAIMS)
        or {x.get("id") for x in observed} != CLAIMS):
        raise ValueError("missing, duplicate or unsupported claims")
    for item in observed:
        if (item.get("status") != "VERIFIED_WITHIN_TEST_SCOPE" or
            item.get("required_tests") != groups[item["id"]]):
            raise ValueError("claim not supported by full JUnit evidence")
    return deps


def consume(repo: Path, prior: Path, trusted_run: dict,
            current_commit: str, environment: dict[str, str]) -> dict[str, Any]:
    """Never convert missing, inconsistent or unsigned *untrusted* evidence to REUSE."""
    if not SHA1.fullmatch(current_commit):
        return {"decision": "UNKNOWN", "reasons": ["INVALID_TARGET_COMMIT"]}
    try:
        deps = verified_bundle(repo, prior, trusted_run)
        relevant = ["h11/", *manifest.EXTRA_PATHS]
        dirty = subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all",
             "--", *relevant],
            stderr=subprocess.DEVNULL,
        ).strip()
        if dirty:
            return {"decision": "UNKNOWN", "reasons": ["DIRTY_OR_UNTRACKED_EXECUTION_INPUTS"]}
        result = manifest.compare(repo, deps, current_commit, environment)
    except (ValueError, KeyError, OSError, TypeError, AttributeError,
            ET.ParseError, subprocess.CalledProcessError) as exc:
        return {"decision": "UNKNOWN", "reasons": ["EVIDENCE_UNVERIFIED"],
                "detail": str(exc)}
    return {**result, "baseline_commit": deps["source_commit"],
            "target_commit": current_commit,
            "claims": sorted(CLAIMS),
            "scope": "bounded h11 native pytest observations only"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", type=Path, default=producer.ROOT)
    p.add_argument("--prior-artifacts", type=Path, required=True)
    p.add_argument("--trusted-run", type=Path, required=True,
                   help="GitHub Actions run metadata fetched using authenticated GitHub API")
    p.add_argument("--target-commit", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        meta = loaded(args.trusted_run)
        result = consume(args.repository.resolve(), args.prior_artifacts.resolve(),
                         meta, args.target_commit, manifest.environment())
    except (ValueError, OSError, TypeError, AttributeError, ET.ParseError) as exc:
        result = {"decision": "UNKNOWN", "reasons": ["INVALID_INPUT"], "detail": str(exc)}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    # REVERIFY and UNKNOWN are normal decisions, not errors to be hidden.
    # Callers MUST run tests for either result.
    return


if __name__ == "__main__":
    main()
