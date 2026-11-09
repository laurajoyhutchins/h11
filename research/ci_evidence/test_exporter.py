"""Fail-closed regression checks for the pytest -> in-toto conversion."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

import run as exporter
from run import CLAIM_TEST_MARKERS, identity, make_statement, parse_junit


def xml(names: list[str], fail: str = "", skip: str = "") -> str:
    cases = []
    for name in names:
        detail = ("<failure message='failed'/>" if name == fail else
                  "<skipped message='skip'/>" if name == skip else "")
        cases.append(f'<testcase classname="pkg.tests" name="{escape(name)}">{detail}</testcase>')
    return f"<testsuites><testsuite tests='{len(cases)}'>{''.join(cases)}</testsuite></testsuites>"


class EvidenceExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.junit = self.root / "report.xml"
        self.names = [
            "test_ChunkedReader", "test_ChunkedWriter",
            "test_corrupt_chunk_footer_rejected",
            "test_codec_composition_preserves_payload_trailers_and_suffix",
            "test_root_initializer_is_an_implicit_import_dependency",
        ]
        self.assertEqual(len(CLAIM_TEST_MARKERS), 4)

    def save(self, s: str) -> None:
        self.junit.write_text(s)

    def test_valid_report_maps_all_four_claims(self) -> None:
        self.save(xml(self.names))
        passed, failed, warned, groups = parse_junit(self.junit)
        self.assertEqual(len(passed), 5)
        self.assertFalse(failed or warned)
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(all(item in passed for item in tests)
                            for tests in groups.values()))

    def test_empty_report_refused(self) -> None:
        self.save("<testsuites><testsuite tests='0'/></testsuites>")
        with self.assertRaisesRegex(ValueError, "no test cases"):
            parse_junit(self.junit)

    def test_missing_required_group_refused(self) -> None:
        self.save(xml(self.names[:-1]))
        with self.assertRaisesRegex(ValueError, "required test group"):
            parse_junit(self.junit)

    def test_duplicate_case_identifiers_refused(self) -> None:
        self.save(xml(self.names + [self.names[0]]))
        with self.assertRaisesRegex(ValueError, "duplicate JUnit"):
            parse_junit(self.junit)

    def test_failure_never_counted_as_passing(self) -> None:
        self.save(xml(self.names, fail="test_ChunkedReader"))
        passed, failed, warned, _ = parse_junit(self.junit)
        self.assertEqual(len(failed), 1)
        self.assertFalse(warned)
        self.assertNotIn("pkg.tests::test_ChunkedReader", passed)

    def test_skip_never_counted_as_passing(self) -> None:
        self.save(xml(self.names, skip="test_ChunkedWriter"))
        passed, failed, warned, _ = parse_junit(self.junit)
        self.assertEqual(len(warned), 1)
        self.assertFalse(failed)
        self.assertNotIn("pkg.tests::test_ChunkedWriter", passed)

    def test_git_sha_mismatch_refused(self) -> None:
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        for k, v in (("user.name", "Test"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
        (repo / "file.txt").write_text("data\n")
        subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
        with self.assertRaisesRegex(ValueError, "GitHub event commit"):
            identity(repo, "f" * 40)

    def test_junit_bytes_bound_into_statement(self) -> None:
        self.save(xml(self.names))
        with patch.object(exporter, "resource",
                          side_effect=lambda repo, name: {
                              "name": name, "digest": {"sha256": "a" * 64},
                          }):
            statement = make_statement(self.root, "b" * 40, "c" * 40,
                                       self.junit, ["pkg.tests::x"], [], [])
        self.assertEqual(statement["predicate"]["result"], "PASSED")
        self.assertEqual(statement["subject"][0]["digest"]["gitCommit"], "b" * 40)
        actual = statement["predicate"]["configuration"][-1]["digest"]["sha256"]
        self.assertEqual(actual, hashlib.sha256(self.junit.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
