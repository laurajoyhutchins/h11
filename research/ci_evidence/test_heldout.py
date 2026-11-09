"""Regression tests of the held-out whole-source comparator."""
from __future__ import annotations

import unittest

from heldout import choose, START_AFTER, REVISION_COUNT


class HeldoutSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = {
            "src/pkg/__init__.py": "100644:blob:aaa",
            "src/pkg/worker.py": "100644:blob:bbb",
            "pyproject.toml": "100644:blob:ccc",
        }

    def test_older_history_not_reused_in_original_seventy(self) -> None:
        self.assertEqual(START_AFTER, 70)
        self.assertEqual(REVISION_COUNT, 20)

    def test_docs_only_same_tree_reuses(self) -> None:
        self.assertEqual(choose(self.before, dict(self.before), "src/pkg/")[0], "REUSE")

    def test_implicit_initializer_change_reverifies(self) -> None:
        after = dict(self.before, **{"src/pkg/__init__.py": "100644:blob:new"})
        verdict, changed = choose(self.before, after, "src/pkg/")
        self.assertEqual(verdict, "REVERIFY")
        self.assertIn("src/pkg/__init__.py", changed)

    def test_added_implementation_reverifies(self) -> None:
        after = dict(self.before, **{"src/pkg/added.py": "100644:blob:new"})
        self.assertEqual(choose(self.before, after, "src/pkg/")[0], "REVERIFY")

    def test_removed_package_refuses_reuse(self) -> None:
        self.assertEqual(choose(self.before, {"pyproject.toml": "x"}, "src/pkg/")[0],
                         "UNKNOWN")

    def test_changed_environment_refuses_reuse(self) -> None:
        self.assertEqual(choose(self.before, dict(self.before), "src/pkg/",
                                env_equal=False)[0], "UNKNOWN")

    def test_missing_baseline_refuses_reuse(self) -> None:
        self.assertEqual(choose({}, dict(self.before), "src/pkg/")[0], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
