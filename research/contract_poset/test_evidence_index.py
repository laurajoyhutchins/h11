"""End-to-end tests of source-identity evidence reuse on actual scratch Git DAGs.

All Git commits are disposable local fixtures; no production source is changed.
"""
from __future__ import annotations

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from evidence_index import index
from poset import blob_sha


class EvidenceIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="git-evidence-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("p/base.py", "BASE = 1\n")
        self.write("p/reader.py", "from .base import BASE\nREAD = BASE\n")
        self.write("p/writer.py", "from .base import BASE\nWRITE = BASE\n")
        self.git("add", "p")
        self.git("commit", "-qm", "original")
        self.original = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")

        self.source = {}
        for module, deps in {"p.base": [], "p.reader": ["p.base"],
                             "p.writer": ["p.base"]}.items():
            path = module.replace(".", "/") + ".py"
            closure = [module, *deps]
            self.source[module] = {
                "path": path,
                "runtime": deps,
                "runtime_closure": sorted(closure),
                "blob_sha": blob_sha((self.repo / path).read_bytes()),
                "dynamic": [], "unresolved": [],
            }
        self.discovery = {"schema_version": 2, "package": "p",
                          "production_modules": self.source}
        self.contracts = {
            "source": {"commit": self.original, "tree": self.tree},
            "contracts": [
                {"id": "c.reader", "implementation": "p/reader.py",
                 "blob_sha": self.source["p.reader"]["blob_sha"],
                 "import_closure": ["p/base.py", "p/reader.py"]},
                {"id": "c.writer", "implementation": "p/writer.py",
                 "blob_sha": self.source["p.writer"]["blob_sha"],
                 "import_closure": ["p/base.py", "p/writer.py"]},
                {"id": "c.composition", "implementation": None,
                 "import_closure": ["p/base.py", "p/reader.py", "p/writer.py"]},
            ],
        }
        self.links = {"source_commit": self.original, "claims": [
            {"id": "c.reader", "modules": ["p.reader"], "depends_on": [],
             "evidence_case": "reader"},
            {"id": "c.writer", "modules": ["p.writer"], "depends_on": [],
             "evidence_case": "writer"},
            {"id": "c.composition", "modules": ["p.reader", "p.writer"],
             "depends_on": ["c.reader", "c.writer"], "evidence_case": "composition"},
        ]}
        self.verified = {
            "source_ref": self.original, "source_tree": self.tree,
            "verification_run": {"url": "https://example.invalid/run"},
            "full_ci_evidence_sha256": "f" * 64,
            "with_oracles": {"cases": [
                {"id": "reader", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 1},
                {"id": "writer", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 1},
                {"id": "composition", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 2},
            ]},
        }

        self.git("switch", "-qc", "documentation")
        self.write("docs/info.md", "# Changed documentation only\n")
        self.git("add", "docs/info.md")
        self.git("commit", "-qm", "add evidence document")
        self.documentation = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "reader", self.original)
        self.write("p/reader.py", "from .base import BASE\nREAD = BASE + 1\n")
        self.git("add", "p/reader.py")
        self.git("commit", "-qm", "reader implementation changed")
        self.reader = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "writer", self.original)
        self.write("p/writer.py", "from .base import BASE\nWRITE = BASE + 1\n")
        self.git("add", "p/writer.py")
        self.git("commit", "-qm", "writer implementation changed")
        self.writer = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "both", self.reader)
        self.git("merge", "-q", "--no-ff", "-m", "real merge of two branches", self.writer)
        self.merged = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "shared-change", self.original)
        self.write("p/base.py", "BASE = 2\n")
        self.git("add", "p/base.py")
        self.git("commit", "-qm", "shared dependency changed")
        self.shared = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "reader-deleted", self.original)
        self.git("rm", "-q", "p/reader.py")
        self.git("commit", "-qm", "reader source deleted")
        self.deleted = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True).strip()

    def write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def scan(self, *refs: str, links=None, contracts=None, verified=None, discovery=None):
        return index(self.repo, discovery or self.discovery,
                     contracts or self.contracts, links or self.links,
                     verified or self.verified, list(refs))

    def by_ref(self, *refs: str):
        return {
            item["ref"]: {x["claim"]: x for x in item["claims"]}
            for item in self.scan(*refs)["revisions"]
        }

    def test_doc_only_commit_preserves_exact_source_identity(self) -> None:
        results = self.scan(self.original, self.documentation)
        self.assertEqual([x["reuse_eligible"] for x in results["revisions"]], [3, 3])
        self.assertNotEqual(results["revisions"][0]["tree_oid"],
                            results["revisions"][1]["tree_oid"])
        self.assertEqual(results["revisions"][1]["new_paths_outside_original_source"], 1)

    def test_reader_and_writer_independent_changes(self) -> None:
        states = self.by_ref(self.reader, self.writer)
        for ref, stable in [(self.reader, "c.writer"), (self.writer, "c.reader")]:
            self.assertEqual(states[ref][stable]["status"], "REUSE_ELIGIBLE")
            changed = "c.reader" if stable == "c.writer" else "c.writer"
            self.assertEqual(states[ref][changed]["status"], "REVERIFY_REQUIRED")
            self.assertIn("SOURCE_BLOB_CHANGED", states[ref][changed]["reasons"])
            self.assertEqual(states[ref]["c.composition"]["status"], "REVERIFY_REQUIRED")

    def test_real_two_parent_merge_invalidates_both_and_composition(self) -> None:
        result = self.scan(self.merged)["revisions"][0]
        self.assertEqual(len(result["parent_oids"]), 2)
        self.assertEqual(result["reuse_eligible"], 0)
        self.assertEqual(result["reverify_required"], 3)

    def test_shared_dependency_invalidation(self) -> None:
        claims = self.by_ref(self.shared)[self.shared]
        self.assertTrue(all(x["status"] == "REVERIFY_REQUIRED" for x in claims.values()))
        for x in claims.values():
            self.assertIn("SOURCE_BLOB_CHANGED", x["reasons"])

    def test_missing_reader_does_not_invalidate_writer(self) -> None:
        claims = self.by_ref(self.deleted)[self.deleted]
        self.assertEqual(claims["c.reader"]["status"], "REVERIFY_REQUIRED")
        self.assertIn("SOURCE_MODULE_MISSING", claims["c.reader"]["reasons"])
        self.assertEqual(claims["c.writer"]["status"], "REUSE_ELIGIBLE")
        self.assertEqual(claims["c.composition"]["status"], "REVERIFY_REQUIRED")

    def test_explicit_semantic_dependency_propagates_without_direct_source_change(self) -> None:
        links = copy.deepcopy(self.links)
        contracts = copy.deepcopy(self.contracts)
        composition = next(x for x in links["claims"] if x["id"] == "c.composition")
        composition["modules"] = ["p.reader"]
        spec = next(x for x in contracts["contracts"] if x["id"] == "c.composition")
        spec["import_closure"] = ["p/base.py", "p/reader.py"]
        claims = {x["claim"]: x for x in self.scan(self.writer, links=links, contracts=contracts)
                  ["revisions"][0]["claims"]}
        self.assertEqual(claims["c.composition"]["changed_source_modules"], [])
        self.assertEqual(claims["c.composition"]["stale_prerequisite_claims"], ["c.writer"])
        self.assertIn("PREREQUISITE_CLAIM_NOT_REUSABLE", claims["c.composition"]["reasons"])

    def test_preexisting_insufficient_evidence_does_not_turn_green(self) -> None:
        evidence = copy.deepcopy(self.verified)
        evidence["with_oracles"]["cases"][0]["status"] = "INSUFFICIENT_EVIDENCE"
        claims = {x["claim"]: x for x in self.scan(self.original, verified=evidence)
                  ["revisions"][0]["claims"]}
        self.assertEqual(claims["c.reader"]["status"], "REVERIFY_REQUIRED")
        self.assertIn("PRIOR_ORACLE_NOT_VERIFIED", claims["c.reader"]["reasons"])
        self.assertEqual(claims["c.composition"]["status"], "REVERIFY_REQUIRED")
        self.assertEqual(claims["c.writer"]["status"], "REUSE_ELIGIBLE")

    def test_dynamic_dependency_blocks_source_reuse(self) -> None:
        changed = copy.deepcopy(self.discovery)
        changed["production_modules"]["p.reader"]["dynamic"] = ["import_module"]
        claims = {x["claim"]: x for x in self.scan(self.original, discovery=changed)
                  ["revisions"][0]["claims"]}
        self.assertIn("STATIC_IMPORT_ANALYSIS_INCOMPLETE", claims["c.reader"]["reasons"])
        self.assertEqual(claims["c.writer"]["status"], "REUSE_ELIGIBLE")

    def test_wrong_source_blob_and_unknown_semantic_edge_fail_closed(self) -> None:
        contracts = copy.deepcopy(self.contracts)
        contracts["contracts"][0]["blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "implementation blob"):
            self.scan(self.original, contracts=contracts)
        links = copy.deepcopy(self.links)
        links["claims"][-1]["depends_on"].append("nonexistent")
        with self.assertRaisesRegex(ValueError, "unknown prerequisite"):
            self.scan(self.original, links=links)

    def test_duplicate_refs_and_stale_evidence_pins_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.scan(self.original, self.original)
        fake = copy.deepcopy(self.verified)
        fake["source_tree"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "different original source"):
            self.scan(self.original, verified=fake)


if __name__ == "__main__":
    unittest.main()
