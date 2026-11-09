"""Standalone tests for generic evidence engine using unrelated toy modules."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from discover import discover
from verify import candidate_key, verify


class VerificationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="verify-toy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = self.root / "toy"
        self.pkg.mkdir()
        self.oracles = self.root / "oracles"
        self.oracles.mkdir()
        (self.pkg / "__init__.py").write_text("raise RuntimeError('must not import original init')\n")
        (self.pkg / "base.py").write_text("class Payload: pass\n")
        (self.pkg / "a.py").write_text("from .base import Payload\nclass PacketReader:\n def go(self,x):\n  return x+1\n")
        (self.pkg / "b.py").write_text("from .base import Payload\nclass PacketWriter:\n def go(self,x):\n  return x*2\n")
        (self.pkg / "combined.py").write_text("from .a import PacketReader\nfrom .b import PacketWriter\n")
        (self.oracles / "reader_oracle.py").write_text(
            "import unittest\nfrom toy.a import PacketReader\n"
            "class Probe(unittest.TestCase):\n"
            " def test_value(self):\n  self.assertEqual(PacketReader().go(1),2)\n")
        (self.oracles / "writer_oracle.py").write_text(
            "import unittest\nfrom toy.b import PacketWriter\n"
            "class Probe(unittest.TestCase):\n"
            " def test_value(self):\n  self.assertEqual(PacketWriter().go(2),4)\n")
        self.discovery = discover(self.root, "toy")
        self.assertEqual(len(self.discovery["independent_sibling_candidates"]), 1)
        self.key = candidate_key(self.discovery["independent_sibling_candidates"][0])
        self.plan = {"schema_version": 1, "cases": [
            {"id": "reader", "candidate": self.key, "modules": ["toy.a"],
             "oracle": "reader_oracle.py", "claims": ["Reader increments input by 1"],
             "mutations": [{"id": "plus-two", "module": "toy.a", "search": "return x+1", "replace": "return x+2"}]},
            {"id": "writer", "candidate": self.key, "modules": ["toy.b"],
             "oracle": "writer_oracle.py", "claims": ["Writer doubles input"],
             "mutations": [{"id": "times-three", "module": "toy.b", "search": "return x*2", "replace": "return x*3"}]},
        ]}

    def check(self, plan=None, discovery=None):
        return verify(self.root, discovery or self.discovery, plan,
                      self.oracles, timeout=10)["candidates"][0]

    def test_mutants_killed_at_independent_boundaries(self) -> None:
        result = self.check(self.plan)
        self.assertEqual(result["status"], "VERIFIED_WITHIN_SCOPE")
        self.assertEqual([m["result"] for c in result["cases"] for m in c["mutations"]],
                         ["KILLED", "KILLED"])
        self.assertEqual(self.pkg.joinpath("a.py").read_text().count("return x+1"), 1)

    def test_no_oracles_returns_insufficient(self) -> None:
        self.assertEqual(self.check()["status"], "INSUFFICIENT_EVIDENCE")

    def test_surviving_mutant_does_not_verify(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["cases"][0]["mutations"][0]["search"] = "class PacketReader:"
        plan["cases"][0]["mutations"][0]["replace"] = "class PacketReader:\n pass"
        result = self.check(plan)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["cases"][0]["mutations"][0]["result"], "SURVIVED")

    def test_unmatched_mutant_is_blocked(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["cases"][0]["mutations"][0]["search"] = "not a source snippet"
        self.assertEqual(self.check(plan)["status"], "BLOCKED")

    def test_falsified_oracle_is_contradicted(self) -> None:
        (self.oracles / "reader_oracle.py").write_text(
            "import unittest\nfrom toy.a import PacketReader\n"
            "class Probe(unittest.TestCase):\n"
            " def test_false_claim(self):\n  self.assertEqual(PacketReader().go(1),500)\n")
        result = self.check(self.plan)
        self.assertEqual(result["status"], "CONTRADICTED")
        self.assertEqual(result["cases"][0]["status"], "CONTRADICTED")

    def test_stale_source_blocks_all_execution(self) -> None:
        (self.pkg / "b.py").write_text((self.pkg / "b.py").read_text()+"\n# stale\n")
        result = self.check(self.plan)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["cases"], [])

    def test_invented_candidate_is_an_error(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["cases"][0]["candidate"] = "invented|target|fake"
        with self.assertRaises(ValueError):
            self.check(plan)

    def test_dynamic_import_means_unsupported(self) -> None:
        with (self.pkg / "a.py").open("a") as file:
            file.write("__import__('toy.base')\n")
        result = self.check(self.plan, discover(self.root, "toy"))
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["cases"][0]["status"], "UNSUPPORTED")

    def test_testless_oracle_is_blocked(self) -> None:
        (self.oracles / "reader_oracle.py").write_text("# no tests\n")
        self.assertEqual(self.check(self.plan)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
