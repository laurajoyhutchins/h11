"""Tests of v2 structural discovery on unrelated, independently named source."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from discover_v2 import discover_v2


class BoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("src/lab/__init__.py",
                   "raise RuntimeError('never execute target package at discovery time')\n")
        self.write("src/lab/base.py", "class Parent:\n pass\n")
        self.write("src/lab/a.py",
                   "from .base import Parent\nclass DerivedA(Parent):\n pass\n")
        self.write("src/lab/b.py",
                   "import lab.base as b\nclass DerivedB(b.Parent):\n pass\n")
        self.write("src/lab/local.py",
                   "class Inner:\n pass\nclass Outer(Inner):\n pass\n")
        self.write("src/lab/consumer.py",
                   "from .a import DerivedA\nfrom .b import DerivedB\n")
        self.write("tests/test_a.py", "from lab.a import DerivedA\n")
        self.write("tests/test_facade.py", "import lab\n")
        self.write("tests/test_base.py", "from lab.base import Parent\n")

    def write(self, relative: str, content: str) -> None:
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def scan(self) -> dict:
        return discover_v2(self.root, "lab", ["tests"], source_dir="src")

    def test_resolves_intra_module_inheritance(self) -> None:
        result = self.scan()
        pairs = {(e["base"], e["derived"]) for e in result["extension_boundary_candidates"]}
        self.assertIn(("lab.local.Inner", "lab.local.Outer"), pairs)

    def test_resolves_explicit_import_and_module_alias(self) -> None:
        result = self.scan()
        pairs = {(e["base"], e["derived"]) for e in result["extension_boundary_candidates"]}
        self.assertIn(("lab.base.Parent", "lab.a.DerivedA"), pairs)
        self.assertIn(("lab.base.Parent", "lab.b.DerivedB"), pairs)

    def test_finds_direct_test_import_without_fabricating_test_execution(self) -> None:
        result = self.scan()
        candidates = {c["module"]: c for c in result["test_exercised_module_candidates"]}
        self.assertEqual(candidates["lab.a"]["supporting_test_modules"], ["tests.test_a"])
        self.assertEqual(candidates["lab.a"]["status"], "CANDIDATE_ONLY")
        self.assertEqual(candidates["lab.a"]["runtime_closure"], ["lab.a", "lab.base"])

    def test_facade_only_test_does_not_claim_submodule_coverage(self) -> None:
        result = self.scan()
        self.assertIn("tests.test_facade", result["facade_only_test_modules"])
        self.assertTrue(all("tests.test_facade" not in c["supporting_test_modules"]
                            for c in result["test_exercised_module_candidates"]))

    def test_determinism_and_no_source_execution(self) -> None:
        a = self.scan()
        b = self.scan()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(a["schema_version"], 2)
        self.assertEqual(a["source_dir"], "src")

    def test_unresolved_and_external_bases_not_invented(self) -> None:
        self.write("src/lab/weird.py",
                   "class One(ExternalUnknown):\n pass\n"
                   "class Two((lambda x:x)(One)):\n pass\n")
        result = self.scan()
        pairs = {(e["base"], e["derived"]) for e in result["extension_boundary_candidates"]}
        self.assertNotIn(("lab.weird.ExternalUnknown", "lab.weird.One"), pairs)
        self.assertNotIn(("lab.weird.One", "lab.weird.Two"), pairs)
        self.assertTrue(any(x["reason"] == "dynamic-base-expression"
                            for x in result["unresolved_class_bases"]))

    def test_existing_sibling_heuristic_remains_available(self) -> None:
        result = self.scan()
        pairs = result["independent_sibling_candidates"]
        self.assertTrue(any({p["left"], p["right"]} == {"lab.a", "lab.b"} and
                            p["join"] == "lab.consumer" for p in pairs))


if __name__ == "__main__":
    unittest.main()
