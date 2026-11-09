"""Tests for dependency-order ideals and explicit claim separation."""
from __future__ import annotations

import itertools
import tempfile
import unittest
import subprocess
from pathlib import Path

from poset import (
    attach_contracts, blob_sha, covers, frontier, from_frontier,
    git_objects, ideal_count, is_ideal, module_poset, validate_graph,
)


class IdealLatticeTests(unittest.TestCase):
    def setUp(self) -> None:
        # A diamond: foundation -> independent reader/writer -> composition.
        self.graph = {"foundation": set(), "reader": {"foundation"},
                      "writer": {"foundation"}, "composition": {"reader", "writer"}}
        self.closure = validate_graph(self.graph)

    def test_six_ideals_and_exact_frontiers(self) -> None:
        self.assertEqual(ideal_count(self.closure), 6)
        self.assertEqual(frontier({"foundation", "reader", "writer"}, self.closure),
                         ["reader", "writer"])
        for size in range(len(self.graph) + 1):
            for subset in itertools.combinations(self.graph, size):
                S = set(subset)
                if is_ideal(S, self.closure):
                    self.assertEqual(from_frontier(frontier(S, self.closure),
                                                   self.closure), S)

    def test_meet_and_join_stay_ideals_and_distribute(self) -> None:
        names = list(self.graph)
        ideals = [set(subset) for i in range(len(names) + 1)
                  for subset in itertools.combinations(names, i)
                  if is_ideal(set(subset), self.closure)]
        for a, b, c in itertools.product(ideals, repeat=3):
            self.assertTrue(is_ideal(a | b, self.closure))
            self.assertTrue(is_ideal(a & b, self.closure))
            self.assertEqual(a & (b | c), (a & b) | (a & c))
            self.assertEqual(a | (b & c), (a | b) & (a | c))

    def test_stage_merge_is_union_not_meet(self) -> None:
        reader = {"foundation", "reader"}
        writer = {"foundation", "writer"}
        composition = {"foundation", "reader", "writer"}
        self.assertEqual(reader & writer, {"foundation"})
        self.assertEqual(reader | writer, composition)
        self.assertTrue(is_ideal(composition, self.closure))
        self.assertFalse(is_ideal((composition | {"composition"}) - {"writer"}, self.closure))

    def test_cover_edges_remove_transitive_dependencies(self) -> None:
        graph = {**self.graph, "composition": {"foundation", "reader", "writer"}}
        closure = validate_graph(graph)
        edges = covers(graph, closure)
        self.assertNotIn({"prerequisite": "foundation", "dependent": "composition"}, edges)
        self.assertIn({"prerequisite": "reader", "dependent": "composition"}, edges)

    def test_cycles_and_unknown_nodes_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Cycle"):
            validate_graph({"a": {"b"}, "b": {"a"}})
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_graph({"a": {"missing"}})
        with self.assertRaisesRegex(ValueError, "Not a downward"):
            frontier({"reader"}, self.closure)

    def test_big_graph_count_is_not_guessed(self) -> None:
        graph = {f"node{i}": set() for i in range(19)}
        self.assertIsNone(ideal_count(validate_graph(graph)))

    def test_source_graph_is_not_a_semantic_contract(self) -> None:
        discovery = {
            "schema_version": 2,
            "production_modules": {
                "p.base": {"runtime": [], "runtime_closure": ["p.base"],
                           "blob_sha": "a" * 40, "path": "p/base.py"},
                "p.consumer": {"runtime": ["p.base"],
                               "runtime_closure": ["p.base", "p.consumer"],
                               "blob_sha": "b" * 40, "path": "p/consumer.py"},
            }
        }
        _, _, report = module_poset(discovery)
        self.assertEqual(report["number_of_order_ideals"], 3)
        self.assertEqual(report["cover_edges"], [
            {"prerequisite": "p.base", "dependent": "p.consumer"}])
        self.assertNotIn("guarantees", str(report))
        bad = {"schema_version": 2,
               "production_modules": dict(discovery["production_modules"])}
        bad["production_modules"]["p.consumer"] = dict(bad["production_modules"]["p.consumer"])
        bad["production_modules"]["p.consumer"]["runtime_closure"] = ["p.consumer"]
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module_poset(bad)


class GitIdentityTests(unittest.TestCase):
    def test_read_existing_git_blob_and_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def command(*args: str) -> str:
                return subprocess.check_output(["git", "-C", str(repo), *args],
                                               text=True).strip()
            command("init", "-q")
            command("config", "user.email", "research@example.invalid")
            command("config", "user.name", "Research")
            (repo / "p").mkdir()
            data = b"sample = 1\n"
            (repo / "p" / "mod.py").write_bytes(data)
            command("add", "p/mod.py")
            command("commit", "-qm", "fixture")
            objs = git_objects(repo, "HEAD")
            self.assertEqual(objs["p/mod.py"]["oid"], blob_sha(data))
            self.assertEqual(objs["p/mod.py"]["kind"], "blob")


class ExplicitClaimsTests(unittest.TestCase):
    def test_claim_dependency_lattice_does_not_come_from_imports(self) -> None:
        graph = {"m.reader": set(), "m.writer": set()}
        clos = validate_graph(graph)
        git_stages = [
            {"stage": "base", "modules": [], "stage_parent_names": []},
            {"stage": "reader", "modules": ["m.reader"], "stage_parent_names": ["base"]},
            {"stage": "writer", "modules": ["m.writer"], "stage_parent_names": ["base"]},
            {"stage": "merge", "modules": ["m.reader", "m.writer"],
             "stage_parent_names": ["reader", "writer"]},
        ]
        contracts = {"source": {"commit": "1", "tree": "2"}, "contracts": [
            {"id": "c.reader", "introduced_at": "reader"},
            {"id": "c.writer", "introduced_at": "writer"},
            {"id": "c.compose", "introduced_at": "merge"},
        ]}
        verified = {
            "source_ref": "1", "source_tree": "2",
            "verification_run": {"url": "https://example.invalid/ci"},
            "with_oracles": {"cases": [
                {"id": "reader-probe", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 1},
                {"id": "writer-probe", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 1},
                {"id": "composition-probe", "status": "VERIFIED_WITHIN_SCOPE", "semantic_mutants_killed": 1},
            ]},
        }
        links = {"source_commit": "1", "claims": [
            {"id": "c.reader", "modules": ["m.reader"],
             "depends_on": [], "evidence_case": "reader-probe"},
            {"id": "c.writer", "modules": ["m.writer"],
             "depends_on": [], "evidence_case": "writer-probe"},
            {"id": "c.compose", "modules": ["m.reader", "m.writer"],
             "depends_on": ["c.reader", "c.writer"], "evidence_case": "composition-probe"},
        ]}
        result = attach_contracts(contracts, links, verified, clos, git_stages, {})
        self.assertEqual(result["number_of_claim_order_ideals"], 5)
        self.assertEqual(result["stage_claim_projection"]["reader"]["claims_present_by_explicit_links"],
                         ["c.reader"])
        self.assertEqual(result["stage_claim_projection"]["writer"]["claims_present_by_explicit_links"],
                         ["c.writer"])
        self.assertEqual(result["stage_claim_projection"]["merge"]["semantic_claim_frontier"],
                         ["c.compose"])
        bad = {"source_commit": "1", "claims": [dict(v) for v in links["claims"]]}
        bad["claims"][-1]["depends_on"] = ["c.reader", "not-real"]
        with self.assertRaisesRegex(ValueError, "unknown prerequisite"):
            attach_contracts(contracts, bad, verified, clos, git_stages, {})


if __name__ == "__main__":
    unittest.main()
