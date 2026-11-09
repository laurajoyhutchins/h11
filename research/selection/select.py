"""Prioritize source-derived contract candidates without claiming verification.

Inputs: schema-v2 discover_v2() JSON only. Does not read source files,
import target code, generate behavioral specifications, or run tests.

Scoring and greedy budget are frozen in research/selection/jinja_preregistration.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILIES = (
    "independent_sibling_pair",
    "test_exercised_module_closure",
    "extension_boundary",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def family_of(candidate: dict[str, Any]) -> str:
    kind = candidate.get("kind", "independent_sibling_pair")
    if kind not in FAMILIES:
        raise ValueError(f"Unknown candidate family: {kind!r}")
    return kind


def candidate_id(candidate: dict[str, Any]) -> str:
    kind = family_of(candidate)
    if kind == "independent_sibling_pair":
        left, right = sorted([candidate["left"], candidate["right"]])
        return f"{candidate['join']}|{left}|{right}"
    return candidate["id"]


def focus_of(candidate: dict[str, Any]) -> tuple[str, ...]:
    kind = family_of(candidate)
    if kind == "independent_sibling_pair":
        focus = [candidate["left"], candidate["right"]]
    elif kind == "test_exercised_module_closure":
        focus = [candidate["module"]]
    else:
        focus = [candidate["base_module"], candidate["derived_module"]]
    return tuple(sorted(set(focus)))


def family_points(candidate: dict[str, Any]) -> int:
    kind = family_of(candidate)
    if kind == "independent_sibling_pair":
        return 4
    if kind == "test_exercised_module_closure":
        return 2
    return 3 if candidate["scope"] == "cross-module" else 1


def sources_from_discovery(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *discovery["independent_sibling_candidates"],
        *discovery["test_exercised_module_candidates"],
        *discovery["extension_boundary_candidates"],
    ]


def base_candidate(candidate: dict[str, Any],
                   discovery: dict[str, Any]) -> dict[str, Any]:
    production = discovery["production_modules"]
    focus = focus_of(candidate)
    if not focus or not set(focus) <= production.keys():
        raise ValueError(f"Candidate has invalid source modules: {candidate_id(candidate)}")
    closures = [production[m]["runtime_closure"] for m in focus]
    closure = set().union(*[set(v) for v in closures])
    if not closure <= production.keys():
        raise ValueError(f"Unknown import-closure dependency in {candidate_id(candidate)}")
    # import relationships are evidence of structural exposure, not that test bodies
    # exercise the referenced behavior.
    tests = sorted({
        test["test_module"]
        for test in discovery["tests"]
        if set(test["direct_production_imports"]) & set(focus)
    })
    downstream = sorted(
        module for module, info in production.items()
        if module not in focus and set(info["runtime_closure"]) & set(focus)
    )
    loc = sum(int(production[m]["loc"]) for m in focus)
    if loc < 0:
        raise ValueError("Negative module lines of code")
    dynamic = sorted(m for m in closure if production[m].get("dynamic"))
    score_parts = {
        "test_import_points": 3 * min(len(tests), 4),
        "downstream_points": 2 * min(len(downstream), 4),
        "source_size_points": min(4, (loc + 119) // 120),
        "family_points": family_points(candidate),
        "closure_cost_penalty": min(3, max(0, len(closure) - 4) // 4),
        "dynamic_import_penalty": 4 if dynamic else 0,
    }
    score = sum(v if not k.endswith("penalty") else -v for k, v in score_parts.items())
    return {
        "id": candidate_id(candidate),
        "family": family_of(candidate),
        "focus_modules": list(focus),
        "source_blobs": {m: production[m]["blob_sha"] for m in focus},
        "test_import_witnesses": tests,
        "downstream_module_witnesses": downstream,
        "runtime_import_closure": sorted(closure),
        "dynamic_import_modules": dynamic,
        "focus_module_lines": loc,
        "base_score": score,
        "base_score_parts": score_parts,
        "test_evidence": "DIRECT_STATIC_IMPORT" if tests else "NO_DIRECT_TEST_IMPORT",
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": "Structural priority candidate; no independent behavioral oracle was evaluated",
    }


def select(discovery: dict[str, Any], budget: int = 3) -> dict[str, Any]:
    if discovery.get("schema_version") != 2:
        raise ValueError("Selection requires schema-v2 source discovery")
    if not isinstance(budget, int) or not 0 <= budget <= 30:
        raise ValueError("Budget must be an integer between 0 and 30")
    production = discovery["production_modules"]
    if not isinstance(production, dict) or not production:
        raise ValueError("No production modules in discovery")
    all_cases = [base_candidate(candidate, discovery)
                 for candidate in sources_from_discovery(discovery)]
    ids = [case["id"] for case in all_cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate candidate identities")
    all_cases.sort(key=lambda x: x["id"])
    remaining = {case["id"]: case for case in all_cases}
    covered: set[str] = set()
    families: set[str] = set()
    selected: list[dict[str, Any]] = []
    suppressed: dict[str, str] = {}

    for number in range(min(budget, len(remaining))):
        options = []
        for case in remaining.values():
            uncovered = len(set(case["focus_modules"]) - covered)
            diversity = 2 if case["family"] not in families else 0
            novelty = 2 * min(3, uncovered)
            score = case["base_score"] + diversity + novelty
            options.append((score, case["id"], novelty, diversity, case))
        if not options:
            break
        # Descending score, then canonical string ID ascending.
        options.sort(key=lambda p: (-p[0], p[1]))
        score, ident, novelty, diversity, winner = options[0]
        entry = {
            **winner,
            "selection_rank": number + 1,
            "greedy_score": score,
            "novelty_points": novelty,
            "new_family_points": diversity,
            "covered_modules_before": sorted(covered),
        }
        selected.append(entry)
        focus = tuple(winner["focus_modules"])
        for key, candidate in list(remaining.items()):
            if tuple(candidate["focus_modules"]) == focus:
                del remaining[key]
                if key != ident:
                    suppressed[key] = ident
        covered.update(winner["focus_modules"])
        families.add(winner["family"])
    return {
        "schema_version": 1,
        "method": "frozen greedy ranking of discover_v2 structural candidates",
        "discovery_sha256": hashlib.sha256(canonical(discovery)).hexdigest(),
        "package": discovery["package"],
        "source_snapshot": {m: production[m]["blob_sha"] for m in sorted(production)},
        "requested_budget": budget,
        "selected": selected,
        "all_candidates": all_cases,
        "suppressed_equivalent_focus": dict(sorted(suppressed.items())),
        "unselected_candidate_count": len(all_cases) - len(selected),
        "interpretation": ("Priority is a heuristic for allocating independent verification effort. "
                           "No contract oracle or mutation test was executed, therefore every candidate "
                           "remains INSUFFICIENT_EVIDENCE."),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--discovery", required=True, type=Path)
    p.add_argument("--budget", type=int, default=3)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = select(json.loads(args.discovery.read_text()), args.budget)
    raw = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(raw, end="")
    else:
        args.output.write_text(raw)


if __name__ == "__main__":
    main()
