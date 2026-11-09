"""Fail-closed regressions for Lean-to-Python correspondence checks."""
from __future__ import annotations

import unittest

import formal_bridge as bridge


GOOD_OUTPUT = "\n".join(
    f"'{thm}' depends on axioms: [propext, Classical.choice, Quot.sound]"
    for thm in bridge.REQUIRED_THEOREMS
)


class FormalBridgeTests(unittest.TestCase):
    def test_exact_original_and_candidate_methods(self) -> None:
        bridge.validate_source_bridge(bridge.OLD_METHOD, bridge.NEW_METHOD)

    def test_modified_candidate_shift_is_rejected(self) -> None:
        candidate = bridge.NEW_METHOD.replace("number >>= 4", "number >>= 5")
        with self.assertRaisesRegex(ValueError, "candidate method"):
            bridge.validate_source_bridge(bridge.OLD_METHOD, candidate)

    def test_extra_callback_invocation_is_rejected(self) -> None:
        candidate = bridge.NEW_METHOD.replace(
            '        write(data)', '        write(b"extra")\n        write(data)')
        with self.assertRaisesRegex(ValueError, "candidate method"):
            bridge.validate_source_bridge(bridge.OLD_METHOD, candidate)

    def test_changed_original_format_is_rejected(self) -> None:
        original = bridge.OLD_METHOD.replace('%x', '%X')
        with self.assertRaisesRegex(ValueError, "baseline method"):
            bridge.validate_source_bridge(original, bridge.NEW_METHOD)

    def test_missing_original_zero_case_is_rejected(self) -> None:
        original = bridge.OLD_METHOD.replace(
            "        if not data:\n            return\n", "")
        with self.assertRaisesRegex(ValueError, "baseline method"):
            bridge.validate_source_bridge(original, bridge.NEW_METHOD)

    def test_restricted_model_excludes_fake_python_inputs(self) -> None:
        candidate = bridge.NEW_METHOD.replace(
            "number = len(data)", "number = int(data)")
        with self.assertRaisesRegex(ValueError, "candidate method"):
            bridge.validate_source_bridge(bridge.OLD_METHOD, candidate)

    def test_python_reference_is_pinned_to_3_13(self) -> None:
        self.assertEqual(
            bridge.PYTHON_SEMANTICS_NOTE,
            "research/preservation/PYTHON_SEMANTICS.md",
        )
        self.assertEqual(
            set(bridge.PYTHON_313_REFERENCES),
            {
                "bytes_format_hex", "integer_bitwise",
                "bytes_and_mutable_sequences", "truth_value_testing",
                "evaluation_order", "import_context_limits",
                "function_introspection_limits",
            },
        )
        self.assertTrue(all(
            url.startswith("https://docs.python.org/3.13/")
            for url in bridge.PYTHON_313_REFERENCES.values()
        ))

    def test_runtime_function_introspection_can_distinguish_sources(self) -> None:
        # Same emitted bytes do not imply arbitrary contextual equivalence.
        before = {"Writer": object}
        after = {"Writer": object}
        exec(bridge.OLD_METHOD, before)
        exec(bridge.NEW_METHOD, after)
        old = before["ChunkedWriter"].send_data
        new = after["ChunkedWriter"].send_data
        self.assertNotEqual(old.__code__.co_code, new.__code__.co_code)

    def test_annotation_does_not_restrict_runtime_data_to_bytes(self) -> None:
        namespace = {"Writer": object}
        exec(bridge.OLD_METHOD, namespace)

        class Placeholder:
            def __len__(self) -> int:
                return 3

        data = Placeholder()
        observed: list[object] = []
        namespace["ChunkedWriter"]().send_data(data, observed.append)
        self.assertIs(observed[1], data)
        self.assertEqual(observed[0], b"3\r\n")

    def test_allowed_axioms_are_accepted(self) -> None:
        bridge.validate_proof_output(
            "Lean (version 4.35.0, x86_64-unknown-linux-gnu)", GOOD_OUTPUT)

    def test_sorry_axiom_is_rejected(self) -> None:
        bad = GOOD_OUTPUT.replace("Quot.sound", "Quot.sound, sorryAx", 1)
        with self.assertRaisesRegex(ValueError, "unauthorized axioms"):
            bridge.validate_proof_output(
                "Lean (version 4.35.0, x86_64-unknown-linux-gnu)", bad)

    def test_custom_axiom_is_rejected(self) -> None:
        bad = GOOD_OUTPUT.replace("Quot.sound", "free_equivalence", 1)
        with self.assertRaisesRegex(ValueError, "unauthorized axioms"):
            bridge.validate_proof_output(
                "Lean (version 4.35.0, x86_64-unknown-linux-gnu)", bad)

    def test_missing_theorem_or_wrong_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "all four theorem"):
            bridge.validate_proof_output(
                "Lean (version 4.35.0, x86_64-unknown-linux-gnu)",
                GOOD_OUTPUT.splitlines()[0])
        with self.assertRaisesRegex(ValueError, "pinned Lean"):
            bridge.validate_proof_output(
                "Lean (version 4.34.0, x86_64-unknown-linux-gnu)", GOOD_OUTPUT)


if __name__ == "__main__":
    unittest.main()
