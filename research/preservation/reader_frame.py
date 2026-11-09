"""Fail-closed source frame for h11's *sealed reader-only* execution context.

This does NOT purport to prove unrestricted Python observational
equivalence. It proves that, for a deliberately fixed reader-only import
environment, the transitive package source closure excludes the writer,
and those module blobs remain identical across the actual Git transformation.

The original reader observations are subsequently reproduced ON THE BASELINE
under this sealed context. The candidate reader is never executed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

READER_ROOT = "_readers"
EXPECTED_CLOSURE = frozenset({
    "_readers", "_receivebuffer", "_events", "_headers",
    "_abnf", "_util", "_state",
})
FORBIDDEN_MODULES = frozenset({"_writers", "_connection"})
FORBIDDEN_BUILTINS = frozenset({
    "__import__", "eval", "exec", "open", "getattr",
    "setattr", "delattr", "vars", "dir", "locals",
})
REFLECTIVE_NAMES = frozenset({
    "ChunkedWriter", "WRITERS", "inspect", "importlib",
})
REFLECTIVE_ATTRIBUTES = frozenset({
    "__code__", "co_code", "__globals__", "__closure__",
    "__dict__", "modules", "meta_path",
})


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True).strip()


def hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def imports(path: str, content: bytes) -> set[str]:
    tree = ast.parse(content.decode("utf-8"), filename=path)
    imports_local: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level != 1 or not node.module or not node.module.startswith("_"):
                    raise ValueError("unexpected relative import: " + path)
                imports_local.add(node.module)
            elif node.module and node.module.startswith("h11."):
                imports_local.add(node.module.split(".", 1)[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("h11."):
                    imports_local.add(alias.name.split(".", 1)[1])
                if alias.name.split(".", 1)[0] in ("inspect", "importlib"):
                    raise ValueError("reflective import in sealed reader closure: " + path)
        elif isinstance(node, ast.Name) and node.id in REFLECTIVE_NAMES:
            raise ValueError("reader closure references writer or reflection: " + path)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                raise ValueError("dynamic operation in sealed reader closure: " + path)
            # _abnf uses globals() only for formatting its own constant
            # grammar strings. No other source module may use it.
            if node.func.id == "globals" and path != "h11/_abnf.py":
                raise ValueError("unexpected reader closure globals() use: " + path)
        elif isinstance(node, ast.Attribute) and node.attr in REFLECTIVE_ATTRIBUTES:
            raise ValueError("reflection in sealed reader closure: " + path)
    if imports_local & FORBIDDEN_MODULES:
        raise ValueError("sealed reader imports the modified writer: " + path)
    if any(name not in EXPECTED_CLOSURE for name in imports_local):
        raise ValueError("reader imports outside declared closure: " + path)
    return imports_local


def source_frame(baseline: Path, candidate: Path) -> dict[str, Any]:
    from check import source_obligations
    original = run_git(baseline, "rev-parse", "HEAD")
    changed = run_git(candidate, "rev-parse", "HEAD")
    bounds = source_obligations(candidate, original, changed)
    if (run_git(baseline, "status", "--porcelain") or
        run_git(candidate, "status", "--porcelain")):
        raise ValueError("source frame requires clean checkouts")
    stack = [READER_ROOT]
    closure: set[str] = set()
    deps: dict[str, dict[str, Any]] = {}
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        if name not in EXPECTED_CLOSURE:
            raise ValueError("unknown reader dependency " + name)
        relative = f"h11/{name}.py"
        old = subprocess.check_output(["git", "-C", str(baseline),
                                       "show", f"{original}:{relative}"])
        new = subprocess.check_output(["git", "-C", str(candidate),
                                       "show", f"{changed}:{relative}"])
        if old != new:
            raise ValueError("changed reader dependency: " + relative)
        dependencies = imports(relative, old)
        deps[relative] = {
            "sha256": hash_bytes(old),
            "direct_h11_imports": sorted(dependencies),
        }
        closure.add(name)
        stack.extend(dependencies - closure)
    if closure != EXPECTED_CLOSURE:
        raise ValueError("reader closure shape drifted: " + repr(closure))
    # Note that h11/__init__.py is not part of this CLOSED subprogram.
    # We replace the package entry with an inert namespace in a fresh
    # process. Normal h11 imports would load _connection -> _writers.
    return {
        "schema_version": 1,
        "kind": "sealed-reader-source-frame",
        "baseline_commit": original,
        "candidate_commit": changed,
        "candidate_git_tree": bounds["candidate_tree"],
        "declared_modules": sorted(closure),
        "module_digests": deps,
        "writer_absent_from_checked_direct_import_closure": True,
        "package_initializer_bypassed_by_sealed_runner": True,
        "reader_source_unchanged": True,
        "context": "fresh isolated Python process, inert h11 package stub, no caller mutation",
        "limits": [
            "Static import and unsafe-operation check for the seven pinned reader modules",
            "No claim for normal package initialization through h11.__init__",
            "No claim for monkeypatching, custom import hooks or adversarial Python runtime",
            "No new candidate reader executions",
            "Python standard library and interpreter remain trusted dependencies",
        ],
    }


def verify_observations(frame: dict, observed: dict, prior: dict) -> dict:
    if frame["kind"] != "sealed-reader-source-frame":
        raise ValueError("invalid frame identity")
    if (observed.get("schema_version") != 1
        or observed.get("kind") != "sealed-reader-baseline-observations"
        or observed.get("candidate_reader_executions") != 0
        or observed.get("package_initializer_executed") is not False
        or observed.get("writer_module_imported") is not False
        or observed.get("loaded_reader_modules") != frame["declared_modules"]
        or observed.get("observations_count") != 24
        or len(observed.get("cases", [])) != 24
        or observed.get("prior_verified_run_id") != prior["verified_run_id"]):
        raise ValueError("sealed reader observation is incomplete or inconsistent")
    expected_cases = {(name, step) for name in
                      ("legacy-empty", "legacy-single", "legacy-trailers", "legacy-binary")
                      for step in (1, 2, 3, 7, 64, 1024)}
    actual_cases = {(x.get("input"), x.get("segment")) for x in observed["cases"]}
    if len(actual_cases) != 24 or actual_cases != expected_cases:
        raise ValueError("missing, duplicate, or unsupported sealed reader test case")
    if any(x.get("status") != "PASSED" for x in observed["cases"]):
        raise ValueError("sealed reader baseline did not reproduce a prior case")
    return {
        "schema_version": 1,
        "kind": "sealed-reader-noninterference",
        "frame": frame,
        "source": {
            "baseline_commit": frame["baseline_commit"],
            "candidate_commit": frame["candidate_commit"],
        },
        "observations": {
            "count": 24,
            "baseline_reader_only": True,
            "candidate_reader_executions": 0,
            "sha256": hash_bytes(json.dumps(observed, sort_keys=True).encode()),
        },
        "derived_claim": {
            "id": "http1.chunked.reader.sealed",
            "status": "PRESERVED_IN_SEALED_IMPORT_CONTEXT",
            "basis": (
                "reader-only module import graph excludes writer; all seven "
                "reader source modules are identical Git blobs; original "
                "24 cases pass with inert h11 package and no writer import"
            ),
            "not_proved": (
                "normal package import context, arbitrary reflection, "
                "monkeypatching, external import hooks or all HTTP behavior"
            ),
        },
    }


def reexecute_baseline(baseline: Path, baseline_observations: Path,
                       prior_reference: Path, recorded: dict) -> None:
    """Independently regenerate sealed baseline results, never candidate reader."""
    with tempfile.TemporaryDirectory(prefix="h11-sealed-replay-") as tmp:
        regenerated = Path(tmp) / "sealed-observations.json"
        completed = subprocess.run(
            [sys.executable, "-E", "-s", "-S",
             str(baseline / "research/preservation/sealed_reader.py"),
             "--baseline", str(baseline),
             "--baseline-observations", str(baseline_observations),
             "--prior-reference", str(prior_reference),
             "--output", str(regenerated)],
            cwd=baseline, capture_output=True, text=True, check=False,
            timeout=90,
        )
        if completed.returncode:
            raise ValueError("sealed baseline reader replay failed: " +
                             (completed.stderr + completed.stdout)[-1200:])
        fresh = json.loads(regenerated.read_text())
        if fresh != recorded:
            raise ValueError("sealed reader observations differ from actual replay")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--baseline-observations", type=Path, required=True)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = source_frame(args.baseline, args.candidate)
    observed = json.loads(args.observations.read_text())
    prior = json.loads(args.prior.read_text())
    reexecute_baseline(args.baseline.resolve(), args.baseline_observations.resolve(),
                       args.prior.resolve(), observed)
    certificate = verify_observations(frame, observed, prior)
    args.output.write_text(json.dumps(certificate, sort_keys=True, indent=2) + "\n")
    print("READER_FRAME_VERIFIED", len(frame["declared_modules"]),
          "unchanged reader modules; 24 sealed baseline cases; 0 candidate reader runs")


if __name__ == "__main__":
    main()
