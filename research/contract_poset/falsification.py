"""Falsify an import-only Git-blob contract evidence reuse rule.

Protocol is pinned in falsification_preregistration.json, committed *before*
this experiment. Evaluates historical first-parent revisions and local-only,
adversarial package-initializer changes in three independently selected repos.

No source is pushed to any repo. The target code runs in disposable GitHub CI.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROBE_CODE = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
repo = os.environ["EVAL_PACKAGE"]
if repo == "blinker":
    from blinker import Signal
    signal = Signal()
    def receiver(sender, **values):
        return [sender, values["number"]]
    signal.connect(receiver, weak=False)
    received = signal.send("caller", number=7)
    result = {"receivers": [v for _, v in received], "receiver_count": len(received)}
elif repo == "hpack":
    from hpack import Encoder, Decoder
    headers = [(b":method", b"GET"), (b":path", b"/"), (b"x-study", b"fixed")]
    encoded = bytes(Encoder().encode(headers))
    observed = Decoder().decode(encoded, raw=True)
    converted = [[bytes(k).hex(), bytes(v).hex()] for k, v in observed]
    expected = [[k.hex(), v.hex()] for k, v in headers]
    result = {"encoded_hex": encoded.hex(), "decoded": converted, "round_trip": converted == expected}
elif repo == "hyperframe":
    from hyperframe.frame import DataFrame, Frame
    frame = DataFrame(1)
    frame.data = b"fixed-frame-data"
    encoded = frame.serialize()
    decoded, length = Frame.parse_frame_header(memoryview(encoded[:9]))
    decoded.parse_body(memoryview(encoded[9:9+length]))
    result = {"encoded_hex": encoded.hex(), "payload_hex": bytes(decoded.data).hex(),
              "frame_length": int(length), "round_trip": bytes(decoded.data) == b"fixed-frame-data"}
else:
    raise ValueError("Unknown preregistered package")
print("__ORACLE_JSON__" + json.dumps(result, sort_keys=True, separators=(",", ":")))
'''

MUTATIONS: dict[str, str] = {
    "blinker": "\nSignal.send = lambda self, sender=None, **kwargs: []\n",
    "hpack": "\nEncoder.encode = lambda self, headers, *args, **kwargs: b''\n",
    "hyperframe": "\nfrom .frame import DataFrame\nDataFrame.serialize = lambda self: b'\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x01'\n",
}


def command(*argv: str, cwd: Path | None = None, check: bool = True) -> str:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise ValueError(f"Command failed {argv!r}: {p.stderr[:1400]}")
    return p.stdout.strip()


def git(repo: Path, *argv: str) -> str:
    return command("git", "-C", str(repo), *argv)


def blobs(repo: Path, commit: str, root: str) -> dict[str, str]:
    raw = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-rz", commit, "--", root],
        capture_output=True, check=True,
    ).stdout
    files = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        info, path = item.split(b"\t", 1)
        mode, kind, oid = info.decode().split()
        if kind == "blob":
            files[path.decode()] = f"{mode}:{oid}"
    return files


def resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    package = module if is_package else module.rpartition(".")[0]
    parts = package.split(".")
    if level > len(parts):
        return ""
    if level:
        parts = parts[:len(parts) - level + 1]
        if not parts:
            return ""
    else:
        parts = []
    if target:
        parts.extend(target.split("."))
    return ".".join(parts)


def static_closure(checkout: Path, source: str, package: str, focus: str) -> list[str]:
    """Explicit AST imports only: intentionally does not add implicit package init."""
    root = checkout / source / package
    if not root.is_dir():
        raise ValueError("Pinned source package missing: " + package)
    paths = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(checkout / source)
        segments = list(rel.with_suffix("").parts)
        if segments[-1] == "__init__":
            segments.pop()
        if segments:
            paths[".".join(segments)] = path
    if focus not in paths:
        raise ValueError("Pinned focus module missing: " + focus)
    graph = {}
    for name, path in sorted(paths.items()):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        deps = set()
        is_package = path.name == "__init__.py"
        for n in ast.walk(tree):
            candidates = []
            if isinstance(n, ast.Import):
                candidates.extend(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                base = (resolve_relative(name, is_package, n.level, n.module)
                        if n.level else n.module or "")
                candidates.append(base)
                candidates.extend(f"{base}.{a.name}" for a in n.names if base)
            deps.update(c for c in candidates if c in paths and c != name)
        graph[name] = deps
    closure = set()
    pending = [focus]
    while pending:
        node = pending.pop()
        if node not in closure:
            closure.add(node)
            pending.extend(sorted(graph[node] - closure))
    return sorted(str(paths[x].relative_to(checkout)) for x in closure)


def oracle(repo: Path, package: str) -> tuple[dict[str, Any] | None, float, str | None]:
    env = dict(os.environ, EVAL_PACKAGE=package, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    start = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, "-B", "-I", "-S", "-c", PROBE_CODE],
                           cwd=repo, env=env, capture_output=True, text=True,
                           timeout=10)
    except subprocess.TimeoutExpired:
        return None, time.perf_counter() - start, "oracle timeout"
    duration = time.perf_counter() - start
    if p.returncode:
        return None, duration, p.stderr.strip()[-300:]
    output = [s[len("__ORACLE_JSON__"):]
              for s in p.stdout.splitlines() if s.startswith("__ORACLE_JSON__")]
    if len(output) != 1:
        return None, duration, "missing or ambiguous oracle observation"
    try:
        return json.loads(output[0]), duration, None
    except json.JSONDecodeError:
        return None, duration, "invalid oracle JSON"


def evaluate_revision(repo: Path, package: str, label: str, rev: str, baseline: dict[str, str],
                      source_prefix: str, closure: list[str], expected: dict,
                      records: list[dict], totals: dict) -> None:
    start = time.perf_counter()
    current = blobs(repo, rev, source_prefix)
    changed = [p for p in closure if current.get(p) != baseline.get(p)]
    verdict = "REVERIFY" if changed else "REUSE"
    totals["index_seconds"] += time.perf_counter() - start
    git(repo, "checkout", "-q", "--detach", "-f", rev)
    observed, secs, error = oracle(repo, package)
    row: dict[str, Any] = {
        "label": label, "commit": rev, "verdict": verdict,
        "changed_tracked_paths": changed,
        "oracle_seconds": round(secs, 6),
        "assessable": observed is not None,
    }
    if observed is None:
        totals["unassessable"] += 1
        row["oracle_error"] = error
    else:
        difference = observed != expected
        missed = difference and verdict == "REUSE"
        row.update(observation=observed, behavior_changed=difference, missed_change=missed)
        totals["assessable"] += 1
        totals["changed_observations"] += int(difference)
        totals["misses"] += int(missed)
        totals["full_oracle_seconds"] += secs
        if verdict == "REVERIFY":
            totals["selected_oracle_seconds"] += secs
    records.append(row)


def evaluate_one(target: dict, root: Path, history_count: int) -> dict:
    repo_name = target["repository"]
    package = target["package"]
    head = target["commit"]
    checkout = root / package
    command("git", "clone", "-q", "--no-tags", f"https://github.com/{repo_name}.git",
            str(checkout))
    if git(checkout, "rev-parse", head + "^{commit}") != head:
        raise ValueError("Pinned revision unavailable: " + repo_name)
    git(checkout, "checkout", "-q", "--detach", "-f", head)
    start = time.perf_counter()
    paths = static_closure(checkout, target["source"], package, target["focus"])
    if f"{target['source']}/{package}/__init__.py" in paths:
        raise ValueError("Adversarial initializer already tracked; test not targeted")
    base = blobs(checkout, head, f"{target['source']}/{package}")
    if any(path not in base for path in paths):
        raise ValueError("Pinned source closure missing a Git object")
    analysis_seconds = time.perf_counter() - start
    expected, baseline_seconds, base_error = oracle(checkout, package)
    if expected is None:
        raise ValueError(f"Pinned oracle failed for {repo_name}: {base_error}")
    hist = git(checkout, "rev-list", "--first-parent", "-n", str(history_count + 1), head).splitlines()
    if len(hist) != history_count + 1:
        raise ValueError(f"Insufficient history in {repo_name}: {len(hist)-1}/{history_count}")
    records = []
    totals = {"index_seconds": analysis_seconds,
              "assessable": 0, "unassessable": 0, "changed_observations": 0,
              "misses": 0, "full_oracle_seconds": 0., "selected_oracle_seconds": 0.}
    for number, rev in enumerate(hist[1:], 1):
        evaluate_revision(checkout, package, f"historical-{number:03}", rev, base,
                          f"{target['source']}/{package}", paths, expected, records, totals)

    # A new, real but never-pushed Git commit changes only the package
    # initializer. The naive import-only closure doesn't record that file.
    git(checkout, "checkout", "-q", "--detach", "-f", head)
    git(checkout, "config", "user.email", "ci-experiment@example.invalid")
    git(checkout, "config", "user.name", "CI Experiment")
    init = checkout / target["source"] / package / "__init__.py"
    before = init.read_bytes()
    patch = MUTATIONS[package].encode()
    init.write_bytes(before + patch)
    git(checkout, "add", "--", str(init.relative_to(checkout)))
    git(checkout, "commit", "-qm", f"local only: {package} initializer semantic mutation")
    adversarial = git(checkout, "rev-parse", "HEAD")
    evaluate_revision(checkout, package, "adversarial-initializer", adversarial,
                      base, f"{target['source']}/{package}", paths, expected, records, totals)
    if records[-1]["verdict"] != "REUSE":
        raise ValueError("Preregistered adversarial initializer no longer avoids static closure")
    control = totals["full_oracle_seconds"]
    indexed = totals["selected_oracle_seconds"] + totals["index_seconds"]
    totals["counterfactual_savings_fraction"] = (
        round(1 - indexed / control, 6) if control > 0 else None
    )
    return {
        "repository": repo_name, "source_commit": head,
        "source_tree": git(checkout, "rev-parse", head + "^{tree}"),
        "source_closure_paths": paths,
        "source_closure_oids": {p: base[p] for p in paths},
        "pinned_oracle": expected,
        "baseline_oracle_seconds": round(baseline_seconds, 6),
        "history_requested": history_count,
        "observations": records,
        "totals": totals,
        "local_only_adversarial_oid": adversarial,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--checkout-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    protocol = json.loads(args.protocol.read_text())
    if protocol["schema_version"] != 1:
        raise ValueError("Unknown preregistration schema")
    args.checkout_root.mkdir(parents=True, exist_ok=True)
    results = []
    for target in protocol["repos"]:
        case = evaluate_one(target, args.checkout_root, target["history_first_parent_revisions"])
        totals = case["totals"]
        adversarial = case["observations"][-1]
        print("CASE", target["repository"],
              "assessable", totals["assessable"],
              "misses", totals["misses"],
              "history_requested", case["history_requested"],
              "adversarial", {
                  "assessable": adversarial["assessable"],
                  "miss": adversarial.get("missed_change"),
                  "verdict": adversarial["verdict"],
              }, flush=True)
        results.append(case)

    all_rows = [row for repo in results for row in repo["observations"]]
    misses = [
        {"repository": c["repository"], "label": row["label"], "commit": row["commit"],
         "observed": row["observation"], "tracked_source_paths": c["source_closure_paths"]}
        for c in results for row in c["observations"] if row.get("missed_change")
    ]
    assessable = sum(row["assessable"] for row in all_rows)
    control = sum(c["totals"]["full_oracle_seconds"] for c in results)
    indexed = sum(c["totals"]["selected_oracle_seconds"] + c["totals"]["index_seconds"]
                  for c in results)
    total_historical = sum(c["history_requested"] for c in results)
    result = {
        "schema_version": 1,
        "protocol_sha256": hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        "python": platform.python_version(), "assessment_scope": "observational; not normative regression",
        "total_historical_revisions_requested": total_historical,
        "total_adversarial_revisions": len(results),
        "assessable_revisions": assessable,
        "unassessable_revisions": sum(not row["assessable"] for row in all_rows),
        "missed_observable_changes": len(misses),
        "misses": misses,
        "control_oracle_seconds": round(control, 6),
        "counterfactual_selected_oracles_plus_index_seconds": round(indexed, 6),
        "counterfactual_savings_fraction": round(1 - indexed / control, 6) if control else None,
        "hypothesis_falsified_by_soundness_counterexample": bool(misses),
        "all_preregistered_comparisons_assessable": assessable == total_historical + len(results),
        "complete_hypothesis_success": (
            assessable == total_historical + len(results)
            and not misses and control > 0 and (1 - indexed / control) >= 0.5
        ),
        "per_repository": results,
        "scope_limitations": [
            "Static import-only AST predictor omitted implicit package initialization.",
            "Historical revisions may intentionally alter behavior; this is not a regression label.",
            "Measurements are counterfactual estimates from recorded full-oracle subprocess times.",
            "The index does not verify plugin registration, import side effects, environment changes or hidden dynamic dependencies.",
            "No behavioral evidence is inferred from Git ancestry alone.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("TOTAL", json.dumps({
        "historical": total_historical,
        "adversarial": len(results),
        "assessable": assessable,
        "misses": len(misses),
        "savings_fraction": result["counterfactual_savings_fraction"],
        "falsified": result["hypothesis_falsified_by_soundness_counterexample"],
    }, sort_keys=True), flush=True)
    if result["complete_hypothesis_success"]:
        raise SystemExit("Protocol success does not prove general soundness")


if __name__ == "__main__":
    main()
