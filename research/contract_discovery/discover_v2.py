"""Second-generation source-only candidate discovery.

Extends the unchanged sibling-pair heuristic with two generic candidate
families: test-import-observed runtime module closures and statically
resolved class inheritance boundaries.

This script neither imports the target package nor runs its code. No
behavioral specification is inferred from names or test imports.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import json
from pathlib import Path
from typing import Any

from discover import discover, resolve


def class_catalog(production: dict[str, Any]) -> dict[str, set[str]]:
    return {name: {c["name"] for c in data["classes"]} for name, data in production.items()}


def bindings(tree: ast.Module, module: str, is_package: bool,
             classes: dict[str, set[str]]) -> dict[str, tuple[str, str]]:
    """Map imported local symbols to their declared source modules/classes."""
    imports: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                if target in classes:
                    bound = alias.asname or target.partition(".")[0]
                    imports[bound] = ("module", target if alias.asname else target.partition(".")[0])
        elif isinstance(node, ast.ImportFrom):
            parent = resolve(module, is_package, node.level, node.module)
            if parent is None:
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                submodule = f"{parent}.{alias.name}" if parent else alias.name
                if submodule in classes:
                    imports[bound] = ("module", submodule)
                elif parent in classes and alias.name in classes[parent]:
                    imports[bound] = ("class", f"{parent}.{alias.name}")
    return imports


def resolve_base(base: ast.expr, module: str, catalog: dict[str, set[str]],
                 imports: dict[str, tuple[str, str]]) -> tuple[str | None, str]:
    """Class-qualified reference, or a conservative unresolved reason."""
    if isinstance(base, ast.Subscript):
        return resolve_base(base.value, module, catalog, imports)
    if isinstance(base, ast.Name):
        if base.id in catalog[module]:
            return f"{module}.{base.id}", "local"
        entry = imports.get(base.id)
        if entry and entry[0] == "class":
            return entry[1], "explicit-import"
        if base.id in vars(builtins):
            return None, "builtin"
        return None, "unknown-or-external"
    if isinstance(base, ast.Attribute):
        expression = ast.unparse(base)
        names = expression.split(".")
        if len(names) > 1:
            direct_module = ".".join(names[:-1])
            if names[-1] in catalog.get(direct_module, set()):
                return f"{direct_module}.{names[-1]}", "qualified"
            head = imports.get(names[0])
            if head and head[0] == "module":
                target_module = ".".join([head[1], *names[1:-1]])
                if names[-1] in catalog.get(target_module, set()):
                    return f"{target_module}.{names[-1]}", "module-alias"
        return None, "unresolved-attribute"
    return None, "dynamic-base-expression"


def extension_boundaries(root: Path, production: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    catalog = class_catalog(production)
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for name, data in sorted(production.items()):
        path = root / data["path"]
        source = ast.parse(path.read_bytes(), filename=str(path))
        imports = bindings(source, name, path.name == "__init__.py", catalog)
        for node in source.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                qname, resolution = resolve_base(base, name, catalog, imports)
                if qname is None:
                    if resolution not in {"builtin", "unknown-or-external"}:
                        unresolved.append({"module": name, "class": node.name,
                                           "base_expression": ast.unparse(base), "reason": resolution})
                    continue
                base_module, _, base_class = qname.rpartition(".")
                if not base_module or base_class not in catalog.get(base_module, set()):
                    unresolved.append({"module": name, "class": node.name,
                                       "base_expression": ast.unparse(base), "reason": "ambiguous-target"})
                    continue
                derived = f"{name}.{node.name}"
                if qname == derived:
                    unresolved.append({"module": name, "class": node.name,
                                       "base_expression": ast.unparse(base), "reason": "self-inheritance"})
                    continue
                edges.append({
                    "kind": "extension_boundary",
                    "id": f"extension|{qname}|{derived}",
                    "base": qname, "derived": derived,
                    "base_module": base_module, "derived_module": name,
                    "scope": "cross-module" if base_module != name else "intra-module",
                    "resolution": resolution,
                    "base_runtime_closure": production[base_module]["runtime_closure"],
                    "derived_runtime_closure": data["runtime_closure"],
                    "status": "CANDIDATE_ONLY",
                    "evidence": "statically resolved class inheritance; no behavioral guarantee",
                })
    edges.sort(key=lambda e: (e["base"], e["derived"]))
    unresolved.sort(key=lambda e: (e["module"], e["class"], e["base_expression"]))
    return edges, unresolved


def test_exercised_modules(discovery: dict[str, Any]) -> tuple[list[dict], list[str]]:
    production = discovery["production_modules"]
    package = discovery["package"]
    reverse: dict[str, list[str]] = {}
    facade_only: list[str] = []
    for entry in discovery["tests"]:
        imported = set(entry["direct_production_imports"])
        internal = sorted(imported & production.keys() - {package})
        if package in imported and not internal:
            facade_only.append(entry["test_module"])
        for module in internal:
            reverse.setdefault(module, []).append(entry["test_module"])
    results = []
    for module, tests in sorted(reverse.items()):
        results.append({
            "kind": "test_exercised_module_closure",
            "id": f"test-module|{module}",
            "module": module,
            "source_path": production[module]["path"],
            "runtime_closure": production[module]["runtime_closure"],
            "supporting_test_modules": sorted(set(tests)),
            "status": "CANDIDATE_ONLY",
            "evidence": "test module imports source module; import does not establish exercised behavior",
        })
    return results, sorted(set(facade_only))


def discover_v2(root: Path, package: str, tests: list[str] | None = None,
                source_dir: str = ".") -> dict[str, Any]:
    root = root.resolve()
    base = discover(root, package, tests, source_dir)
    production = base["production_modules"]
    tested, facade_only = test_exercised_modules(base)
    extensions, unresolved = extension_boundaries(root, production)
    base.update({
        "schema_version": 2,
        "test_exercised_module_candidates": tested,
        "extension_boundary_candidates": extensions,
        "unresolved_class_bases": unresolved,
        "facade_only_test_modules": facade_only,
        "candidate_counts": {
            "independent_siblings": len(base["independent_sibling_candidates"]),
            "test_exercised_modules": len(tested),
            "extension_boundaries": len(extensions),
            "unresolved_bases": len(unresolved),
            "facade_only_test_modules": len(facade_only),
        },
        "v2_caveats": [
            "Test-import-observed closure is not proof the test executes the module's behavior.",
            "Inheritance is a structural relation, not evidence of behavioral subtyping.",
            "External, dynamic and ambiguous inheritance may not be resolved.",
            "Only top-level class declarations and top-level explicit imports are inspected.",
            "No independent behavioral oracle is generated from source or names.",
        ],
    })
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--tests", action="append", default=None)
    parser.add_argument("--source-dir", default=".")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = discover_v2(args.repository, args.package, args.tests, args.source_dir)
    value = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(value)
    else:
        print(value, end="")


if __name__ == "__main__":
    main()
