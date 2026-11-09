"""Index bounded contract evidence against *existing* Git revisions.

Uses the original source import closures and Git blob identities. Does NOT
generate a chronology, execute the target package, infer specifications,
re-run oracles, or turn Git ancestry into semantic implication.

"REUSE_ELIGIBLE" means only that the exact source blobs supporting a previously
reported isolated oracle are still present. It is NOT a fresh verification and
does not establish whole-program behavior in a changed repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from poset import (
    digest, git_commit, git_objects, git_text, module_poset,
    validate_graph, validate_source,
)


def claim_basis(discovery: dict[str, Any], contracts: dict[str, Any],
                links: dict[str, Any], verified: dict[str, Any],
                closure: dict[str, set[str]]) -> dict[str, dict[str, Any]]:
    """Check explicit evidence bindings before considering reuse on another ref."""
    source = contracts["source"]
    if (source["commit"], source["tree"]) != (verified["source_ref"], verified["source_tree"]):
        raise ValueError("Independent evidence is pinned to different original source")
    if links["source_commit"] != source["commit"]:
        raise ValueError("Claim links reference different original source")

    modules = discovery["production_modules"]
    by_path = {d["path"]: (name, d) for name, d in modules.items()}
    specifications = {c["id"]: c for c in contracts["contracts"]}
    reports = {c["id"]: c for c in verified["with_oracles"]["cases"]}
    declarations = links["claims"]
    if len(specifications) != len(contracts["contracts"]):
        raise ValueError("Duplicate contract identifiers")
    if len(reports) != len(verified["with_oracles"]["cases"]):
        raise ValueError("Duplicate independent oracle case identifiers")
    if len({link["id"] for link in declarations}) != len(declarations):
        raise ValueError("Duplicate claim link identifiers")
    if {link["id"] for link in declarations} != set(specifications):
        raise ValueError("Claims must be explicitly linked one-to-one to source contracts")

    result = {}
    for link in declarations:
        name = link["id"]
        spec = specifications[name]
        case = reports[link["evidence_case"]]
        focus = set(link["modules"])
        if not focus or not focus <= set(modules):
            raise ValueError(f"Claim {name} has unsupported implementation modules")
        required = set().union(*(closure[m] for m in focus))
        source_paths = {modules[m]["path"] for m in required}
        if set(spec["import_closure"]) != source_paths:
            raise ValueError(f"Claim {name} declared import closure differs from source")
        implementation = spec.get("implementation")
        if implementation is not None:
            record = by_path.get(implementation)
            if record is None or record[0] not in focus or record[1]["blob_sha"] != spec["blob_sha"]:
                raise ValueError(f"Claim {name} has an incompatible implementation blob")
        result[name] = {
            "claim": name, "evidence_case": case["id"],
            "prior_evidence_status": case["status"],
            "previous_mutants_killed": case.get("semantic_mutants_killed", 0),
            "source_modules": sorted(required),
            "focus_modules": sorted(focus),
            "depends_on": sorted(set(link["depends_on"])),
            "spec_sha256": digest(spec),
            "source_blob_oids": {m: modules[m]["blob_sha"] for m in sorted(required)},
            "dynamic_closure_modules": sorted(m for m in required if modules[m].get("dynamic")),
            "unresolved_import_modules": sorted(m for m in required if modules[m].get("unresolved")),
        }
    graph = {k: set(v["depends_on"]) for k, v in result.items()}
    validate_graph(graph)
    return dict(sorted(result.items()))


def evaluate_ref(repo: Path, ref: str, basis: dict[str, dict[str, Any]],
                 discovery: dict[str, Any], original_objects: dict[str, dict]) -> dict[str, Any]:
    """Compare original claim closure blobs/modes at a real Git commit."""
    commit = git_commit(repo, ref)
    objects = git_objects(repo, commit["oid"])
    module_paths = {m: x["path"] for m, x in discovery["production_modules"].items()}

    cache: dict[str, dict[str, Any]] = {}
    visiting: set[str] = set()

    def claim_result(name: str) -> dict[str, Any]:
        if name in cache:
            return cache[name]
        if name in visiting:
            raise ValueError("Cycle in explicit contract dependencies")
        visiting.add(name)
        info = basis[name]
        changed = []
        missing = []
        for module in info["source_modules"]:
            path = module_paths[module]
            actual = objects.get(path)
            expected = original_objects[path]
            if actual is None:
                missing.append(module)
            elif actual != expected:
                changed.append({
                    "module": module, "path": path,
                    "previous_blob": expected["oid"],
                    "current_blob": actual["oid"],
                    "previous_mode": expected["mode"],
                    "current_mode": actual["mode"],
                })
        prerequisites = [claim_result(dep) for dep in info["depends_on"]]
        stale_dependencies = sorted(r["claim"] for r in prerequisites
                                    if r["status"] != "REUSE_ELIGIBLE")
        reasons = []
        if info["prior_evidence_status"] != "VERIFIED_WITHIN_SCOPE":
            reasons.append("PRIOR_ORACLE_NOT_VERIFIED")
        if info["previous_mutants_killed"] < 1:
            reasons.append("NO_MUTATION_CHALLENGE")
        if info["dynamic_closure_modules"] or info["unresolved_import_modules"]:
            reasons.append("STATIC_IMPORT_ANALYSIS_INCOMPLETE")
        if changed:
            reasons.append("SOURCE_BLOB_CHANGED")
        if missing:
            reasons.append("SOURCE_MODULE_MISSING")
        if stale_dependencies:
            reasons.append("PREREQUISITE_CLAIM_NOT_REUSABLE")
        result = {
            "claim": name, "status": "REUSE_ELIGIBLE" if not reasons else "REVERIFY_REQUIRED",
            "reasons": reasons,
            "changed_source_modules": changed,
            "missing_source_modules": missing,
            "stale_prerequisite_claims": stale_dependencies,
            "source_closure_module_count": len(info["source_modules"]),
            "source_closure_digest": digest(info["source_blob_oids"]),
            "previous_oracle_case": info["evidence_case"],
            "prior_evidence_status": info["prior_evidence_status"],
            "prior_verified_mutants": info["previous_mutants_killed"],
            "previous_spec_digest": info["spec_sha256"],
        }
        visiting.remove(name)
        cache[name] = result
        return result

    claims = [claim_result(name) for name in sorted(basis)]
    unassessed_paths = sorted(set(objects) - set(original_objects))
    return {
        "ref": ref, "commit_oid": commit["oid"], "tree_oid": commit["tree"],
        "parent_oids": commit["parents"],
        "claims": claims,
        "reuse_eligible": sum(c["status"] == "REUSE_ELIGIBLE" for c in claims),
        "reverify_required": sum(c["status"] != "REUSE_ELIGIBLE" for c in claims),
        "new_paths_outside_original_source": len(unassessed_paths),
        "scope": "original isolated-oracle source closures only; no changed whole-program integration checked",
    }


def index(repo: Path, discovery: dict, contracts: dict, links: dict, verified: dict,
          refs: list[str]) -> dict:
    """An explicitly scoped, deterministic source-identity evidence index."""
    if not refs or len(refs) != len(set(refs)):
        raise ValueError("Provide at least one unique Git ref")
    repo = repo.resolve()
    if git_text(repo, "rev-parse", "--show-object-format") != "sha1":
        raise ValueError("The pinned h11 source uses Git SHA-1; another object format requires an adapter")
    _graph, closure, _structural = module_poset(discovery)
    original = contracts["source"]
    original_objects = validate_source(repo, discovery, original["commit"], original["tree"])
    basis = claim_basis(discovery, contracts, links, verified, closure)
    return {
        "schema_version": 1,
        "original_commit": original["commit"],
        "original_tree": original["tree"],
        "discovery_sha256": digest(discovery),
        "claim_basis_sha256": digest(basis),
        "original_evidence": {
            "reported_run": verified["verification_run"]["url"],
            "full_evidence_json_sha256": verified["full_ci_evidence_sha256"],
            "note": "Prior attestation reference, not revalidated against the Actions server here",
        },
        "claim_sources": [basis[k] for k in sorted(basis)],
        "revisions": [evaluate_ref(repo, ref, basis, discovery, original_objects) for ref in refs],
        "semantics": (
            "REUSE_ELIGIBLE means pinned source closure is byte-identical, previous bounded "
            "oracle evidence exists, and explicit prerequisite claims remain eligible. "
            "It is NOT proof for a new environment, package initialization, added code, "
            "new integration behavior or an arbitrary Git merge. No oracle executed."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repository", type=Path)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--contracts", type=Path, required=True)
    p.add_argument("--links", type=Path, required=True)
    p.add_argument("--verified", type=Path, required=True)
    p.add_argument("--ref", action="append", required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = index(
        args.repository,
        json.loads(args.discovery.read_text()),
        json.loads(args.contracts.read_text()),
        json.loads(args.links.read_text()),
        json.loads(args.verified.read_text()),
        args.ref,
    )
    raw = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(raw)
    else:
        print(raw, end="")


if __name__ == "__main__":
    main()
