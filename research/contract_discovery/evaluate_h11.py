"""Held-out h11 acceptance checks. These names are not inputs to discover()."""
from __future__ import annotations

import json
import sys
from pathlib import Path

result = json.loads(Path(sys.argv[1]).read_text())
modules = result["production_modules"]
assert len(modules) == 11, len(modules)
assert result["runtime_import_cycles"] == [], result["runtime_import_cycles"]

# The highest-scoring independent pair must be the two codec modules;
# neither imports the other, and the join imports both at runtime.
pair = result["independent_sibling_candidates"][0]
assert pair["join"] == "h11._connection", pair
assert {pair["left"], pair["right"]} == {"h11._readers", "h11._writers"}, pair
assert set(pair["shared_dependencies"]) >= {
    "h11._events", "h11._headers", "h11._state", "h11._util",
}, pair
assert {x["stem"] for x in pair["matched_class_families"]} >= {
    "Chunked", "ContentLength", "Http10",
}, pair

# Independent code imports are not enough; original tests have cross-module
# requirements that the production _headers module does not.
headers = modules["h11._headers"]
assert "h11._events" in headers["typing_only"]
assert "h11._events" not in headers["runtime"]
tests = {test["test_module"]: test for test in result["tests"]}
h = tests["h11.tests.test_headers"]
assert "h11._headers" in h["direct_production_imports"], h
assert "h11._events" in h["imports_not_required_by_named_target"], h
io = tests["h11.tests.test_io"]
assert {"h11._readers", "h11._writers"} <= set(io["direct_production_imports"]), io

# Candidates remain unverified hypotheses, without invented semantics.
assert pair["status"] == "candidate; semantic guarantees not inferred"
assert all("guarantees" not in c for c in result["independent_sibling_candidates"])

report = {
    "source": "Pinned original h11 Git tree",
    "modules": len(modules),
    "test_files": len(result["tests"]),
    "candidate_pairs": len(result["independent_sibling_candidates"]),
    "top_pair": {"join": pair["join"], "members": [pair["left"], pair["right"]]},
    "paired_class_families": [x["stem"] for x in pair["matched_class_families"]],
    "separate_test_dependency": "test_headers imports _events, absent from _headers runtime closure",
    "status": "PASS",
}
print(json.dumps(report, sort_keys=True, indent=2))
