"""Fresh h11 pytest/JUnit evidence projected into unsigned in-toto and SARIF.

No historical observation ledger is imported. An attestation is emitted only
for the exact checked-out source, after the required native tests are run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import manifest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ".github/workflows/native-contract-evidence.yml"
TEST_FILES = (
    "h11/tests/test_io.py::test_ChunkedReader",
    "h11/tests/test_io.py::test_ChunkedWriter",
    "research/ci_evidence/test_roundtrip.py",
    "research/contract_poset/test_initializer_closure.py",
)
CONFIG_FILES = (
    WORKFLOW,
    "research/ci_evidence/run.py",
    "research/ci_evidence/manifest.py",
    "research/ci_evidence/test_roundtrip.py",
    "research/ci_evidence/test_exporter.py",
    "research/contract_poset/test_initializer_closure.py",
)
SOURCE_FILES = (
    "h11/__init__.py", "h11/_abnf.py", "h11/_events.py",
    "h11/_headers.py", "h11/_readers.py", "h11/_receivebuffer.py",
    "h11/_state.py", "h11/_util.py", "h11/_writers.py",
)
CLAIM_TEST_MARKERS = {
    "http1.chunked.reader": ("test_ChunkedReader", "test_corrupt_chunk_footer_rejected"),
    "http1.chunked.writer": ("test_ChunkedWriter",),
    "http1.chunked.composition": ("test_codec_composition_preserves_payload_trailers_and_suffix",),
    "research.import-closure.initializer": ("test_root_initializer_is_an_implicit_import_dependency",),
}
RESULT_MARKER = "include_package_initializers: bool = False"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()


def identity(repo: Path, expected_commit: str | None) -> tuple[str, str]:
    commit = git(repo, "rev-parse", "HEAD")
    if expected_commit and commit != expected_commit:
        raise ValueError(f"checkout commit {commit} != GitHub event commit {expected_commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("expected 40-character Git commit SHA-1")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    required = (*SOURCE_FILES, *CONFIG_FILES, "h11/tests/test_io.py",
                "research/contract_poset/falsification.py")
    if git(repo, "status", "--porcelain", "--", *required):
        raise ValueError("tracked source or verifier differs from commit")
    for path in required:
        if not (repo / path).is_file():
            raise ValueError(f"missing source or verifier: {path}")
        git(repo, "ls-files", "--error-unmatch", "--", path)
    return commit, tree


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resource(repo: Path, path: str) -> dict:
    return {"name": path, "digest": {"sha256": sha256(repo / path)}}


def parse_junit(path: Path) -> tuple[list[str], list[str], list[str], dict[str, list[str]]]:
    root = ET.parse(path).getroot()
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit has no suites")
    cases = [case for suite in suites for case in suite.findall("testcase")]
    if not cases:
        raise ValueError("JUnit contains no test cases")
    names = []
    for case in cases:
        cls, name = case.get("classname"), case.get("name")
        if not cls or not name:
            raise ValueError("testcase without a full identifier")
        names.append(f"{cls}::{name}")
    if len(names) != len(set(names)):
        raise ValueError("duplicate JUnit testcase identifiers")
    passed, failed, warned = [], [], []
    for name, case in zip(names, cases):
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(name)
        elif case.find("skipped") is not None:
            warned.append(name)
        else:
            passed.append(name)
    groups: dict[str, list[str]] = {}
    for claim, markers in CLAIM_TEST_MARKERS.items():
        found: list[str] = []
        for marker in markers:
            matching = [name for name in names if marker in name]
            if not matching:
                raise ValueError(f"required test group missing: {claim}/{marker}")
            found.extend(matching)
        groups[claim] = sorted(set(found))
    return sorted(passed), sorted(failed), sorted(warned), groups


def make_statement(repo: Path, commit: str, tree: str, junit: Path,
                   passed: list[str], failed: list[str], warned: list[str],
                   dependencies: Path | None = None) -> dict:
    if not passed:
        raise ValueError("no passing tests")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo_name = os.environ.get("GITHUB_REPOSITORY", "laurajoyhutchins/h11")
    predicate = {
        "result": "FAILED" if failed else ("WARNED" if warned else "PASSED"),
        "configuration": [resource(repo, x) for x in CONFIG_FILES]
                         + [{"name": "results.xml", "digest": {"sha256": sha256(junit)}}],
        "passedTests": passed,
        "warnedTests": warned,
        "failedTests": failed,
    }
    if dependencies is not None:
        predicate["configuration"].append({
            "name": "dependencies.json",
            "digest": {"sha256": sha256(dependencies)},
        })
    if os.environ.get("GITHUB_RUN_ID"):
        predicate["url"] = f"{server}/{repo_name}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": f"git+{server}/{repo_name}", "digest": {"gitCommit": commit}},
            {"name": "git-tree", "digest": {"gitTree": tree}},
            *[resource(repo, x) for x in SOURCE_FILES],
        ],
        "predicateType": "https://in-toto.io/attestation/test-result/v0.1",
        "predicate": predicate,
    }


def make_sarif(repo: Path, passed: list[str]) -> dict:
    source = "research/contract_poset/falsification.py"
    lines = (repo / source).read_text().splitlines()
    positions = [i for i, text in enumerate(lines, 1)
                 if RESULT_MARKER in text and "-> list[str]" in text]
    if len(positions) != 1:
        raise ValueError("known control limitation no longer matches source")
    if not any("test_root_initializer_is_an_implicit_import_dependency" in name
               for name in passed):
        raise ValueError("no fresh initializer regression supporting finding")
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "h11-contract-evidence",
                "informationUri": "https://github.com/in-toto/attestation",
                "rules": [{
                    "id": "EVIDENCE001",
                    "name": "LegacyImportOnlyPredictorOmitsInitializer",
                    "shortDescription": {"text": "The frozen import-only control omits implicit package initializers"},
                    "fullDescription": {"text": "Import-only source identity is unsound for general oracle reuse. The corrected predictor includes initializer dependencies; the frozen control remains for research."},
                    "defaultConfiguration": {"level": "warning"},
                }],
            }},
            "results": [{
                "ruleId": "EVIDENCE001",
                "level": "warning",
                "message": {"text": "Research-only import-only control omits Python package __init__.py execution dependencies and must not authorize production evidence reuse."},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": source},
                    "region": {"startLine": positions[0]},
                }}],
                "properties": {"scope": "research-only-control", "status": "KNOWN_LIMITATION"},
            }],
        }],
    }


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def run(repo: Path, output_dir: Path, expected: str | None) -> int:
    repo = repo.resolve()
    output_dir = output_dir.resolve()
    if output_dir == repo or repo in output_dir.parents:
        raise ValueError("outputs must be written outside source checkout")
    commit, tree = identity(repo, expected)
    output_dir.mkdir(parents=True, exist_ok=True)
    junit = output_dir / "results.xml"
    junit.unlink(missing_ok=True)
    command = [sys.executable, "-m", "pytest", "-q", *TEST_FILES,
               f"--junitxml={junit}"]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(repo / "research/contract_poset"), env.get("PYTHONPATH", ""),
    )))
    print("VERIFYING", " ".join(command), flush=True)
    exit_status = subprocess.run(command, cwd=repo, env=env, check=False).returncode
    if not junit.is_file():
        raise ValueError("fresh JUnit XML was not produced")
    passed, failed, warned, groups = parse_junit(junit)
    if exit_status and not failed:
        raise ValueError("pytest failed without a reported testcase failure")
    if not exit_status and failed:
        raise ValueError("pytest returned success despite JUnit failures")
    if (commit, tree) != identity(repo, expected):
        raise ValueError("source changed during verification")
    dependency_path = output_dir / "dependencies.json"
    write(dependency_path, manifest.generate(repo, commit))
    statement = make_statement(repo, commit, tree, junit, passed, failed, warned,
                               dependencies=dependency_path)
    # Do not pretend that the known limitation is a newly discovered bug.
    sarif = make_sarif(repo, passed) if not failed and not warned else {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "h11-contract-evidence"}}, "results": []}],
    }
    write(output_dir / "test-result.intoto.json", statement)
    write(output_dir / "limitations.sarif", sarif)
    write(output_dir / "claim-results.json", {
        "schema_version": 1, "source_commit": commit, "source_tree": tree,
        "status": statement["predicate"]["result"],
        "claims": [
            {"id": claim, "required_tests": tests,
             "status": "VERIFIED_WITHIN_TEST_SCOPE"
                       if all(t in passed for t in tests) else "NOT_VERIFIED"}
            for claim, tests in sorted(groups.items())
        ],
        "limits": "Finite checked-out source tests, not HTTP correctness proof; unsigned; no evidence-reuse decisions.",
    })
    print("EVIDENCE", statement["predicate"]["result"], "tests", len(passed),
          "failed", len(failed), "skipped", len(warned), "commit", commit,
          flush=True)
    return 0 if not exit_status and not failed and not warned else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-commit", default=os.environ.get("GITHUB_SHA"))
    a = p.parse_args()
    raise SystemExit(run(a.repository, a.output_dir, a.expected_commit))


if __name__ == "__main__":
    main()
