"""Equal-budget calibration of architectural ranking against a size baseline.

Neither ranking is trained on mutant results. Full original pytest suite is
the common mutation-sensitivity oracle; the already-published independent
chunked-codec oracle bank is reported separately, not conflated with pytest.
This is a calibration on familiar h11, not a blind generalization test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Load the research ranking module by path without importing it as "select",
# which would shadow CPython's native select module used by subprocess.
import importlib.util
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _SCRIPT_DIR]
_SPEC = importlib.util.spec_from_file_location("research_ranking", _SCRIPT_DIR / "select.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Cannot load pinned ranking implementation")
_RANKING = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RANKING)
ranked_select = _RANKING.select

from blind_transfer import git, mutants, pytest_result

EXPECTED_TREE = "5a1cacdb9d0d6e8d18e8161924ae18130da6c130"
ORACLE_BANK_MODULES = ("h11._readers", "h11._writers")


def baseline_modules(discovery: dict, budget: int = 3) -> list[dict]:
    production = discovery["production_modules"]
    tested = {
        module for test in discovery["tests"]
        for module in test["direct_production_imports"]
        if module in production and module != discovery["package"]
    }
    modules = sorted(tested, key=lambda module: (-production[module]["loc"], module))
    return [{"id": "largest-tested|" + m, "module": m,
             "source_loc": production[m]["loc"]}
            for m in modules[:budget]]


def treatments(discovery: dict, budget: int = 3) -> list[dict]:
    selected = ranked_select(discovery, budget)["selected"]
    items = []
    for candidate in selected:
        if candidate["family"] == "test_exercised_module_closure":
            module = candidate["focus_modules"][0]
        elif candidate["family"] == "extension_boundary":
            # Source-derived extension IDs encode base and derived qualified names.
            derived = candidate["id"].split("|")[-1]
            module = derived.rpartition(".")[0]
        elif candidate["family"] == "independent_sibling_pair":
            module = sorted(candidate["focus_modules"])[0]
        else:
            raise ValueError("Unknown candidate family")
        if module not in discovery["production_modules"]:
            raise ValueError("Unresolved selected mutation module: " + module)
        items.append({"id": candidate["id"], "module": module,
                      "family": candidate["family"], "selection_score": candidate["greedy_score"]})
    return items


def run(repo: Path, discovery: dict, expected_commit: str,
        budget: int = 3, faults_per_selection: int = 3,
        timeout: int = 35) -> dict:
    repo = repo.resolve()
    if git(repo, "rev-parse", "HEAD") != expected_commit:
        raise RuntimeError("Wrong pinned source checkout")
    if git(repo, "rev-parse", "HEAD^{tree}") != EXPECTED_TREE:
        raise RuntimeError("Pinned source tree changed")
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("Dirty source worktree before testing")
    if discovery["schema_version"] != 2 or discovery["package"] != "h11":
        raise ValueError("This pinned calibration must use h11 discovery v2")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    test_baseline = pytest_result(repo, "h11/tests", env, timeout)
    if test_baseline["verdict"] != "PASS":
        raise RuntimeError("Original source has failing tests: " + repr(test_baseline))
    arms = {
        "architecture_ranking": treatments(discovery, budget),
        "largest_test_imported_modules": baseline_modules(discovery, budget)
    }
    trials: dict[str, list[dict]] = {}
    original_bytes: dict[str, bytes] = {}
    for arm, selections in arms.items():
        trials[arm] = []
        for chosen in selections:
            module = chosen["module"]
            info = discovery["production_modules"][module]
            file = (repo / info["path"]).resolve()
            if not file.is_relative_to(repo):
                raise RuntimeError("Module path escaped checkout")
            original = file.read_bytes()
            object_sha = hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest()
            if object_sha != info["blob_sha"]:
                raise RuntimeError("Discovery blob mismatch: " + module)
            original_bytes.setdefault(module, original)
            available = mutants(file, original, faults_per_selection)
            for mutation in available:
                assert file.read_bytes() == original
                try:
                    file.write_bytes(mutation["modified"])
                    observation = pytest_result(repo, "h11/tests", env, timeout)
                finally:
                    file.write_bytes(original)
                if file.read_bytes() != original:
                    raise RuntimeError("Failed to restore original source bytes")
                result = observation["verdict"]
                kind = ("DETECTED" if result == "DETECTED_BY_ORIGINAL_TEST_FAILURE" else
                        "SURVIVED" if result == "PASS" else "INVALID")
                trials[arm].append({
                    "module": module, "selection": chosen["id"],
                    "mutant_id": mutation["id"], "line": mutation["line"],
                    "condition": mutation["original_expression"],
                    "classification": kind,
                    "original_tests": observation
                })
                print(arm, module, mutation["id"], kind, flush=True)
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("Dirty source worktree after trials")
    for module, original in original_bytes.items():
        if (repo / discovery["production_modules"][module]["path"]).read_bytes() != original:
            raise RuntimeError("Original source bytes changed")
    summaries = {}
    for arm, selections in arms.items():
        ts = trials[arm]
        detected = sum(t["classification"] == "DETECTED" for t in ts)
        survived = sum(t["classification"] == "SURVIVED" for t in ts)
        invalid = sum(t["classification"] == "INVALID" for t in ts)
        covered = sorted(set(s["module"] for s in selections) & set(ORACLE_BANK_MODULES))
        summaries[arm] = {
            "selections": selections,
            "allocated_mutation_slots": budget * faults_per_selection,
            "actual_mutation_trials": len(ts),
            "detected_by_original_tests": detected,
            "survived_original_tests": survived,
            "invalid_or_uninterpretable": invalid,
            "valid_mutant_detection_fraction": (
                detected / (detected + survived) if detected + survived else None),
            "known_independent_oracle_bank_modules": covered,
            "known_oracle_bank_coverage": len(covered),
            "redundant_selections": len(selections) - len({s["module"] for s in selections}),
        }
    return {
        "schema_version": 1,
        "source_commit": expected_commit,
        "source_tree": EXPECTED_TREE,
        "baseline_pytest": test_baseline,
        "parameters": {
            "selections_per_arm": budget,
            "mutants_per_selection": faults_per_selection,
            "operator": "function-scoped-If-test inversion, SHA256 sorted",
            "test_suite": "full original h11/tests",
            "independent_oracle_bank_modules": list(ORACLE_BANK_MODULES)
        },
        "results": summaries,
        "trials": trials,
        "limitations": [
            "Original tests do not constitute independent semantic oracles.",
            "The existing independent oracle bank covers only ChunkedReader and ChunkedWriter.",
            "Uncovered selections cannot be judged by the existing independent contract bank.",
            "Identical mutants on overlap are shared, not independently sampled.",
            "Test mutation sensitivity is a limited proxy, not measured contract utility.",
            "This is a familiar repository, not a blind holdout."
        ]
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repository", type=Path)
    p.add_argument("--discovery", required=True, type=Path)
    p.add_argument("--revision", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    results = run(args.repository, json.loads(args.discovery.read_text()), args.revision)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print("SUMMARY", json.dumps(results["results"], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
