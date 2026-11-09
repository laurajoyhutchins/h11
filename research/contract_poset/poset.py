"""Map static Python module dependencies and explicit claims to existing Git objects.

No synthetic commits, tree rewrites, source mutations, or package imports.
Structural import dependencies and independently evidenced semantic claims stay
in *separate posets*. Git tree/commit object identities are checked, not inferred.

The set of downward-closed subsets of a finite poset is a distributive lattice.
A Git commit's parents express history, not necessarily semantic prerequisites.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if p.returncode:
        raise ValueError(f"git {args!r} failed: {p.stderr.decode(errors='replace')[:800]}")
    return p.stdout


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode().strip()


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git_objects(repo: Path, revision: str) -> dict[str, dict[str, str]]:
    """Inspect a *real*, existing Git tree; never synthesize object IDs."""
    result: dict[str, dict[str, str]] = {}
    for item in git(repo, "ls-tree", "-rz", revision).split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if path in result:
            raise ValueError(f"Duplicate Git path: {path}")
        result[path] = {"mode": mode, "kind": kind, "oid": oid}
    return result


def git_commit(repo: Path, revision: str) -> dict[str, Any]:
    oid = git_text(repo, "rev-parse", revision + "^{commit}")
    data = git(repo, "cat-file", "-p", oid).split(b"\n\n", 1)[0]
    lines = data.decode("utf-8", errors="replace").splitlines()
    tree = [x[5:] for x in lines if x.startswith("tree ")]
    parents = [x[7:] for x in lines if x.startswith("parent ")]
    if len(tree) != 1:
        raise ValueError(f"Invalid Git commit tree: {oid}")
    return {"oid": oid, "tree": tree[0], "parents": parents}


def graph_closure(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        x = todo.pop()
        if x not in seen:
            seen.add(x)
            todo.extend(sorted(graph[x] - seen))
    return seen


def validate_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    names = set(graph)
    if any(not deps <= names for deps in graph.values()):
        raise ValueError("Graph contains unknown prerequisite nodes")
    transitive: dict[str, set[str]] = {}
    for name in sorted(graph):
        reachable = graph_closure(graph, name)
        if name in set().union(*(graph_closure(graph, dep) for dep in graph[name])):
            raise ValueError("Cycle in dependency graph: " + name)
        transitive[name] = reachable
    return transitive


def covers(graph: dict[str, set[str]], closure: dict[str, set[str]]) -> list[dict[str, str]]:
    edges = []
    for name in sorted(graph):
        for dependency in sorted(graph[name]):
            other = graph[name] - {dependency}
            if not any(dependency in closure[x] for x in other):
                edges.append({"prerequisite": dependency, "dependent": name})
    return edges


def is_ideal(nodes: set[str], closure: dict[str, set[str]]) -> bool:
    return nodes <= closure.keys() and all(closure[x] <= nodes for x in nodes)


def frontier(nodes: set[str], closure: dict[str, set[str]]) -> list[str]:
    if not is_ideal(nodes, closure):
        raise ValueError("Not a downward-closed set")
    return sorted(x for x in nodes if not any(x != y and x in closure[y] for y in nodes))


def from_frontier(maximal: list[str], closure: dict[str, set[str]]) -> set[str]:
    return set().union(*(closure[x] for x in maximal)) if maximal else set()


def ideal_count(closure: dict[str, set[str]], max_nodes: int = 18) -> int | None:
    """Exact for small DAGs; never extrapolate or pretend truncated counts are exact."""
    names = sorted(closure)
    if len(names) > max_nodes:
        return None
    count = 0
    for length in range(len(names) + 1):
        for subset in itertools.combinations(names, length):
            if is_ideal(set(subset), closure):
                count += 1
    return count


def module_poset(discovery: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict]:
    if discovery.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported source discovery schema")
    source = discovery["production_modules"]
    graph = {
        name: set(data["runtime"]) & source.keys()
        for name, data in source.items()
    }
    closure = validate_graph(graph)
    for name, data in source.items():
        recorded = set(data["runtime_closure"])
        if recorded != closure[name]:
            raise ValueError(f"Discovery runtime closure inconsistent: {name}")
    return graph, closure, {
        "nodes": [
            {"id": name, "path": data["path"], "source_blob_oid": data["blob_sha"],
             "runtime_direct_deps": sorted(graph[name]),
             "dynamic_imports": data.get("dynamic", []),
             "unresolved_imports": data.get("unresolved", [])}
            for name, data in sorted(source.items())
        ],
        "cover_edges": covers(graph, closure),
        "number_of_order_ideals": ideal_count(closure),
        "count_exact": len(source) <= 18,
    }


def validate_source(repo: Path, discovery: dict[str, Any], expected_commit: str,
                    expected_tree: str) -> dict[str, dict[str, str]]:
    if git_text(repo, "rev-parse", expected_commit + "^{tree}") != expected_tree:
        raise ValueError("Source Git tree mismatch")
    source_objects = git_objects(repo, expected_commit)
    for module, data in discovery["production_modules"].items():
        path = data["path"]
        info = source_objects.get(path)
        if not info or info["kind"] != "blob" or info["oid"] != data["blob_sha"]:
            raise ValueError(f"Discovery object not found in pinned source Git tree: {module}")
    return source_objects


def check_stages(repo: Path, stages: dict, source: dict[str, Any],
                 source_objects: dict[str, dict[str, str]],
                 closure: dict[str, set[str]]) -> list[dict[str, Any]]:
    if stages["source_commit"] != source["commit"] or stages["source_tree"] != source["tree"]:
        raise ValueError("Stage ledger references a different original source")
    records: list[dict[str, Any]] = []
    module_paths = {x["path"]: name for name, x in source["discovery"]["production_modules"].items()}
    by_id: dict[str, dict[str, Any]] = {}
    for name, description in stages["nodes"].items():
        actual = git_commit(repo, description["sha"])
        if actual["tree"] != description["tree"] or actual["parents"] != description["parents"]:
            raise ValueError(f"Git commit does not match stage ledger: {name}")
        objects = git_objects(repo, actual["oid"])
        changed = sorted(path for path, spec in objects.items()
                         if path not in source_objects or spec != source_objects[path])
        if changed:
            raise ValueError(f"Stage contains bytes absent from pinned original: {name}: {changed[:5]}")
        present = {module_paths[path] for path in objects if path in module_paths}
        if not is_ideal(present, closure):
            missing = sorted(set().union(*(closure[m] for m in present)) - present)
            raise ValueError(f"Not a dependency-closed Git stage: {name}; missing={missing}")
        known_parents = [by_id[other] for other, x in stages["nodes"].items()
                         if x["sha"] in actual["parents"] and other in by_id]
        expected_stage_parents = [name_by_sha for name_by_sha in
                                  (next((n for n, s in stages["nodes"].items()
                                         if s["sha"] == oid), None) for oid in actual["parents"])
                                  if name_by_sha is not None]
        if len(expected_stage_parents) != len(known_parents):
            raise ValueError(f"Stage parent not evaluated before child: {name}")
        parents_union = set().union(*(set(p["modules"]) for p in known_parents))
        if not parents_union <= present:
            raise ValueError(f"Git stage lost previously assembled modules: {name}")
        record = {
            "stage": name, "commit_oid": actual["oid"], "tree_oid": actual["tree"],
            "actual_git_parent_oids": actual["parents"],
            "stage_parent_names": expected_stage_parents,
            "external_original_commit_anchor": source["commit"] in actual["parents"],
            "modules": sorted(present),
            "new_modules_vs_stage_parents": sorted(present - parents_union),
            "maximal_frontier": frontier(present, closure),
            "ideal_id": digest(sorted([source["discovery"]["production_modules"][m]["blob_sha"]
                                      + ":" + m for m in present])),
            "original_blobs_present": len(objects),
            "all_git_paths_are_original_exact_blobs": True,
            "downward_closed_imports": True,
        }
        if len(known_parents) >= 2:
            record["merge_source_union_equals_child_modules"] = parents_union == present
            record["merge_join_of_module_ideals"] = sorted(parents_union)
            record["merge_meet_of_module_ideals"] = sorted(
                set.intersection(*(set(p["modules"]) for p in known_parents)))
        if from_frontier(record["maximal_frontier"], closure) != present:
            raise ValueError("Antichain frontier does not recover state")
        by_id[name] = record
        records.append(record)
    return records


def project_existing_refs(repo: Path, refs: list[str], discovery: dict,
                          source_objects: dict[str, dict[str, str]],
                          closure: dict[str, set[str]], source_tree: str) -> list[dict]:
    """Project arbitrary existing Git commit snapshots onto the pinned module basis.

    Added unrelated files are allowed. Changed *source module* blobs are
    incompatible with this pinned version, not silently treated as absence.
    """
    if len(set(refs)) != len(refs):
        raise ValueError("Snapshot references must be unique")
    module_paths = {x["path"]: name for name, x in discovery["production_modules"].items()}
    projected = []
    for ref in refs:
        commit = git_commit(repo, ref)
        objects = git_objects(repo, commit["oid"])
        missing = sorted(module_paths[path] for path in module_paths if path not in objects)
        changed = sorted(module_paths[path] for path in module_paths
                         if path in objects and objects[path] != source_objects[path])
        if changed:
            projected.append({
                "ref": ref, "commit_oid": commit["oid"], "tree_oid": commit["tree"],
                "parent_commit_oids": commit["parents"], "status": "INCOMPATIBLE_SOURCE_VERSION",
                "changed_original_modules": changed,
                "message": "Cannot project changed source module blobs onto pinned module basis",
            })
            continue
        present = set(discovery["production_modules"]) - set(missing)
        if not is_ideal(present, closure):
            missing_deps = sorted(set().union(*(closure[x] for x in present)) - present)
            projected.append({
                "ref": ref, "commit_oid": commit["oid"], "tree_oid": commit["tree"],
                "parent_commit_oids": commit["parents"], "status": "NOT_DEPENDENCY_CLOSED",
                "missing_original_modules": missing,
                "missing_prerequisites": missing_deps,
            })
            continue
        extra = sorted(set(objects) - set(source_objects))
        projected.append({
            "ref": ref, "commit_oid": commit["oid"], "tree_oid": commit["tree"],
            "parent_commit_oids": commit["parents"], "status": "PINNED_MODULE_IDEAL",
            "modules": sorted(present),
            "frontier": frontier(present, closure),
            "ideal_id": digest(sorted(discovery["production_modules"][m]["blob_sha"] + ":" + m
                                      for m in present)),
            "same_tree_as_source": commit["tree"] == source_tree,
            "additional_paths_beyond_pinned_source": len(extra),
            "missing_original_modules": missing,
            "is_complete_original_module_set": len(present) == len(module_paths),
            "note": "No semantic correctness claim; exact Git source-module blob identity only",
        })
    return projected


def attach_contracts(contracts: dict, links: dict, verified: dict,
                     module_closure: dict[str, set[str]],
                     stages: list[dict[str, Any]], discovery: dict) -> dict[str, Any]:
    """Explicit, existing evidence only. No semantic implications are inferred."""
    pins = (contracts["source"]["commit"], contracts["source"]["tree"])
    if pins != (verified["source_ref"], verified["source_tree"]):
        raise ValueError("Independent evidence references wrong source")
    if links.get("source_commit") != pins[0]:
        raise ValueError("Explicit contract links reference wrong source")
    by_contract = {c["id"]: c for c in contracts["contracts"]}
    by_verified = {x["id"]: x for x in verified["with_oracles"]["cases"]}
    by_stage = {s["stage"]: s for s in stages}
    graph: dict[str, set[str]] = {}
    definitions: dict[str, dict[str, Any]] = {}
    for link in links["claims"]:
        name = link["id"]
        if name in graph or name not in by_contract:
            raise ValueError("Duplicate or unrecognized independent claim: " + name)
        spec = by_contract[name]
        evidence = by_verified[link["evidence_case"]]
        required_modules = set(link["modules"])
        if not required_modules or not required_modules <= set(module_closure):
            raise ValueError("Contract modules absent from source poset: " + name)
        source_by_path = {d["path"]: (module, d)
                          for module, d in discovery["production_modules"].items()}
        implementation = spec.get("implementation")
        if implementation is not None:
            matching = source_by_path.get(implementation)
            if matching is None or matching[0] not in required_modules:
                raise ValueError("Contract implementation is not bound to its source module: " + name)
            if spec.get("blob_sha") != matching[1]["blob_sha"]:
                raise ValueError("Contract implementation blob SHA differs from pinned source: " + name)
        expected_paths = set(spec.get("import_closure", []))
        actual_paths = {discovery["production_modules"][m]["path"]
                        for module in required_modules for m in module_closure[m]}
        if expected_paths and expected_paths != actual_paths:
            raise ValueError("Contract source import closure differs from independently declared specification: " + name)
        stage = by_stage[spec["introduced_at"]]
        if not required_modules <= set(stage["modules"]):
            raise ValueError("Contract introduced before source closure exists: " + name)
        for module in required_modules:
            if not module_closure[module] <= set(stage["modules"]):
                raise ValueError("Contract stage lacks source dependencies: " + name)
        graph[name] = set(link["depends_on"])
        definitions[name] = {
            "id": name, "spec_sha256": digest(spec), "claim_id": name,
            "implementation_modules": sorted(required_modules),
            "structural_module_closure": sorted(
                set().union(*(module_closure[m] for m in required_modules))),
            "introduced_at_stage": spec["introduced_at"],
            "declared_claim_dependencies": sorted(graph[name]),
            "evidence_case": link["evidence_case"],
            "reported_status": evidence["status"],
            "reported_mutants_killed": evidence["semantic_mutants_killed"],
            "verification_run": verified["verification_run"]["url"],
            "evidence_source": "previous independently executed oracle run; not reexecuted in poset mapping",
        }
    closure = validate_graph(graph)
    for claim, reqs in graph.items():
        intro = by_stage[definitions[claim]["introduced_at_stage"]]
        # Stage ancestry determines whether a declared prerequisite is present,
        # but cannot establish its semantic implication.
        ancestor_stages: set[str] = set()
        def trace(stage_name: str) -> None:
            if stage_name in ancestor_stages:
                return
            ancestor_stages.add(stage_name)
            for parent in by_stage[stage_name]["stage_parent_names"]:
                trace(parent)
        trace(intro["stage"])
        for required in reqs:
            if definitions[required]["introduced_at_stage"] not in ancestor_stages:
                raise ValueError("Explicit claim requirement absent from declared stage ancestry")
    stage_claims = {}
    for stage in stages:
        available_stages: set[str] = set()
        def reach(name: str) -> None:
            if name in available_stages:
                return
            available_stages.add(name)
            for parent in by_stage[name]["stage_parent_names"]:
                reach(parent)
        reach(stage["stage"])
        present = {name for name, d in definitions.items()
                   if d["introduced_at_stage"] in available_stages}
        if not is_ideal(present, closure):
            raise ValueError("Claim set in existing Git stage is not dependency closed")
        stage_claims[stage["stage"]] = {
            "claims_present_by_explicit_links": sorted(present),
            "semantic_claim_frontier": frontier(present, closure),
        }
    return {
        "claims": [definitions[k] for k in sorted(definitions)],
        "claim_cover_edges": covers(graph, closure),
        "number_of_claim_order_ideals": ideal_count(closure),
        "stage_claim_projection": stage_claims,
        "evidence_scope": "finite independent oracle/mutant challenges reported in earlier CI",
        "note": "Claims are manually bound to evidence; their dependencies are explicit assertions, not derived from Git parents.",
    }


def build(repo: Path, discovery: dict, stage_ledger: dict,
          contracts: dict | None = None, links: dict | None = None,
          verified: dict | None = None, refs: list[str] | None = None) -> dict:
    repo = repo.resolve()
    graph, closure, structural = module_poset(discovery)
    source_commit = stage_ledger["source_commit"]
    source_tree = stage_ledger["source_tree"]
    source_objects = validate_source(repo, discovery, source_commit, source_tree)
    source = {"commit": source_commit, "tree": source_tree, "discovery": discovery}
    stages = check_stages(repo, stage_ledger, source, source_objects, closure)
    result: dict[str, Any] = {
        "schema_version": 1,
        "source": {"commit": source_commit, "tree": source_tree,
                   "object_format": git_text(repo, "rev-parse", "--show-object-format"),
                   "original_git_paths": len(source_objects)},
        "structural_module_poset": structural,
        "existing_git_stage_projection": stages,
        "source_discovery_sha256": digest(discovery),
        "not_equated": [
            "Git commit ancestry != semantic dependency",
            "Module import prerequisite != behavioral implication",
            "Union of valid source-module ideals != conflict-free code merge",
            "Independent oracle evidence != proof for all possible inputs",
            "The first generated Git stage descends from the complete original commit, so Git ancestry is not monotone in source-module content",
        ],
        "method": "read-only existing Git object inspection + finite structural ideal lattice",
    }
    if refs:
        result["existing_git_refs"] = project_existing_refs(
            repo, refs, discovery, source_objects, closure, source_tree)
    supplied = [contracts is not None, links is not None, verified is not None]
    if any(supplied) and not all(supplied):
        raise ValueError("Provide contracts, explicit links and verified summary together")
    if all(supplied):
        assert contracts is not None and links is not None and verified is not None
        result["explicit_semantic_claim_poset"] = attach_contracts(
            contracts, links, verified, closure, stages, discovery)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repository", type=Path)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--stages", type=Path, required=True)
    p.add_argument("--contracts", type=Path)
    p.add_argument("--links", type=Path)
    p.add_argument("--verified", type=Path)
    p.add_argument("--ref", action="append", default=[],
                   help="Existing Git commit/ref to project onto pinned module ideals (repeatable)")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = build(args.repository,
                   json.loads(args.discovery.read_text()),
                   json.loads(args.stages.read_text()),
                   json.loads(args.contracts.read_text()) if args.contracts else None,
                   json.loads(args.links.read_text()) if args.links else None,
                   json.loads(args.verified.read_text()) if args.verified else None,
                   args.ref)
    raw = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(raw)
    else:
        print(raw, end="")


if __name__ == "__main__":
    main()
