"""Tests for the generic discoverer; reference names appear only in evaluation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from discover import discover, resolve


class SourceOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path: str, content: str) -> None:
        output = self.root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)

    def fixture(self) -> dict:
        self.write("toy/__init__.py", "raise RuntimeError('discovery must never import package')\n")
        self.write("toy/base.py", "class Fact: pass\n")
        self.write("toy/alpha.py",
                   "from .base import Fact\nclass FancyReader:\n def __call__(self): pass\n")
        self.write("toy/beta.py",
                   "from typing import TYPE_CHECKING\nfrom .base import Fact\n"
                   "if TYPE_CHECKING:\n from .alpha import FancyReader\n"
                   "class FancyWriter:\n def __call__(self): pass\n")
        self.write("toy/combined.py",
                   "from .alpha import FancyReader\nfrom .beta import FancyWriter\n")
        self.write("toy/tests/__init__.py", "")
        self.write("toy/tests/helpers.py", "from ..alpha import FancyReader\n")
        self.write("toy/tests/test_beta.py",
                   "from ..beta import FancyWriter\nfrom .helpers import FancyReader\n")
        return discover(self.root, "toy")

    def test_independence_from_code_execution_and_specific_names(self) -> None:
        result = self.fixture()
        pair = result["independent_sibling_candidates"][0]
        self.assertEqual(pair["join"], "toy.combined")
        self.assertEqual({pair["left"], pair["right"]}, {"toy.alpha", "toy.beta"})
        self.assertEqual(pair["shared_dependencies"], ["toy.base"])
        self.assertEqual([x["stem"] for x in pair["matched_class_families"]], ["Fancy"])
        self.assertEqual(result["production_modules"]["toy.beta"]["typing_only"], ["toy.alpha"])
        self.assertEqual(result["production_modules"]["toy.beta"]["runtime_closure"],
                         ["toy.base", "toy.beta"])
        self.assertEqual(result["runtime_import_cycles"], [])

    def test_expands_test_helper_imports(self) -> None:
        result = self.fixture()
        self.assertEqual(len(result["tests"]), 1)
        test = result["tests"][0]
        self.assertEqual(test["direct_production_imports"], ["toy.alpha", "toy.beta"])
        self.assertEqual(test["depends_on_test_helpers"], ["toy.tests.helpers"])

    def test_stable_and_read_only(self) -> None:
        original = self.fixture()
        before = {str(p): p.read_bytes() for p in self.root.rglob("*.py")}
        self.assertEqual(json.dumps(original, sort_keys=True),
                         json.dumps(discover(self.root, "toy"), sort_keys=True))
        self.assertEqual(before,
                         {str(p): p.read_bytes() for p in self.root.rglob("*.py")})

    def test_relative_import_resolution(self) -> None:
        self.assertEqual(resolve("toy.tests.test_beta", False, 2, "beta"), "toy.beta")
        self.assertEqual(resolve("toy.tests", True, 1, "helpers"), "toy.tests.helpers")
        self.assertIsNone(resolve("toy.base", False, 3, "alpha"))

    def test_missing_package_fails(self) -> None:
        with self.assertRaises(ValueError):
            discover(self.root, "missing")


if __name__ == "__main__":
    unittest.main()
