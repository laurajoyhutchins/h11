"""Verify candidate boundaries using trusted, independent unittest oracles.

Consumes discover.py JSON. Does not infer behavioral guarantees from source.
Runs source closures from the pinned discovered snapshot in scratch directories.
Requires assertion failures, not import errors, to count a semantic mutant killed.
Python -I -S limits import contamination but is NOT a security sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

MARKER = "__CONTRACT_VERIFY_RESULT__"


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix != ".py":
        raise ValueError("Invalid or unavailable oracle/support file: " + relative)
    return path


def candidate_key(candidate: dict[str, Any]) -> str:
    if candidate.get("kind") in {"test_exercised_module_closure", "extension_boundary"}:
        return candidate["id"]
    return "|".join([candidate["join"], *sorted((candidate["left"], candidate["right"]))])


def source_record(repo: Path, package: str, module: str, discovery: dict[str, Any]) -> tuple[str, bytes]:
    info = discovery["production_modules"][module]
    path = (repo / info["path"]).resolve()
    if not path.is_relative_to(repo.resolve()) or not path.is_file():
        raise FileNotFoundError(info["path"])
    data = path.read_bytes()
    return info["path"], data


def snapshot_mismatches(repo: Path, discovery: dict[str, Any]) -> list[str]:
    mismatches = []
    for module, info in discovery["production_modules"].items():
        try:
            path, data = source_record(repo, discovery["package"], module, discovery)
        except (OSError, ValueError) as exc:
            mismatches.append(f"{module}: {exc}")
            continue
        if git_blob(data) != info["blob_sha"]:
            mismatches.append(f"{path}: source blob differs from discovery snapshot")
    return mismatches


def select_modules(spec: dict[str, Any], pair: dict[str, Any], discovery: dict[str, Any]) -> set[str]:
    requested = spec.get("modules")
    if not isinstance(requested, list) or not requested or any(not isinstance(x, str) for x in requested):
        raise ValueError("Case modules must be a non-empty list of module names")
    modules = set(requested)
    kind = pair.get("kind", "independent_sibling_pair")
    if kind == "test_exercised_module_closure":
        permitted = {pair["module"]}
    elif kind == "extension_boundary":
        permitted = {pair["base_module"], pair["derived_module"]}
    else:
        permitted = {pair["left"], pair["right"]}
    if len(modules) != len(requested) or not modules <= permitted:
        raise ValueError("Case modules must be part of the selected discovered boundary")
    known = discovery["production_modules"]
    closure = set().union(*(set(known[m]["runtime_closure"]) for m in modules))
    if not closure <= set(known):
        raise ValueError("Unknown modules in supplied runtime import closure")
    return closure


def run_oracle(repo: Path, discovery: dict[str, Any], closure: set[str], spec: dict[str, Any],
               policy_root: Path, mutation: dict[str, str] | None, timeout: float) -> dict[str, Any]:
    """Return structured unittest output, distinguishing assertions from harness failure."""
    package = discovery["package"]
    package_path = package.replace(".", "/")
    with tempfile.TemporaryDirectory(prefix="contract-verify-") as work:
        scratch = Path(work)
        init = scratch / package_path / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text("# test-only shim; never part of production Git tree\n")
        for module in sorted(closure):
            rel, data = source_record(repo, package, module, discovery)
            if mutation and mutation["module"] == module:
                old = mutation["search"]
                new = mutation["replace"]
                if not old or old == new:
                    raise ValueError("Mutation search must be nonempty and replace must change content")
                decoded = data.decode("utf-8")
                if decoded.count(old) != 1:
                    raise ValueError(f"Mutation {mutation['id']} does not match exactly once in {module}")
                data = decoded.replace(old, new, 1).encode()
            target = scratch / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        filenames = [spec["oracle"], *spec.get("support", [])]
        for rel in filenames:
            src = safe_file(policy_root, rel)
            if Path(rel).name != rel or rel == "__init__.py" or rel in {"h11.py", "os.py", "sys.py"}:
                raise ValueError("Oracle files must be plain top-level .py names")
            (scratch / rel).write_bytes(src.read_bytes())
        if len(filenames) != len(set(filenames)):
            raise ValueError("Duplicate oracle file names")
        runner = '''import importlib,json,pathlib,sys,unittest
root=pathlib.Path(sys.argv[1]).resolve(); package=sys.argv[2]; oracle=sys.argv[3]
sys.path.insert(0,str(root))
mod=importlib.import_module(oracle)
suite=unittest.defaultTestLoader.loadTestsFromModule(mod)
if suite.countTestCases()==0: raise RuntimeError("Oracle contains no unittest test cases")
result=unittest.TextTestRunner(stream=sys.stderr,verbosity=1).run(suite)
loaded={n:getattr(o,"__file__",None) for n,o in sys.modules.items()
        if (n==package or n.startswith(package+".")) and getattr(o,"__file__",None)}
if any(not pathlib.Path(p).resolve().is_relative_to(root) for p in loaded.values()):
    raise RuntimeError("Nonlocal package code loaded: "+str(loaded))
print("__CONTRACT_VERIFY_RESULT__"+json.dumps({"tests":result.testsRun,"failures":len(result.failures),
    "errors":len(result.errors),"skipped":len(result.skipped),"success":result.wasSuccessful()}))
'''
        process = subprocess.run([sys.executable, "-I", "-S", "-c", runner, str(scratch), package,
                                  Path(spec["oracle"]).stem], text=True, capture_output=True,
                                 timeout=timeout, cwd=scratch)
        records = [line[len(MARKER):] for line in process.stdout.splitlines() if line.startswith(MARKER)]
        if len(records) != 1:
            return {"kind": "HARNESS_ERROR", "message": process.stderr[-1300:],
                    "returncode": process.returncode}
        result = json.loads(records[0])
        if process.returncode != 0:
            return {"kind": "HARNESS_ERROR", "message": process.stderr[-1300:],
                    "returncode": process.returncode}
        if result["errors"]:
            return {"kind": "HARNESS_ERROR", "message": process.stderr[-1300:], **result}
        return {"kind": "ASSERTION_FAILURE" if result["failures"] else "PASS", **result}


def verify(repo: Path, discovery: dict[str, Any], plan: dict[str, Any] | None,
           oracle_root: Path | None = None, timeout: float = 20) -> dict[str, Any]:
    """Evaluate discovered pairs, failing closed on stale inputs or weak evidence."""
    if timeout <= 0 or timeout > 120:
        raise ValueError("Timeout must be within 0..120 seconds")
    repo = repo.resolve()
    if discovery.get("schema_version") not in {1, 2}:
        raise ValueError("Unsupported discovery schema")
    if plan is not None and plan.get("schema_version") != 1:
        raise ValueError("Unsupported oracle-plan schema")
    cases = [] if plan is None else plan.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Oracle cases must be a list")
    duplicates = [x.get("id") for x in cases]
    if len(duplicates) != len(set(duplicates)):
        raise ValueError("Duplicate case identifiers")
    mismatches = snapshot_mismatches(repo, discovery)
    candidates = [
        *discovery.get("independent_sibling_candidates", []),
        *discovery.get("test_exercised_module_candidates", []),
        *discovery.get("extension_boundary_candidates", []),
    ]
    by_key = {candidate_key(p): p for p in candidates}
    result: dict[str, Any] = {
        "schema_version": 1,
        "source_snapshot_digest": json_digest({m: d["blob_sha"] for m, d in discovery["production_modules"].items()}),
        "discovery_digest": json_digest(discovery),
        "plan_digest": json_digest(plan) if plan is not None else None,
        "source_mismatches": mismatches,
        "candidates": [],
        "method": "independent unittest oracle + assertion-sensitive semantic mutations in isolated source closures",
        "disclaimer": "Finite tests and selected mutants are bounded evidence, not full semantic correctness or formal proof.",
    }
    unknown = sorted((repr(x) for x in ({case.get("candidate") for case in cases} - set(by_key))))
    if unknown:
        raise ValueError(f"Oracle plan references unrecognized discovered candidate(s): {unknown}")
    if cases and oracle_root is None:
        raise ValueError("An explicit --oracles directory is required when supplying a plan")
    for candidate in candidates:
        key = candidate_key(candidate)
        applicable = [x for x in cases if x.get("candidate") == key]
        entry: dict[str, Any] = {"candidate": key, "status": "INSUFFICIENT_EVIDENCE",
                                 "cases": [], "reason": "No independent behavioral oracle supplied"}
        if mismatches:
            entry.update(status="BLOCKED", reason="Source differs from discovered snapshot; no oracle executed")
            result["candidates"].append(entry)
            continue
        if not applicable:
            result["candidates"].append(entry)
            continue
        statuses = []
        for spec in applicable:
            case: dict[str, Any] = {"id": spec.get("id"), "status": "INSUFFICIENT_EVIDENCE",
                                    "claims": spec.get("claims", []), "mutations": [],
                                    "oracle_sha256": None}
            try:
                if not isinstance(case["claims"], list) or not case["claims"] or any(not isinstance(x,str) or not x for x in case["claims"]):
                    raise ValueError("Independent oracle needs at least one explicit behavioral claim")
                if any(m not in discovery["production_modules"] for m in spec.get("modules", [])):
                    raise ValueError("Case contains module absent from discovered package")
                closure = select_modules(spec, candidate, discovery)
                if any(discovery["production_modules"][m].get("dynamic") for m in closure):
                    case.update(status="UNSUPPORTED", reason="Dynamic imports in source closure cannot be established statically")
                    statuses.append(case["status"]); entry["cases"].append(case); continue
                root = oracle_root.resolve()  # type: ignore[union-attr]
                files = [spec["oracle"], *spec.get("support", [])]
                case["oracle_sha256"] = hashlib.sha256(b"".join(
                    hashlib.sha256(safe_file(root, f).read_bytes()).digest() for f in files)).hexdigest()
                base = run_oracle(repo, discovery, closure, spec, root, None, timeout)
                case["baseline"] = base
                case["closure"] = sorted(closure)
                if base["kind"] == "ASSERTION_FAILURE":
                    case.update(status="CONTRADICTED", reason="Original implementation violated the supplied oracle")
                elif base["kind"] != "PASS" or base.get("tests", 0) <= 0 or base.get("skipped"):
                    case.update(status="BLOCKED", reason="Original oracle could not complete cleanly")
                else:
                    declared_mutants = spec.get("mutations", [])
                    if not isinstance(declared_mutants, list):
                        raise ValueError("Mutations must be a list")
                    if not declared_mutants:
                        case.update(status="INSUFFICIENT_EVIDENCE", reason="Oracle passed but no targeted semantic mutants were challenged")
                    else:
                        outcomes = []
                        for mutation in declared_mutants:
                            if mutation.get("module") not in closure:
                                raise ValueError(f"Mutation targets a module outside case closure: {mutation.get('module')}")
                            mutated = run_oracle(repo, discovery, closure, spec, root, mutation, timeout)
                            status = ("KILLED" if mutated["kind"] == "ASSERTION_FAILURE" else
                                      "SURVIVED" if mutated["kind"] == "PASS" else "INVALID")
                            outcomes.append({"id": mutation["id"], "result": status, "test_result": mutated})
                        case["mutations"] = outcomes
                        if any(m["result"] == "INVALID" for m in outcomes):
                            case.update(status="BLOCKED", reason="One or more mutants did not reach a valid oracle verdict")
                        elif any(m["result"] == "SURVIVED" for m in outcomes):
                            case.update(status="INSUFFICIENT_EVIDENCE", reason="At least one semantic mutant survived independent oracle tests")
                        else:
                            case.update(status="VERIFIED_WITHIN_SCOPE", reason="Oracle passed; all selected semantic mutants caused assertion failures")
            except subprocess.TimeoutExpired:
                case.update(status="BLOCKED", reason="Oracle timed out")
            except (ValueError, KeyError, OSError, UnicodeDecodeError) as exc:
                case.update(status="BLOCKED", reason=f"Invalid oracle or mutation configuration: {exc}")
            statuses.append(case["status"])
            entry["cases"].append(case)
        if "CONTRADICTED" in statuses:
            entry.update(status="CONTRADICTED", reason="An independent oracle contradicts the original source")
        elif "BLOCKED" in statuses:
            entry.update(status="BLOCKED", reason="One or more cases could not be evaluated")
        elif "UNSUPPORTED" in statuses:
            entry.update(status="UNSUPPORTED", reason="Static isolation insufficient for this source")
        elif "INSUFFICIENT_EVIDENCE" in statuses:
            entry.update(status="INSUFFICIENT_EVIDENCE", reason="Some claimed behaviors lack mutation-sensitive evidence")
        elif statuses:
            entry.update(status="VERIFIED_WITHIN_SCOPE", reason="All supplied bounded contract cases passed and killed selected mutants")
        result["candidates"].append(entry)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repository", type=Path)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--plan", type=Path)
    p.add_argument("--oracles", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--timeout", type=float, default=20)
    args = p.parse_args()
    disc = json.loads(args.discovery.read_text())
    plan = json.loads(args.plan.read_text()) if args.plan else None
    report = verify(args.repository, disc, plan, args.oracles, args.timeout)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
