"""Small independent tests for the finite-domain preservation checker."""
from __future__ import annotations

import copy
import unittest

import check as verifier
from domain import corpus, digest
from probe import SEGMENTS, SUFFIX


class PreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = corpus()
        self.case = self.cases[1]
        self.writes = ["31", "0d0a", self.case["payloads"][0], "0d0a",
                       "30", "0d0a", "0d0a"]
        observation = {
            "payload": "".join(self.case["payloads"]),
            "trailers": self.case["trailers"],
            "unread_suffix": SUFFIX.hex(),
        }
        self.baseline = {
            "schema_version": 1, "role": "baseline",
            "corpus_sha256": digest([self.case]),
            "segments": list(SEGMENTS),
            "rows": [{"id": self.case["id"], "writes": self.writes,
                      "downstream": [observation] * len(SEGMENTS)}],
        }
        self.candidate = {
            "schema_version": 1, "role": "candidate",
            "corpus_sha256": digest([self.case]), "segments": [],
            "rows": [{"id": self.case["id"], "writes": self.writes}],
        }

    def verify(self):
        return verifier.verify_rows(self.baseline, self.candidate, [self.case])

    def test_corpus_is_finite_deterministic_and_nonempty(self) -> None:
        self.assertEqual(len(self.cases), 108)
        self.assertEqual(corpus(), self.cases)
        self.assertIn("trace-000", [x["id"] for x in self.cases])

    def test_equivalent_interface_traces_carry_composition(self) -> None:
        result = self.verify()
        self.assertTrue(result[0]["composition_retained_by_congruence"])

    def test_corrupted_writer_trace_is_not_preserved(self) -> None:
        self.candidate["rows"][0]["writes"][0] = "ff"
        with self.assertRaisesRegex(ValueError, "writer callback trace"):
            self.verify()

    def test_corrupted_baseline_decoder_observation_is_not_preserved(self) -> None:
        self.baseline["rows"][0]["downstream"][0]["payload"] = "00"
        with self.assertRaisesRegex(ValueError, "baseline downstream"):
            self.verify()

    def test_candidate_cannot_claim_to_have_rerun_downstream(self) -> None:
        self.candidate["rows"][0]["downstream"] = []
        with self.assertRaisesRegex(ValueError, "writer callback trace"):
            self.verify()

    def test_missing_trace_refused(self) -> None:
        self.candidate["rows"] = []
        with self.assertRaisesRegex(ValueError, "missing, duplicate"):
            self.verify()

    def test_wrong_corpus_digest_refused(self) -> None:
        self.candidate["corpus_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.verify()

    def test_restricted_ast_change_recognized(self) -> None:
        before = ("class ChunkedWriter:\n"
                  "    def send_data(self, data, write):\n"
                  "        write(b'original')\n")
        after = ("class ChunkedWriter:\n"
                 "    def send_data(self, data, write):\n"
                 "        write(data)\n")
        self.assertTrue(verifier.method_only_change(before, after))
        altered_other_method = after + "    def unexpected(self):\n        return 1\n"
        self.assertFalse(verifier.method_only_change(before, altered_other_method))

    def test_source_file_outside_writer_body_refused(self) -> None:
        before = ("import os\nclass ChunkedWriter:\n"
                  "    def send_data(self, data, write):\n        pass\n")
        after = before.replace("import os", "import sys").replace("pass", "write(data)")
        self.assertFalse(verifier.method_only_change(before, after))


if __name__ == "__main__":
    unittest.main()
