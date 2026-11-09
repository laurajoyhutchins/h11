"""Held-out, independently observed evaluation of coarse Git-source evidence reuse.

This evaluates the *source comparator*, not in-toto provenance, on three
third-party packages. Historical revisions 71..90 were excluded from the
earlier 1..70-per-repository falsification experiment. All oracles run in
the control arm, even on predicted REUSE decisions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contract_poset"))
from falsification import MUTATIONS, command, git, oracle  # noqa: E402

CONFIG = ("pyproject.toml", "setup.py", "setup.cfg",
          "tox.ini", "requirements.txt", "requirements-dev.txt")
START_AFTER = 70
REVISION_COUNT = 20


def source_snapshot(repo: Path, revision: str, prefix: str) -> dict[str, str]:
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", revision],
    )
    files: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        left, right = entry.split(b"\t", 1)
        path = right.decode("utf-8")
        if path.startswith(prefix) or path in CONFIG:
            mode, kind, oid = left.decode("ascii").split()
            files[path] = f"{mode}:{kind}:{oid}"
    return files


def choose(baseline: dict[str, str], other: dict[str, str],
           prefix: str, env_equal: bool = True) -> tuple[str, list[str]]:
    if not env_equal or not baseline or not any(k.startswith(prefix) for k in baseline):
        return "UNKNOWN", ["NO_VALID_BASELINE_OR_ENV"]
    if not other or not any(k.startswith(prefix) for k in other):
        return "UNKNOWN", ["TARGET_PACKAGE_MISSING"]
    changed = sorted(k for k in baseline.keys() | other.keys()
                     if baseline.get(k) != other.get(k))
    if changed:
        return "REVERIFY", changed
    return "REUSE", []


def local_adversaries(repo: Path, target: dict, original: str,
                      baseline: dict[str, str], expected: dict,
                      prefix: str) -> list[dict]:
    git(repo, "checkout", "-q", "--detach", "-f", original)
    git(repo, "config", "user.email", "research@example.invalid")
    git(repo, "config", "user.name", "Evidence Research")
    cases: list[dict] = []
    # A genuinely source-independent change should permit reuse.
    note = repo / "evidence-independent-note.txt"
    note.write_text("local-only analysis artifact\n")
    git(repo, "add", note.name)
    git(repo, "commit", "-qm", "fixture: independent note")
    docs = git(repo, "rev-parse", "HEAD")
    choice, paths = choose(baseline, source_snapshot(repo, docs, prefix), prefix)
    observed, secs, error = oracle(repo, target["package"])
    cases.append({"label": "independent-note", "decision": choice,
                  "observed_equal": observed == expected if observed is not None else None,
                  "assessable": observed is not None, "error": error,
                  "oracle_seconds": round(secs, 6), "changed": paths})
    if choice != "REUSE" or observed != expected:
        raise ValueError("unrelated note failed expected reuse observation")

    # The known initializer counterexample remains mandatory regression,
    # but this is *not* claimed as a held-out adversarial observation.
    git(repo, "checkout", "-q", "--detach", "-f", original)
    init = repo / target["source"] / target["package"] / "__init__.py"
    init.write_bytes(init.read_bytes() + MUTATIONS[target["package"]].encode())
    git(repo, "add", str(init.relative_to(repo)))
    git(repo, "commit", "-qm", "fixture: initializer semantic change")
    changed = git(repo, "rev-parse", "HEAD")
    decision, paths = choose(baseline, source_snapshot(repo, changed, prefix), prefix)
    observed, secs, error = oracle(repo, target["package"])
    cases.append({"label": "known-initializer-regression", "decision": decision,
                  "observed_equal": observed == expected if observed is not None else None,
                  "assessable": observed is not None, "error": error,
                  "oracle_seconds": round(secs, 6), "changed": paths})
    if decision != "REVERIFY":
        raise ValueError("initializer mutation was incorrectly reused")

    # A novel file inside the source tree cannot silently enter the program.
    git(repo, "checkout", "-q", "--detach", "-f", original)
    inserted = repo / target["source"] / target["package"] / "_new_dependency_fixture.py"
    inserted.write_text("VALUE = 'decoy'\n")
    git(repo, "add", str(inserted.relative_to(repo)))
    git(repo, "commit", "-qm", "fixture: newly tracked source module")
    added = git(repo, "rev-parse", "HEAD")
    decision, paths = choose(baseline, source_snapshot(repo, added, prefix), prefix)
    cases.append({"label": "added-source-module", "decision": decision,
                  "changed": paths})
    if decision != "REVERIFY":
        raise ValueError("new source module was incorrectly reused")
    decision, paths = choose(baseline, baseline, prefix, env_equal=False)
    cases.append({"label": "changed-environment", "decision": decision,
                  "changed": paths})
    if decision != "UNKNOWN":
        raise ValueError("environment drift was incorrectly reused")
    return cases


def evaluate(target: dict, root: Path, count: int) -> dict[str, Any]:
    pkg = target["package"]
    repo = root / pkg
    command("git", "clone", "-q", "--no-tags", f"https://github.com/{target['repository']}.git",
            str(repo))
    head = target["commit"]
    if git(repo, "rev-parse", head + "^{commit}") != head:
        raise ValueError("pinned source unavailable")
    prefix = f"{target['source']}/{pkg}/"
    baseline = source_snapshot(repo, head, prefix)
    git(repo, "checkout", "-q", "--detach", "-f", head)
    expected, baseline_cost, err = oracle(repo, pkg)
    if expected is None:
        raise ValueError(f"pinned baseline oracle invalid: {err}")
    history = git(repo, "rev-list", "--first-parent", "-n",
                  str(START_AFTER + count + 1), head).splitlines()
    if len(history) < START_AFTER + count + 1:
        raise ValueError("held-out first-parent history too short")
    selected = history[START_AFTER + 1:START_AFTER + count + 1]
    baseline_git = git(repo, "rev-parse", head + "^{tree}")

    # Measure the entire verification arm, including Git checkout and process
    # startup. Every oracle is run independently to expose missed changes.
    control_started = time.perf_counter()
    observed_by_revision: dict[str, tuple[dict | None, str | None]] = {}
    control_rows = []
    for revision in selected:
        git(repo, "checkout", "-q", "--detach", "-f", revision)
        result, seconds, error = oracle(repo, pkg)
        observed_by_revision[revision] = (result, error)
        control_rows.append({"revision": revision, "assessable": result is not None,
                             "oracle_seconds": round(seconds, 6), "error": error})
    control_elapsed = time.perf_counter() - control_started

    selective_started = time.perf_counter()
    rows = []
    for index, revision in enumerate(selected, 1):
        other = source_snapshot(repo, revision, prefix)
        decision, changed = choose(baseline, other, prefix)
        observation, error = observed_by_revision[revision]
        difference = observation != expected if observation is not None else None
        missed = decision == "REUSE" and difference is True
        candidate: dict[str, Any] = {
            "label": f"heldout-{START_AFTER + index:03}",
            "commit": revision,
            "decision": decision,
            "changed_paths": changed,
            "assessable": observation is not None,
            "behavior_changed": difference,
            "missed_change": missed,
            "oracle_error": error,
        }
        if decision != "REUSE":
            git(repo, "checkout", "-q", "--detach", "-f", revision)
            second, secs, second_error = oracle(repo, pkg)
            candidate["selective_oracle_seconds"] = round(secs, 6)
            candidate["selective_error"] = second_error
            if second != observation or second_error != error:
                candidate["repeatability_failure"] = True
        rows.append(candidate)
    selective_elapsed = time.perf_counter() - selective_started
    adversaries = local_adversaries(repo, target, head, baseline, expected, prefix)
    return {
        "repository": target["repository"], "source_commit": head,
        "source_tree": baseline_git, "baseline_oracle_seconds": round(baseline_cost, 6),
        "heldout_after_prior_70": count,
        "source_tracking": "all tracked paths under src/package plus known root config",
        "history": rows, "adversarial": adversaries,
        "metrics": {
            "control_wall_seconds": round(control_elapsed, 6),
            "selective_wall_seconds": round(selective_elapsed, 6),
            "wall_savings_fraction": round(1 - selective_elapsed / control_elapsed, 6)
                                     if control_elapsed else None,
            "reuse": sum(row["decision"] == "REUSE" for row in rows),
            "reverify": sum(row["decision"] == "REVERIFY" for row in rows),
            "unknown": sum(row["decision"] == "UNKNOWN" for row in rows),
            "assessable": sum(row["assessable"] for row in rows),
            "unassessable": sum(not row["assessable"] for row in rows),
            "misses": sum(row["missed_change"] for row in rows),
            "nondeterministic": sum(bool(row.get("repeatability_failure")) for row in rows),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--checkout-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--history-count", type=int, default=REVISION_COUNT)
    args = p.parse_args()
    if not 1 <= args.history_count <= 25:
        raise ValueError("bounded heldout count must be 1..25")
    protocol = json.loads(args.protocol.read_text())
    if protocol["schema_version"] != 1 or len(protocol["repos"]) != 3:
        raise ValueError("unexpected target protocol")
    args.checkout_root.mkdir(parents=True, exist_ok=True)
    results = []
    for target in protocol["repos"]:
        record = evaluate(target, args.checkout_root, args.history_count)
        print("HELDOUT", record["repository"], json.dumps(record["metrics"], sort_keys=True),
              flush=True)
        results.append(record)
    total_control = sum(r["metrics"]["control_wall_seconds"] for r in results)
    total_selective = sum(r["metrics"]["selective_wall_seconds"] for r in results)
    report = {
        "schema_version": 1, "test_type": "post-hoc held-out observational challenge",
        "past_historical_experiment_revision_count": START_AFTER,
        "new_historical_revisions_per_repository": args.history_count,
        "source_selection": "whole tracked source subtree, not prior AST import-only closure",
        "results": results,
        "totals": {
            "comparisons": 3 * args.history_count,
            "assessable": sum(r["metrics"]["assessable"] for r in results),
            "unassessable": sum(r["metrics"]["unassessable"] for r in results),
            "missed_observable_changes": sum(r["metrics"]["misses"] for r in results),
            "nondeterministic_observations": sum(r["metrics"]["nondeterministic"] for r in results),
            "control_wall_seconds": round(total_control, 6),
            "selective_wall_seconds": round(total_selective, 6),
            "wall_savings_fraction": round(1 - total_selective / total_control, 6)
                                     if total_control else None,
        },
        "limitations": [
            "Not the in-toto consumer: only the identical whole-source Git comparison is exercised.",
            "This protocol uses pinned probes, not complete package behavior.",
            "Untracked runtime inputs, environment drift, and external dependencies are not proven absent.",
            "Every historical oracle is rerun in the control arm to detect observable misses.",
            "The known initializer mutation is a regression case, not a new held-out example.",
            "Control and selective wall times are two sequential measurements in the same VM, including Git checkouts.",
            "Unassessable observations cannot support a zero-miss guarantee.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("TOTAL", json.dumps(report["totals"], sort_keys=True), flush=True)
    if report["totals"]["missed_observable_changes"]:
        raise SystemExit("FALSIFIED: observed behavior changed despite selector reuse")


if __name__ == "__main__":
    main()
