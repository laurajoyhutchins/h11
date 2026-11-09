"""Bounded, content-addressed dependency snapshots for h11's native CI tests.

Deliberately conservative: track *every* Git-managed path in the h11 package,
including implicit initializers, plus explicit test/runner configuration.
This is a bounded coverage policy, not proof of all Python runtime dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

POLICY = "h11-native-pytest-whole-package-v1"
ROOT = "h11/"
EXTRA_PATHS = (
    ".github/workflows/native-contract-evidence.yml",
    "pyproject.toml", "setup.py", "tox.ini", "test-requirements.txt",
    "research/ci_evidence/run.py", "research/ci_evidence/manifest.py",
    "research/ci_evidence/test_exporter.py",
    "research/ci_evidence/test_roundtrip.py",
    "research/contract_poset/test_initializer_closure.py",
    "research/contract_poset/falsification.py",
)


def command(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def environment() -> dict[str, str]:
    import pytest
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_abi": getattr(sys, "abiflags", ""),
        "platform": sys.platform,
        "pytest_version": pytest.__version__,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
    }


def tree_files(repo: Path, commit: str) -> dict[str, dict[str, str]]:
    raw = command(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    files: dict[str, dict[str, str]] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, relative = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        path = relative.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            if path.startswith(ROOT) or path in EXTRA_PATHS:
                raise ValueError("unsupported dependency mode or object: " + path)
            continue
        files[path] = {"oid": oid, "mode": mode}
    return files


def snapshot(repo: Path, commit: str) -> dict[str, Any]:
    all_files = tree_files(repo, commit)
    package = sorted(k for k in all_files if k.startswith(ROOT))
    if not package or "h11/__init__.py" not in package:
        raise ValueError("entire tracked package unavailable")
    missing = set(EXTRA_PATHS) - set(all_files)
    if missing:
        raise ValueError("missing verification dependencies: " + ", ".join(sorted(missing)))
    selected = sorted(set(package) | set(EXTRA_PATHS))
    return {"policy": POLICY, "scope": "bounded native pytest observations",
            "coverage": "whole Git-tracked h11 package and explicit harness inputs",
            "files": {path: all_files[path] for path in selected}}


def generate(repo: Path, commit: str) -> dict[str, Any]:
    result = snapshot(repo, commit)
    result["schema_version"] = 1
    result["source_commit"] = commit
    result["source_tree"] = command(repo, "rev-parse", commit + "^{tree}").decode().strip()
    result["environment"] = environment()
    return result


def check_identity(repo: Path, commit: str, prior: dict[str, Any]) -> bool:
    """Check a stored manifest against actual immutable Git objects."""
    try:
        if (prior["schema_version"] != 1 or prior["source_commit"] != commit
            or prior["source_tree"] != command(repo, "rev-parse", commit + "^{tree}").decode().strip()
            or prior["policy"] != POLICY):
            return False
        return prior["files"] == snapshot(repo, commit)["files"]
    except (KeyError, ValueError, subprocess.CalledProcessError):
        return False


def compare(repo: Path, original: dict[str, Any], current_commit: str,
            current_env: dict[str, str]) -> dict[str, Any]:
    """Decide within the explicit closed-over-files policy; not global correctness."""
    base = original.get("source_commit")
    if not isinstance(base, str) or not check_identity(repo, base, original):
        return {"decision": "UNKNOWN", "reasons": ["BASELINE_MANIFEST_INVALID"]}
    if original.get("environment") != current_env:
        return {"decision": "UNKNOWN", "reasons": ["EXECUTION_ENVIRONMENT_MISMATCH"]}
    try:
        current = snapshot(repo, current_commit)
    except (ValueError, subprocess.CalledProcessError):
        return {"decision": "UNKNOWN", "reasons": ["CURRENT_DEPENDENCIES_UNREADABLE"]}
    past = original["files"]
    now = current["files"]
    changed = sorted(p for p in past.keys() | now.keys() if past.get(p) != now.get(p))
    if changed:
        return {"decision": "REVERIFY", "reasons": ["DEPENDENCY_BLOB_CHANGED"],
                "changed_paths": changed}
    return {"decision": "REUSE", "reasons": ["DEPENDENCIES_IDENTICAL_WITHIN_DECLARED_SCOPE"],
            "changed_paths": []}
