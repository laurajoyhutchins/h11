"""Execute original h11 reader in a fresh, sealed, reader-only import world.

No candidate checkout is accepted. No writer module, connection module or
h11/__init__.py is imported. This verifies the 24 original composition
observations in a controlled baseline context, not against the candidate.

The reader implementation is *not* replicated: we import the real h11
ChunkedReader, ReceiveBuffer, Data, EndOfMessage and their actual dependencies.
"""
from __future__ import annotations

import argparse
import ast
import importlib
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import sys
import types

from domain import corpus

ALLOWED = {
    "h11._readers", "h11._receivebuffer", "h11._events",
    "h11._headers", "h11._abnf", "h11._util", "h11._state",
}
FIXTURES = ("legacy-empty", "legacy-single", "legacy-trailers", "legacy-binary")


class RestrictedFinder:
    def find_spec(self, fullname: str, path=None, target=None):
        if fullname.startswith("h11.") and fullname not in ALLOWED:
            raise ImportError("sealed reader disallows module " + fullname)
        return None


def reference_constants(source: Path) -> tuple[tuple[int, ...], bytes]:
    tree = ast.parse(source.read_text())
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in ("SEGMENTS", "SUFFIX"):
            constants[target.id] = ast.literal_eval(node.value)
    segments, suffix = constants.get("SEGMENTS"), constants.get("SUFFIX")
    if segments != (1, 2, 3, 7, 64, 1024) or not isinstance(suffix, bytes):
        raise ValueError("old composition fragmentation contract drifted")
    return segments, suffix


def sealed_import(package_root: Path):
    if any(k == "h11" or k.startswith("h11.") for k in sys.modules):
        raise ValueError("sealed reader process already imported h11")
    stub = types.ModuleType("h11")
    stub.__package__ = "h11"
    stub.__path__ = [str(package_root)]
    stub.__spec__ = ModuleSpec("h11", loader=None, is_package=True)
    # Prevent the ordinary package __init__ from importing _connection and
    # from there _writers. The frame checks actual reader module imports.
    sys.modules["h11"] = stub
    sys.meta_path.insert(0, RestrictedFinder())
    readers = importlib.import_module("h11._readers")
    buffer_module = importlib.import_module("h11._receivebuffer")
    event_module = importlib.import_module("h11._events")
    loaded = {k for k in sys.modules if k.startswith("h11.")}
    if loaded != ALLOWED or "h11._writers" in sys.modules:
        raise ValueError("reader import graph escapes sealed source closure: " + repr(loaded))
    return readers.ChunkedReader, buffer_module.ReceiveBuffer, (
        event_module.Data, event_module.EndOfMessage), sorted(k[4:] for k in loaded)


def decode(reader_class, buffer_class, data_class, eom_class,
           raw: bytes, step: int) -> tuple[bytes, list[tuple[bytes, bytes]], bytes]:
    reader = reader_class()
    buffer = buffer_class()
    payloads: list[bytes] = []
    for start in range(0, len(raw), step):
        buffer += raw[start:start + step]
        while True:
            event = reader(buffer)
            if event is None:
                break
            if isinstance(event, data_class):
                payloads.append(bytes(event.data))
            elif isinstance(event, eom_class):
                return (
                    b"".join(payloads),
                    list(event.headers),
                    bytes(buffer) + raw[start + step:],
                )
            else:
                raise ValueError("unexpected reader event")
    raise ValueError("sealed reader failed to terminate")


def observe(baseline: Path, observations: Path, prior: Path) -> dict:
    segments, suffix = reference_constants(
        baseline / "research/ci_evidence/test_roundtrip.py")
    old = json.loads(observations.read_text())
    if old.get("role") != "baseline" or old.get("schema_version") != 1:
        raise ValueError("expected checked baseline writer observation record")
    rows = {r["id"]: r for r in old["rows"]}
    if len(rows) != len(old["rows"]):
        raise ValueError("duplicate baseline trace IDs")
    original_inputs = {c["id"]: c for c in corpus()}
    if not set(FIXTURES) <= set(rows) or not set(FIXTURES) <= set(original_inputs):
        raise ValueError("missing original source cases")
    prior_record = json.loads(prior.read_text())
    if (prior_record.get("kind") != "linked-prior-evidence" or
        prior_record.get("exact_previous_fixture_cases") != list(FIXTURES)):
        raise ValueError("unverified original case lineage")

    Reader, Buffer, (Data, Eom), loaded = sealed_import(baseline / "h11")
    cases = []
    for identity in FIXTURES:
        case = original_inputs[identity]
        raw = b"".join(bytes.fromhex(x) for x in rows[identity]["writes"]) + suffix
        expected = (
            b"".join(bytes.fromhex(x) for x in case["payloads"]),
            [(bytes.fromhex(k), bytes.fromhex(v)) for k, v in case["trailers"]],
            suffix,
        )
        for step in segments:
            output = decode(Reader, Buffer, Data, Eom, raw, step)
            if output != expected:
                raise ValueError(f"sealed reader changed observation: {identity}/{step}")
            cases.append({
                "input": identity,
                "segment": step,
                "status": "PASSED",
            })
    if len(cases) != 24:
        raise ValueError("old source composition case count drifted")
    if {k for k in sys.modules if k.startswith("h11.")} != ALLOWED:
        raise ValueError("reader evaluation imported an outside module")
    return {
        "schema_version": 1,
        "kind": "sealed-reader-baseline-observations",
        "prior_verified_run_id": prior_record["verified_run_id"],
        "loaded_reader_modules": loaded,
        "package_initializer_executed": False,
        "writer_module_imported": False,
        "candidate_reader_executions": 0,
        "observations_count": len(cases),
        "cases": cases,
        "restriction": (
            "Reader tested at baseline in inert package loader with only "
            "seven checked h11 modules; no writer or normal initializer"
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--baseline-observations", type=Path, required=True)
    p.add_argument("--prior-reference", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    data = observe(args.baseline.resolve(),
                   args.baseline_observations.resolve(),
                   args.prior_reference.resolve())
    args.output.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    print("SEALED_READER", data["observations_count"],
          "baseline cases verified, no writer import, no candidate reader call")


if __name__ == "__main__":
    main()
