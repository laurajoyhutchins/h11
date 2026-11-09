"""TDD for evidence consumer on real scratch Git trees and forged inputs."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import consume
import manifest
import run as producer


class ConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h11-reuse-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Research")
        self.git("config", "user.email", "research@example.invalid")
        for path in sorted(set(manifest.EXTRA_PATHS) |
                           set(producer.SOURCE_FILES)):
            self.put(path, "# pinned source\n")
        self.put("h11/_connection.py", "# extra production dependency\n")
        self.commit("original")
        self.base = self.git("rev-parse", "HEAD")
        self.env = manifest.environment()
        self.deps = manifest.generate(self.repo, self.base)
        self.write("dependencies.json", self.deps)
        self.junit = self.artifacts / "results.xml"
        names = (
            "test_ChunkedReader", "test_ChunkedWriter",
            "test_corrupt_chunk_footer_rejected",
            "test_codec_composition_preserves_payload_trailers_and_suffix",
            "test_root_initializer_is_an_implicit_import_dependency",
        )
        self.junit.write_text("<testsuites><testsuite>"
            + "".join(f'<testcase classname="fixture" name="{n}"/>'
                      for n in names)
            + "</testsuite></testsuites>")
        passed, failed, warned, groups = producer.parse_junit(self.junit)
        assert not failed and not warned
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "555",
                                     "GITHUB_REPOSITORY": consume.REPOSITORY,
                                     "GITHUB_SERVER_URL": "https://github.com"}):
            statement = producer.make_statement(
                self.repo, self.base, self.deps["source_tree"],
                self.junit, passed, [], [],
                dependencies=self.artifacts / "dependencies.json")
        self.write("test-result.intoto.json", statement)
        self.write("claim-results.json", {
            "schema_version": 1, "source_commit": self.base,
            "source_tree": self.deps["source_tree"], "status": "PASSED",
            "claims": [
                {"id": k, "status": "VERIFIED_WITHIN_TEST_SCOPE",
                 "required_tests": v} for k, v in sorted(groups.items())
            ]})
        self.meta = {
            "id": 555, "repository": {"full_name": consume.REPOSITORY},
            "head_sha": self.base, "head_branch": consume.BRANCH,
            "conclusion": "success", "status": "completed",
            "event": "push", "path": consume.WORKFLOW,
        }

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True).strip()

    def put(self, path: str, content: str) -> None:
        f = self.repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def write(self, name: str, body: dict) -> None:
        (self.artifacts / name).write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n")

    def result(self, ref: str | None = None, env: dict | None = None,
               meta: dict | None = None) -> dict:
        return consume.consume(self.repo, self.artifacts,
                               self.meta if meta is None else meta,
                               ref or self.git("rev-parse", "HEAD"),
                               self.env if env is None else env)

    def test_identical_commit_can_reuse_exact_bounded_evidence(self) -> None:
        self.assertEqual(self.result()["decision"], "REUSE")

    def test_documentation_only_commit_reuses(self) -> None:
        self.put("docs/note.md", "doc change\n")
        self.commit("docs only")
        self.assertEqual(self.result()["decision"], "REUSE")

    def test_implicit_package_initializer_change_forces_reverify(self) -> None:
        self.put("h11/__init__.py", "EXTRA = 2\n")
        self.commit("mutate implicit initializer")
        self.assertEqual(self.result()["decision"], "REVERIFY")
        self.assertIn("h11/__init__.py", self.result()["changed_paths"])

    def test_unrelated_but_in_package_file_change_reverifies(self) -> None:
        self.put("h11/_connection.py", "EXTRA = 2\n")
        self.commit("change package")
        self.assertEqual(self.result()["decision"], "REVERIFY")

    def test_add_new_implementation_file_reverifies(self) -> None:
        self.put("h11/new_module.py", "NEW = 2\n")
        self.commit("add dynamic load candidate")
        self.assertEqual(self.result()["decision"], "REVERIFY")

    def test_test_or_runner_change_reverifies(self) -> None:
        self.put("research/ci_evidence/test_roundtrip.py", "assert False\n")
        self.commit("change test oracle")
        self.assertEqual(self.result()["decision"], "REVERIFY")

    def test_untracked_package_file_refuses(self) -> None:
        self.put("h11/plugin.py", "VALUE = 3\n")
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_environment_change_refuses(self) -> None:
        env = dict(self.env, python_version="different")
        self.assertEqual(self.result(env=env)["decision"], "UNKNOWN")

    def test_untrusted_run_refuses(self) -> None:
        bad = dict(self.meta, conclusion="failure")
        self.assertEqual(self.result(meta=bad)["decision"], "UNKNOWN")

    def test_wrong_run_source_commit_refuses(self) -> None:
        bad = dict(self.meta, head_sha="f" * 40)
        self.assertEqual(self.result(meta=bad)["decision"], "UNKNOWN")

    def test_manifest_tampering_refuses(self) -> None:
        original = json.loads((self.artifacts / "dependencies.json").read_text())
        mutated = copy.deepcopy(original)
        mutated["files"]["h11/__init__.py"]["oid"] = "f" * 40
        self.write("dependencies.json", mutated)
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_fake_passing_junit_refuses(self) -> None:
        self.junit.write_text(
            self.junit.read_text().replace("test_ChunkedWriter", "test_OTHER"))
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_missing_claim_refuses(self) -> None:
        claims = json.loads((self.artifacts / "claim-results.json").read_text())
        claims["claims"] = claims["claims"][:-1]
        self.write("claim-results.json", claims)
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_legacy_evidence_without_manifest_refuses(self) -> None:
        (self.artifacts / "dependencies.json").unlink()
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_renamed_test_does_not_create_new_verification(self) -> None:
        body = self.junit.read_text().replace(
            "test_ChunkedWriter", "test_ChunkedWriter_renamed")
        self.junit.write_text(body)
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_manifest_policy_includes_implicit_initializers_and_entire_package(self) -> None:
        files = self.deps["files"]
        self.assertIn("h11/__init__.py", files)
        self.assertIn("h11/_connection.py", files)
        self.assertIn("h11/tests/test_io.py" if "h11/tests/test_io.py" in files
                      else "h11/_writers.py", files)


if __name__ == "__main__":
    unittest.main()
