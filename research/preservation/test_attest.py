"""Regression tests for standardized preservation evidence and tamper refusals."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import attest


class AttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "old"
        self.candidate = self.root / "new"
        self.base.mkdir()
        self.candidate.mkdir()
        self.work = self.root / "observations"
        self.work.mkdir()
        for name in attest.ARTIFACT_FILES:
            (self.work / name).write_text(name)
        self.cert = {
            "source": {
                "baseline_commit": "a" * 40,
                "candidate_commit": "b" * 40,
                "candidate_tree": "c" * 40,
            },
            "scope": {"case_count": 1},
            "cases": [{"case": "trace-000"}],
            "claims": [
                {"id": "chunked.writer.bounded", "status": "FRESHLY_VERIFIED_WITHIN_CORPUS"},
                {"id": "chunked.reader.bounded", "status": "CARRIED"},
                {"id": "chunked.composition.bounded", "status": "CARRIED"},
            ],
        }

    def git(self, repo: Path, *args: str) -> bytes:
        if args == ("rev-parse", "HEAD"):
            return b"a" * 40 if repo == self.base else b"b" * 40
        if args[0] == "show":
            return b"pinned verifier file"
        raise ValueError(args)

    def emit(self) -> dict:
        with patch.object(attest, "recheck", return_value=self.cert), \
             patch.object(attest, "git", side_effect=self.git), \
             patch.object(attest, "expected_url", return_value=None):
            return attest.emit(self.work, self.base, self.candidate)

    def validate(self) -> None:
        with patch.object(attest, "recheck", return_value=self.cert), \
             patch.object(attest, "git", side_effect=self.git), \
             patch.object(attest, "expected_url", return_value=None):
            attest.verify(self.work, self.base, self.candidate)

    def test_only_executed_checks_reported_as_tests(self) -> None:
        statement = self.emit()
        self.validate()
        self.assertEqual(statement["predicateType"], attest.PREDICATE_TYPE)
        self.assertEqual(statement["_type"], attest.STATEMENT_TYPE)
        names = statement["predicate"]["passedTests"]
        self.assertEqual(len(names), 5)
        self.assertFalse(any("composition" in name or "candidate-reader" in name
                             for name in names))
        self.assertEqual(statement["subject"][0]["digest"]["gitCommit"], "b" * 40)

    def test_observation_mutation_invalidates_statement(self) -> None:
        self.emit()
        (self.work / "candidate-observations.json").write_text("forged")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.validate()

    def test_certificate_mutation_invalidates_statement(self) -> None:
        self.emit()
        (self.work / "preservation.json").write_text("forged")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.validate()

    def test_statement_failed_status_refused(self) -> None:
        self.emit()
        path = self.work / "preservation.intoto.json"
        doc = json.loads(path.read_text())
        doc["predicate"]["result"] = "FAILED"
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.validate()

    def test_other_candidate_git_commit_refused(self) -> None:
        self.emit()
        self.cert["source"]["candidate_commit"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "Git commits"):
            self.validate()

    def test_unsigned_result_is_not_an_attestation_envelope(self) -> None:
        result = self.emit()
        self.assertNotIn("signatures", result)
        self.assertNotIn("payload", result)
        self.assertIn("preservation.json",
                      [c["name"] for c in result["predicate"]["configuration"]])


if __name__ == "__main__":
    unittest.main()
