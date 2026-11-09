"""Source-to-model bridge and Lean-kernel verification for arbitrary lengths.

The Lean proof is universal over Nat/list-of-UInt8; the bridge checks exactly
which Python syntax it represents. The trusted assumptions are standard
CPython semantics for bytes length, integer bit operators and %x formatting,
plus nonthrowing callbacks and the unchanged reader execution context.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PROOF = "research/preservation/formal/HexPreservation.lean"
REQUIRED_THEOREMS = (
    "HexPreservation.bitwiseDigits_eq_toDigits",
    "HexPreservation.chunkTrace_eq_for_all_payloads",
    "HexPreservation.messageTrace_eq_for_all_inputs",
    "HexPreservation.sharedReaderCongruence",
)
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}

PYTHON_SEMANTICS_NOTE = "research/preservation/PYTHON_SEMANTICS.md"
# These are specifications supporting the Python AST interpretation, not extra
# Lean theorems. See PYTHON_SEMANTICS.md for the remaining contextual premises.
PYTHON_313_REFERENCES = {
    "bytes_format_hex": "https://docs.python.org/3.13/library/stdtypes.html#printf-style-bytes-formatting",
    "integer_bitwise": "https://docs.python.org/3.13/library/stdtypes.html#bitwise-operations-on-integer-types",
    "bytes_and_mutable_sequences": "https://docs.python.org/3.13/library/stdtypes.html#binary-sequence-types-bytes-bytearray-memoryview",
    "truth_value_testing": "https://docs.python.org/3.13/library/stdtypes.html#truth-value-testing",
    "evaluation_order": "https://docs.python.org/3.13/reference/expressions.html#evaluation-order",
    "import_context_limits": "https://docs.python.org/3.13/reference/import.html",
    "function_introspection_limits": "https://docs.python.org/3.13/reference/datamodel.html",
}
OLD_METHOD = r'''
class ChunkedWriter:
    def send_data(self, data: bytes, write: Writer) -> None:
        if not data:
            return
        write(b"%x\r\n" % len(data))
        write(data)
        write(b"\r\n")
'''
NEW_METHOD = r'''
class ChunkedWriter:
    def send_data(self, data: bytes, write: Writer) -> None:
        if not data:
            return
        digits = b"0123456789abcdef"
        number = len(data)
        encoded = bytearray()
        while number:
            encoded.append(digits[number & 15])
            number >>= 4
        encoded.reverse()
        write(bytes(encoded) + b"\r\n")
        write(data)
        write(b"\r\n")
'''


def method(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    nodes = [
        child for cls in tree.body
        if isinstance(cls, ast.ClassDef) and cls.name == "ChunkedWriter"
        for child in cls.body
        if isinstance(child, ast.FunctionDef) and child.name == "send_data"
    ]
    if len(nodes) != 1:
        raise ValueError("missing or ambiguous chunk writer entrypoint")
    return nodes[0]


def source_matches(source: str, expected: str) -> bool:
    return ast.dump(method(source), include_attributes=False) == ast.dump(
        method(expected), include_attributes=False)


def validate_source_bridge(old_source: str, new_source: str) -> None:
    if not source_matches(old_source, OLD_METHOD):
        raise ValueError("baseline method does not match formal model's Python bridge")
    if not source_matches(new_source, NEW_METHOD):
        raise ValueError("candidate method does not match formal model's Python bridge")


def validate_proof_output(version: str, stdout: str) -> None:
    if not re.search(r"Lean \(version 4\.35\.0,", version):
        raise ValueError("proof was not checked using pinned Lean 4.35.0")
    # Lean #print axioms enumerates all transitive assumptions for each theorem.
    rows = re.findall(r"'([^']+)' depends on axioms: \[([^\]]*)\]", stdout)
    if len(rows) != len(REQUIRED_THEOREMS) or set(t for t, _ in rows) != set(REQUIRED_THEOREMS):
        raise ValueError("Lean failed to disclose all four theorem axiom sets")
    for theorem, raw in rows:
        axioms = {part.strip() for part in raw.split(",") if part.strip()}
        if not axioms.issubset(ALLOWED_AXIOMS):
            raise ValueError(f"{theorem} depends on unauthorized axioms: {axioms - ALLOWED_AXIOMS}")


def git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def proof_result(root: Path) -> dict:
    file = root / PROOF
    head = git_bytes(root, "rev-parse", "HEAD").decode().strip()
    if file.read_bytes() != git_bytes(root, "show", f"{head}:{PROOF}"):
        raise ValueError("proof source differs from Git commit")
    proc = subprocess.run(["lean", file.name], cwd=file.parent,
                          check=False, text=True, capture_output=True, timeout=120)
    if proc.returncode:
        raise ValueError("Lean proof failed: " + (proc.stderr + proc.stdout)[-2000:])
    version = subprocess.check_output(["lean", "--version"], cwd=file.parent, text=True)
    validate_proof_output(version, proc.stdout)
    return {
        "toolchain": "Lean 4.35.0",
        "proof_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "proof_git_commit": head,
        "theorems": list(REQUIRED_THEOREMS),
        "allowed_axioms": sorted(ALLOWED_AXIOMS),
        "kernel_checked": True,
    }


def verify_bridge(root: Path, baseline: Path, candidate: Path) -> dict:
    old = (baseline / "h11/_writers.py").read_text()
    new = (candidate / "h11/_writers.py").read_text()
    validate_source_bridge(old, new)
    from check import source_obligations
    old_sha = git_bytes(baseline, "rev-parse", "HEAD").decode().strip()
    new_sha = git_bytes(candidate, "rev-parse", "HEAD").decode().strip()
    source_evidence = source_obligations(candidate, old_sha, new_sha)
    if git_bytes(baseline, "status", "--porcelain") or git_bytes(candidate, "status", "--porcelain"):
        raise ValueError("dirty Git input to proof bridge")
    note = root / PYTHON_SEMANTICS_NOTE
    head = git_bytes(root, "rev-parse", "HEAD").decode().strip()
    if not note.is_file() or note.read_bytes() != git_bytes(
        root, "show", f"{head}:{PYTHON_SEMANTICS_NOTE}"
    ):
        raise ValueError("Python specification note differs from source Git commit")
    return {
        "source_restriction": source_evidence,
        "original_method_ast_sha256": hashlib.sha256(
            ast.dump(method(old), include_attributes=False).encode()).hexdigest(),
        "candidate_method_ast_sha256": hashlib.sha256(
            ast.dump(method(new), include_attributes=False).encode()).hexdigest(),
        "source_bridge_checked": True,
        "python_language_specification": {
            "version": "3.13",
            "documentation_path": PYTHON_SEMANTICS_NOTE,
            "documentation_sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
            "official_references": PYTHON_313_REFERENCES,
            "interpretation": (
                "The Python documentation specifies built-in operations; "
                "reader frame independence and callback observation restrictions "
                "are separate unproved context assumptions."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, baseline, candidate = (
        args.root.resolve(), args.baseline.resolve(), args.candidate.resolve())
    report = {
        "schema_version": 1,
        "proof": proof_result(root),
        "bridge": verify_bridge(root, baseline, candidate),
        "assumptions": [
            "Python %x on nonnegative integers follows standard lowercase hexadecimal representation",
            "Python nonnegative integer & 15 and >> 4 agree with Nat bitwise operations",
            "Input Data.data is bytes and len(data) is its nonnegative byte length",
            "Write callback observes only argument values/order and does not throw or mutate input",
            "Reader does not introspect the modified writer method, module state, or code object",
            "Python executions use unchanged runtime dependencies and relevant reader context",
        ],
        "scope": "all finite sequences of arbitrary finite byte payloads, including empty chunks",
        "limitation": (
            "Lean proves the abstract writer trace equivalence universally, not "
            "CPython operational semantics or universally correct HTTP decoding. "
            "Source correspondence is syntactic and conditional on stated assumptions."
        ),
    }
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("LEAN_PROVED", len(report["proof"]["theorems"]),
          "theorems; exact baseline/candidate Python ASTs checked")


if __name__ == "__main__":
    main()
