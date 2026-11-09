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
        with self.assertRaisesRegex(ValueError, "all three theorem"):
            bridge.validate_proof_output(
                "Lean (version 4.35.0, x86_64-unknown-linux-gnu)",
                GOOD_OUTPUT.splitlines()[0])
        with self.assertRaisesRegex(ValueError, "pinned Lean"):
            bridge.validate_proof_output(
                "Lean (version 4.34.0, x86_64-unknown-linux-gnu)", GOOD_OUTPUT)


if __name__ == "__main__":
    unittest.main()
