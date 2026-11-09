"""TDD for conservative reader-closure checks and scoped frame evidence."""
from __future__ import annotations

import copy
import unittest

from reader_frame import (
    EXPECTED_CLOSURE, imports, verify_observations,
)


class ReaderFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = {
            "kind": "sealed-reader-source-frame",
            "declared_modules": sorted(EXPECTED_CLOSURE),
            "baseline_commit": "a" * 40,
            "candidate_commit": "b" * 40,
        }
        self.prior = {"verified_run_id": 42667731213}
        self.observed = {
            "schema_version": 1,
            "kind": "sealed-reader-baseline-observations",
            "prior_verified_run_id": 42667731213,
            "loaded_reader_modules": sorted(EXPECTED_CLOSURE),
            "package_initializer_executed": False,
            "writer_module_imported": False,
            "candidate_reader_executions": 0,
            "observations_count": 24,
            "cases": [
                {"status": "PASSED", "input": name, "segment": step}
                for name in ("legacy-empty", "legacy-single", "legacy-trailers", "legacy-binary")
                for step in (1, 2, 3, 7, 64, 1024)
            ],
        }

    def test_known_reader_imports_are_admitted(self):
        src = b"from ._events import Data\nfrom ._util import validate\n"
        self.assertEqual(imports("h11/_readers.py", src), {"_events", "_util"})

    def test_unapproved_writer_dependency_rejected(self):
        for src in (
            b"from ._writers import ChunkedWriter\n",
            b"import h11._writers\n",
            b"from ._connection import Connection\n",
        ):
            with self.subTest(src=src):
                with self.assertRaises(ValueError):
                    imports("h11/_readers.py", src)

    def test_dynamic_import_and_reflection_rejected(self):
        for src in (
            b"x = __import__('h11._writers')\n",
            b"import importlib\n",
            b"import inspect\n",
            b"x = getattr(object, '__code__')\n",
            b"x = sys.modules\n",
            b"x = ChunkedWriter\n",
            b"exec('pass')\n",
            b"x = open('h11/_writers.py')\n",
        ):
            with self.subTest(src=src):
                with self.assertRaises(ValueError):
                    imports("h11/_readers.py", src)

    def test_parser_rejects_unknown_relative_module(self):
        for src in (b"from ._bogus import X\n", b"from ..x import Y\n"):
            with self.assertRaises(ValueError):
                imports("h11/_readers.py", src)

    def test_abnf_top_level_globals_for_regexes_allowed(self):
        self.assertEqual(imports("h11/_abnf.py", b"x = globals()\n"), set())
        with self.assertRaises(ValueError):
            imports("h11/_readers.py", b"x = globals()\n")

    def test_complete_sealed_frame_is_accepted(self):
        certificate = verify_observations(self.frame, self.observed, self.prior)
        self.assertEqual(certificate["derived_claim"]["status"],
                         "PRESERVED_IN_SEALED_IMPORT_CONTEXT")
        self.assertEqual(certificate["observations"]["candidate_reader_executions"], 0)

    def test_attempt_to_claim_candidate_reader_execution_refused(self):
        bad = copy.deepcopy(self.observed)
        bad["candidate_reader_executions"] = 1
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)

    def test_writer_import_or_initializer_execution_refused(self):
        for k in ("writer_module_imported", "package_initializer_executed"):
            bad = copy.deepcopy(self.observed)
            bad[k] = True
            with self.subTest(field=k), self.assertRaises(ValueError):
                verify_observations(self.frame, bad, self.prior)

    def test_missing_or_failing_baseline_observation_refused(self):
        bad = copy.deepcopy(self.observed)
        bad["cases"][0]["status"] = "FAILED"
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)
        bad["cases"][0]["status"] = "PASSED"
        bad["cases"].pop()
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)

    def test_duplicate_case_is_rejected_even_if_all_24_passed(self):
        bad = copy.deepcopy(self.observed)
        bad["cases"][0] = bad["cases"][1]
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)

    def test_wrong_provenance_or_loaded_closure_refused(self):
        bad = copy.deepcopy(self.observed)
        bad["prior_verified_run_id"] = 0
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)
        bad["prior_verified_run_id"] = 42667731213
        bad["loaded_reader_modules"] = ["_readers"]
        with self.assertRaises(ValueError):
            verify_observations(self.frame, bad, self.prior)


if __name__ == "__main__":
    unittest.main()
