"""Pure, source-independent tests for the preregistered selection rule."""
from __future__ import annotations

import copy
import json
import unittest

from select import select


def fixture() -> dict:
    production = {
        "example": {"runtime_closure": ["example", "example.base", "example.a",
                                        "example.b", "example.combined"],
                    "loc": 10, "blob_sha": "0", "dynamic": []},
        "example.base": {"runtime_closure": ["example.base"], "loc": 60,
                         "blob_sha": "1", "dynamic": []},
        "example.a": {"runtime_closure": ["example.a", "example.base"], "loc": 150,
                      "blob_sha": "2", "dynamic": []},
        "example.b": {"runtime_closure": ["example.b", "example.base"], "loc": 150,
                      "blob_sha": "3", "dynamic": []},
        "example.combined": {"runtime_closure": ["example.combined", "example.a",
                                               "example.b", "example.base"], "loc": 70,
                             "blob_sha": "4", "dynamic": []},
    }
    return {
        "schema_version": 2, "package": "example",
        "production_modules": production,
        "tests": [
            {"test_module": "tests.test_a", "direct_production_imports": ["example.a"]},
            {"test_module": "tests.test_b", "direct_production_imports": ["example.b"]},
            {"test_module": "tests.test_facade", "direct_production_imports": ["example"]},
        ],
        "independent_sibling_candidates": [
            {"join": "example.combined", "left": "example.a", "right": "example.b"}
        ],
        "test_exercised_module_candidates": [
            {"kind": "test_exercised_module_closure", "id": "test-module|example.a",
             "module": "example.a"},
            {"kind": "test_exercised_module_closure", "id": "test-module|example.b",
             "module": "example.b"},
        ],
        "extension_boundary_candidates": [
            {"kind": "extension_boundary", "id": "extension|example.base.B|example.a.A",
             "base_module": "example.base", "derived_module": "example.a",
             "scope": "cross-module"}
        ],
    }


class FrozenRankingTests(unittest.TestCase):
    def test_exact_frozen_score(self) -> None:
        result = select(fixture(), 3)
        first = result["selected"][0]
        self.assertEqual(first["id"], "example.combined|example.a|example.b")
        self.assertEqual(first["base_score_parts"], {
            "test_import_points": 6,
            "downstream_points": 4,
            "source_size_points": 3,
            "family_points": 4,
            "closure_cost_penalty": 0,
            "dynamic_import_penalty": 0,
        })
        self.assertEqual(first["base_score"], 17)
        self.assertEqual(first["novelty_points"], 4)
        self.assertEqual(first["new_family_points"], 2)
        self.assertEqual(first["greedy_score"], 23)
        self.assertEqual(first["test_import_witnesses"], ["tests.test_a", "tests.test_b"])
        self.assertNotIn("tests.test_facade", first["test_import_witnesses"])

    def test_greedy_diversification(self) -> None:
        result = select(fixture(), 3)
        self.assertEqual(len(result["selected"]), 3)
        self.assertEqual(len({s["family"] for s in result["selected"]}), 3)
        self.assertEqual(result["selected"][0]["selection_rank"], 1)
        self.assertEqual(result["selected"][2]["selection_rank"], 3)

    def test_budget_and_order_independence(self) -> None:
        d = fixture()
        a = select(d, 3)
        shuffled = copy.deepcopy(d)
        shuffled["test_exercised_module_candidates"].reverse()
        shuffled["tests"].reverse()
        self.assertEqual([s["id"] for s in a["selected"]],
                         [s["id"] for s in select(shuffled, 3)["selected"]])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(select(d, 3), sort_keys=True))
        self.assertEqual(select(d, 0)["selected"], [])

    def test_no_oracle_or_false_verification(self) -> None:
        result = select(fixture())
        self.assertTrue(all(c["status"] == "INSUFFICIENT_EVIDENCE"
                            for c in result["all_candidates"] + result["selected"]))
        self.assertNotIn("VERIFIED_WITHIN_SCOPE", json.dumps(result))

    def test_dynamic_import_penalty_is_explicit(self) -> None:
        base = select(fixture(), 1)
        d = fixture()
        d["production_modules"]["example.base"]["dynamic"] = ["import_module"]
        modified = select(d, 1)
        old = next(c for c in base["all_candidates"]
                   if c["id"] == "example.combined|example.a|example.b")
        new = next(c for c in modified["all_candidates"]
                   if c["id"] == old["id"])
        self.assertEqual(old["base_score"] - new["base_score"], 4)

    def test_duplicate_candidate_ids_fail_closed(self) -> None:
        d = fixture()
        d["test_exercised_module_candidates"].append(
            copy.deepcopy(d["test_exercised_module_candidates"][0]))
        with self.assertRaises(ValueError):
            select(d)

    def test_unknown_source_module_fails_closed(self) -> None:
        d = fixture()
        d["extension_boundary_candidates"][0]["base_module"] = "example.absent"
        with self.assertRaises(ValueError):
            select(d)

    def test_wrong_schema_and_invalid_budget_fail(self) -> None:
        d = fixture()
        d["schema_version"] = 1
        with self.assertRaises(ValueError):
            select(d)
        with self.assertRaises(ValueError):
            select(fixture(), -1)
        with self.assertRaises(ValueError):
            select(fixture(), 31)


if __name__ == "__main__":
    unittest.main()
