"""Source-only discovery of candidate executable contracts in a Python package.

Uses stdlib AST, never imports the target package and never reads hand-authored
contract specifications. Structural evidence is not a behavioral guarantee.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import re
from pathlib import Path
from typing import Any


def module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def resolve(importer: str, is_package: bool, level: int, module: str | None) -> str | None:
    if not level:
        return module
    parent = importer.split(".") if is_package else importer.split(".")[:-1]
    if level > len(parent):
        return None
    return ".".join(parent[: len(parent) - level + 1] + (module.split(".") if module else []))


def scan_imports(tree: ast.AST, name: str, is_package: bool,
                 known: set[str]) -> dict[str, list[str]]:
    runtime: set[str] = set()
    typing: set[str] = set()
    unresolved: set[str] = set()
    dynamic: set[str] = set()

    def add(target: str | None, symbols: list[str], type_only: bool) -> None:
        if target is None:
            unresolved.add("invalid-relative-import")
            return
        matched = {target} if target in known else set()
        matched.update(x for symbol in symbols
                       if (x := f"{target}.{symbol}" if target else symbol) in known)
        (typing if type_only else runtime).update(matched - {name})
        if target.split(".")[0] == name.split(".")[0] and not matched:
            unresolved.add(target + (":" + ",".join(symbols) if symbols else ""))

    def visit(node: ast.AST, type_only: bool = False) -> None:
        if isinstance(node, ast.If) and (
                isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                or isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"):
            for child in node.body:
                visit(child, True)
            for child in node.orelse:
                visit(child, type_only)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, [], type_only)
        elif isinstance(node, ast.ImportFrom):
            add(resolve(name, is_package, node.level, node.module),
                [alias.name for alias in node.names if alias.name != "*"], type_only)
        elif isinstance(node, ast.Call):
            func = node.func
            method = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            if method in {"__import__", "import_module"}:
                dynamic.add(method)
        for child in ast.iter_child_nodes(node):
            visit(child, type_only)

    visit(tree)
    return {"runtime": sorted(runtime), "typing_only": sorted(typing - runtime),
            "unresolved": sorted(unresolved), "dynamic": sorted(dynamic)}


def describe(tree: ast.Module) -> dict[str, Any]:
    classes = []
    functions = []
    uppercase_bindings = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append({"name": node.name, "line": node.lineno,
                            "methods": sorted(x.name for x in node.body
                                              if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)))})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            uppercase_bindings.extend(t.id for t in targets
                                      if isinstance(t, ast.Name) and t.id.isupper()
                                      and not t.id.startswith("_"))
    return {"classes": classes, "functions": sorted(functions),
            "uppercase_bindings": sorted(uppercase_bindings)}


def closure(node: str, graph: dict[str, set[str]]) -> set[str]:
    result = set()
    todo = [node]
    while todo:
        current = todo.pop()
        if current not in result:
            result.add(current)
            todo.extend(sorted(graph.get(current, set()) - result))
    return result


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm; cycles are an explicit unsupported decomposition."""
    ids: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    groups: list[list[str]] = []
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        ids[node] = low[node] = counter
        counter += 1
        stack.append(node)
        active.add(node)
        for dep in sorted(graph[node]):
            if dep not in ids:
                visit(dep)
                low[node] = min(low[node], low[dep])
            elif dep in active:
                low[node] = min(low[node], ids[dep])
        if low[node] == ids[node]:
            group = []
            while True:
                item = stack.pop()
                active.remove(item)
                group.append(item)
                if item == node:
                    break
            groups.append(sorted(group))

    for module in sorted(graph):
        if module not in ids:
            visit(module)
    return sorted(group for group in groups if len(group) > 1)


def class_families(a: list[dict[str, Any]],
                   b: list[dict[str, Any]]) -> list[dict[str, str]]:
    def words(name: str) -> tuple[str, ...]:
        return tuple(re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+", name))
    found = []
    for left, right in itertools.product(a, b):
        x, y = words(left["name"]), words(right["name"])
        if len(x) < 2 or len(y) < 2 or x[-1] == y[-1]:
            continue
        shared = []
        for i, j in zip(x[:-1], y[:-1]):
            if i != j:
                break
            shared.append(i)
        if shared:
            found.append({"stem": "".join(shared),
                          "left": left["name"], "right": right["name"]})
    return sorted(found, key=lambda p: (p["stem"], p["left"], p["right"]))


def discover(root: Path, package: str, test_roots: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    package_dir = root / package.replace(".", "/")
    if not package_dir.is_dir():
        raise ValueError(f"Expected package directory: {package_dir}")
    sources = {module_name(p, root): p for p in sorted(package_dir.rglob("*.py"))
               if "tests" not in p.relative_to(package_dir).parts}
    if package not in sources:
        raise ValueError(f"Missing package __init__.py: {package_dir}")

    if test_roots is None:
        test_roots = [f"{package.replace('.', '/')}/tests", "tests"]
    tests = {module_name(p, root): p
             for folder in test_roots if (root / folder).is_dir()
             for p in sorted((root / folder).rglob("*.py"))}
    if set(sources) & set(tests):
        raise ValueError(f"Overlapping modules: {sorted(set(sources) & set(tests))}")
    all_files = {**sources, **tests}
    known = set(all_files)
    details = {}
    for name, path in sorted(all_files.items()):
        data = path.read_bytes()
        tree = ast.parse(data, filename=str(path))
        details[name] = {
            "path": path.relative_to(root).as_posix(), "blob_sha": blob_sha(data),
            "loc": len(data.splitlines()),
            **scan_imports(tree, name, path.stem == "__init__", known),
            **describe(tree),
        }
    graph = {m: set(details[m]["runtime"]) & set(sources) for m in sources}
    closures = {m: closure(m, graph) for m in sources}
    candidates = []
    for join in sorted(graph):
        for left, right in itertools.combinations(sorted(graph[join]), 2):
            if left in closures[right] or right in closures[left]:
                continue
            a, b = closures[left], closures[right]
            shared = sorted((a & b) - {left, right})
            families = class_families(details[left]["classes"], details[right]["classes"])
            if not (shared or families):
                continue
            score = 5 * len(families) + 2 * len(shared)
            score += int(bool(details[left]["uppercase_bindings"]))
            score += int(bool(details[right]["uppercase_bindings"]))
            candidates.append({
                "join": join, "left": left, "right": right,
                "rank_score": score, "shared_dependencies": shared,
                "left_only": sorted(a - b), "right_only": sorted(b - a),
                "matched_class_families": families,
                "status": "candidate; semantic guarantees not inferred",
            })
    candidates.sort(key=lambda p: (-p["rank_score"], p["join"], p["left"], p["right"]))

    helper_deps = {name: set(details[name]["runtime"]) for name in tests}
    test_results = []
    for name in sorted(tests):
        if not tests[name].name.startswith("test_"):
            continue
        seen = set()
        todo = [name]
        while todo:
            cur = todo.pop()
            if cur in seen:
                continue
            seen.add(cur)
            todo.extend(sorted(helper_deps.get(cur, set()) & set(tests)))
        direct = set().union(*(helper_deps.get(m, set()) for m in seen)) & set(sources)
        target_token = name.rsplit(".", 1)[-1]
        possible = package + "._" + target_token[5:] if target_token.startswith("test_") else None
        target = possible if possible in sources else None
        target_deps = closures.get(target, set())
        expanded = set().union(*(closures[m] for m in direct))
        test_results.append({
            "test_module": name, "path": details[name]["path"],
            "direct_production_imports": sorted(direct),
            "expanded_production_import_closure": sorted(expanded),
            "name_matched_target": target,
            "imports_not_required_by_named_target": sorted(direct - target_deps) if target else [],
            "depends_on_test_helpers": sorted(seen - {name}),
        })
    for module in sources:
        details[module]["runtime_closure"] = sorted(closures[module])
    return {
        "schema_version": 1, "package": package,
        "production_modules": {m: details[m] for m in sorted(sources)},
        "runtime_import_cycles": cycles(graph),
        "independent_sibling_candidates": candidates,
        "tests": test_results,
        "caveats": [
            "Static imports do not establish semantic contracts or correctness.",
            "Dynamic and conditional imports may require runtime inspection.",
            "Importing package submodules can execute __init__.py, even when not in a module closure.",
            "Test imports alone do not prove which behavior a test exercises.",
            "Candidate scores rank navigational hypotheses, not architectural truth.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--tests", action="append", default=None,
                        help="Relative test directory (repeatable)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = discover(args.repository, args.package, args.tests)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
