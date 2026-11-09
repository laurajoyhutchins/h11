"""Blind repository transfer: deterministic fault sensitivity from original tests.

Run only on a pinned, trusted repo. Never promotes original tests into independent
semantic specifications or mutates remote repository state.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SEED = "source-contract-transfer-v1"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def choose(discovery: dict) -> list[dict]:
    """Select all module/test pairs by name AND direct source import, not judgment."""
    pkg = discovery["package"]
    source = discovery["production_modules"]
    items = []
    for test in discovery["tests"]:
        name = Path(test["path"]).stem
        if not name.startswith("test_"):
            continue
        module = pkg + "." + name[5:]
        if module in source and module in test["direct_production_imports"]:
            items.append({"module": module, "test": test["path"],
                          "source": source[module]["path"]})
    return sorted(items, key=lambda x: (x["module"], x["test"]))


class Conditions(ast.NodeVisitor):
    def __init__(self):
        self.depth = 0
        self.items = []

    def visit_FunctionDef(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node):
        if self.depth and hasattr(node.test, "end_lineno"):
            self.items.append(node.test)
        self.generic_visit(node)


def mutants(path: Path, source: bytes, limit: int = 2) -> list[dict]:
    finder = Conditions()
    finder.visit(ast.parse(source, filename=str(path)))
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    possibilities = []
    for node in finder.items:
        a = starts[node.lineno - 1] + node.col_offset
        b = starts[node.end_lineno - 1] + node.end_col_offset
        original = source[a:b]
        if not original:
            continue
        mutated = source[:a] + b"not (" + original + b")" + source[b:]
        try:
            compile(mutated, str(path), "exec")
        except SyntaxError:
            continue
        identity = sha(SEED.encode() + source + str(a).encode() + original)
        possibilities.append({"id": identity[:16], "line": node.lineno,
                              "original_expression": original.decode("utf-8", "replace")[:120],
                              "modified": mutated})
    return sorted(possibilities, key=lambda x: x["id"])[:limit]


def pytest_result(repo: Path, target: str, env: dict, timeout: int) -> dict:
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short",
                               "--disable-warnings", target], cwd=repo, env=env,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"verdict": "TIMEOUT"}
    output = proc.stdout + proc.stderr
    matches = [x.strip() for x in output.splitlines()
               if re.search(r"\b\d+ (passed|failed|errors?|skipped)\b", x)]
    if proc.returncode == 0:
        verdict = "PASS"
    elif proc.returncode == 1 and re.search(r"\b\d+ failed\b", output) and not re.search(r"\b\d+ errors?\b", output):
        verdict = "DETECTED_BY_ORIGINAL_TEST_FAILURE"
    else:
        verdict = "BLOCKED_OR_INVALID"
    return {"verdict": verdict, "exit_code": proc.returncode,
            "summary": matches[-2:], "stderr_tail": output[-350:]}


def run(repo: Path, discovery: dict, revision: str, timeout: int = 45) -> dict:
    repo = repo.resolve()
    if git(repo, "rev-parse", "HEAD") != revision:
        raise ValueError("Target HEAD differs from preregistered commit")
    if git(repo, "status", "--porcelain"):
        raise ValueError("Target checkout is not clean")
    env = os.environ.copy()
    src = (repo / discovery.get("source_dir", ".")).resolve()
    if not src.is_relative_to(repo):
        raise ValueError("Source path is outside target checkout")
    env["PYTHONPATH"] = str(src)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    selected = choose(discovery)
    baseline = pytest_result(repo, "tests", env, timeout)
    result = {
        "schema_version": 1, "target_commit": revision,
        "target_tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "candidate_pairs": len(discovery["independent_sibling_candidates"]),
        "selected": selected, "original_baseline": baseline, "trials": [],
        "selection_rule": "All test_<module>.py basename matches that import corresponding source module",
        "mutation_rule": "Two SHA256-ordered function-level conditional inversions per selected module",
        "independent_oracle_count": 0,
        "conclusion": "TEST_SENSITIVITY_ONLY_NOT_CONTRACT_VERIFICATION",
    }
    if baseline["verdict"] != "PASS":
        result["conclusion"] = "BLOCKED_BASELINE"
        return result
    verify_import = subprocess.run([sys.executable, "-c",
        "import importlib,pathlib,sys;"
        "m=importlib.import_module(sys.argv[1]);"
        "assert pathlib.Path(m.__file__).resolve().is_relative_to("
        "pathlib.Path(sys.argv[2]).resolve()),m.__file__",
        discovery["package"], str(src)], cwd=repo, env=env,
        capture_output=True, text=True, timeout=timeout)
    if verify_import.returncode:
        result["conclusion"] = "BLOCKED_NONLOCAL_IMPORT"
        result["import_error"] = verify_import.stderr[-500:]
        return result
    for target in selected:
        path = (repo / target["source"]).resolve()
        if not path.is_relative_to(repo):
            raise ValueError("Target file outside checkout")
        original = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest()
        if blob != discovery["production_modules"][target["module"]]["blob_sha"]:
            raise ValueError("Stale discovery source snapshot")
        local = pytest_result(repo, target["test"], env, timeout)
        if local["verdict"] != "PASS":
            result["trials"].append({"module": target["module"],
                                     "result": "BLOCKED_TEST_BASELINE", "baseline": local})
            continue
        for mutation in mutants(path, original):
            try:
                path.write_bytes(mutation["modified"])
                verdict = pytest_result(repo, target["test"], env, timeout)
            finally:
                path.write_bytes(original)
            if path.read_bytes() != original:
                raise AssertionError("Unable to restore original file bytes")
            result["trials"].append({
                "module": target["module"], "test": target["test"],
                "mutant_id": mutation["id"], "line": mutation["line"],
                "source_condition": mutation["original_expression"],
                "mutation": "invert-conditional", "result": verdict,
            })
    if git(repo, "status", "--porcelain"):
        raise AssertionError("Mutation trials left the repo dirty")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repository", type=Path)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.repository, json.loads(args.discovery.read_text()), args.revision)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "baseline": result["original_baseline"]["summary"],
        "candidate_pairs": result["candidate_pairs"],
        "selected_modules": len(result["selected"]),
        "mutants": len(result["trials"]),
        "detected": sum(x.get("result", {}).get("verdict") == "DETECTED_BY_ORIGINAL_TEST_FAILURE" for x in result["trials"]),
        "survived": sum(x.get("result", {}).get("verdict") == "PASS" for x in result["trials"]),
        "conclusion": result["conclusion"],
    }, indent=2))


if __name__ == "__main__":
    main()
