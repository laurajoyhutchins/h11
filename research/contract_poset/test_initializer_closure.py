"""Tests for interpreter-required, automatically regenerated package init edges."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from falsification import static_closure


class PackageInitializerClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def put(self, name: str, body: str) -> None:
        target = self.root / "src" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    def test_root_initializer_is_an_implicit_import_dependency(self) -> None:
        self.put("pkg/__init__.py", "REGISTERED = True\n")
        self.put("pkg/reader.py", "VALUE = 1\n")
        control = static_closure(self.root, "src", "pkg", "pkg.reader")
        corrected = static_closure(self.root, "src", "pkg", "pkg.reader",
                                   include_package_initializers=True)
        self.assertEqual(control, ["src/pkg/reader.py"])
        self.assertEqual(corrected, ["src/pkg/__init__.py", "src/pkg/reader.py"])

    def test_nested_initializers_and_their_imports_are_included(self) -> None:
        self.put("pkg/__init__.py", "from . import registration\n")
        self.put("pkg/registration.py", "REGISTERED = 1\n")
        self.put("pkg/sub/__init__.py", "from .. import shared\n")
        self.put("pkg/shared.py", "SHARED = 5\n")
        self.put("pkg/sub/leaf.py", "LEAF = 10\n")
        corrected = static_closure(self.root, "src", "pkg", "pkg.sub.leaf",
                                   include_package_initializers=True)
        self.assertEqual(corrected, [
            "src/pkg/__init__.py",
            "src/pkg/registration.py",
            "src/pkg/shared.py",
            "src/pkg/sub/__init__.py",
            "src/pkg/sub/leaf.py",
        ])

    def test_initializer_not_created_when_absent(self) -> None:
        self.put("namespace/entry.py", "VALUE = 1\n")
        corrected = static_closure(self.root, "src", "namespace", "namespace.entry",
                                   include_package_initializers=True)
        self.assertEqual(corrected, ["src/namespace/entry.py"])

    def test_imported_module_package_initializer_is_included(self) -> None:
        self.put("pkg/__init__.py", "VALUE = 'ready'\n")
        self.put("pkg/entry.py", "from .inner import tool\n")
        self.put("pkg/inner/__init__.py", "IMPORTED = True\n")
        self.put("pkg/inner/tool.py", "TOOL = 1\n")
        expected = [
            "src/pkg/__init__.py",
            "src/pkg/entry.py",
            "src/pkg/inner/__init__.py",
            "src/pkg/inner/tool.py",
        ]
        self.assertEqual(
            static_closure(self.root, "src", "pkg", "pkg.entry",
                           include_package_initializers=True),
            expected,
        )

    def test_cyclic_initializer_imports_terminate(self) -> None:
        self.put("pkg/__init__.py", "from .entry import VALUE\n")
        self.put("pkg/entry.py", "from . import util\nVALUE = 3\n")
        self.put("pkg/util.py", "from .entry import VALUE\n")
        result = static_closure(self.root, "src", "pkg", "pkg.entry",
                                include_package_initializers=True)
        self.assertEqual(result, [
            "src/pkg/__init__.py", "src/pkg/entry.py", "src/pkg/util.py"])


if __name__ == "__main__":
    unittest.main()
