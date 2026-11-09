"""Frozen selection-comparator mechanics, without source execution."""
from __future__ import annotations
import unittest
from compare import baseline_modules, treatments


class ComparisonRules(unittest.TestCase):
    def fixture(self):
        return {
            "schema_version": 2, "package": "h11",
            "production_modules": {
                "h11": {"loc": 5, "blob_sha": "0", "runtime_closure": ["h11"],"dynamic":[]},
                "h11.a": {"loc": 150, "blob_sha": "a", "runtime_closure": ["h11.a"],"dynamic":[]},
                "h11.b": {"loc": 40, "blob_sha": "b", "runtime_closure": ["h11.b"],"dynamic":[]},
                "h11.c": {"loc": 290, "blob_sha": "c", "runtime_closure": ["h11.c"],"dynamic":[]},
                "h11.d": {"loc": 700, "blob_sha": "d", "runtime_closure": ["h11.d"],"dynamic":[]}
            },
            "tests": [
                {"test_module": "test_a", "direct_production_imports": ["h11.a"]},
                {"test_module": "test_b", "direct_production_imports": ["h11.b"]},
                {"test_module": "test_c", "direct_production_imports": ["h11.c"]},
                {"test_module": "test_facade", "direct_production_imports": ["h11"]}
            ],
            "independent_sibling_candidates": [],
            "test_exercised_module_candidates": [
                {"kind": "test_exercised_module_closure", "id": "test-module|h11.a", "module": "h11.a"},
                {"kind": "test_exercised_module_closure", "id": "test-module|h11.b", "module": "h11.b"},
                {"kind": "test_exercised_module_closure", "id": "test-module|h11.c", "module": "h11.c"}
            ],
            "extension_boundary_candidates": [],
        }

    def test_largest_tested_source_excludes_untested_and_facade(self):
        actual = baseline_modules(self.fixture(), 3)
        self.assertEqual([x["module"] for x in actual], ["h11.c", "h11.a", "h11.b"])

    def test_same_budget_treatment(self):
        result = treatments(self.fixture(), 3)
        self.assertEqual(len(result), 3)
        self.assertEqual({x["module"] for x in result}, {"h11.a", "h11.b", "h11.c"})

    def test_no_invented_module_for_extension(self):
        f = self.fixture()
        f["extension_boundary_candidates"] = [{
            "kind": "extension_boundary",
            "id": "extension|h11.a.Base|h11.b.Child",
            "base_module": "h11.a", "derived_module": "h11.b", "scope": "cross-module"
        }]
        choices = treatments(f, 3)
        for choice in choices:
            if choice["family"] == "extension_boundary":
                self.assertEqual(choice["module"], "h11.b")

    def test_ties_stable(self):
        f = self.fixture()
        f["production_modules"]["h11.c"]["loc"] = 150
        self.assertEqual([x["module"] for x in baseline_modules(f, 3)],
                         ["h11.a", "h11.c", "h11.b"])


if __name__ == "__main__":
    unittest.main()
