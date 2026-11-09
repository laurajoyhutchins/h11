"""Build two real local Git states, observe interfaces and verify preservation.

Only fixture commits are created. Nothing is pushed. The candidate implements
the chunk-header conversion using integer digit extraction instead of %-format.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

OLD = '        write(b"%x\\r\\n" % len(data))\n'
NEW = (
    "        digits = b\"0123456789abcdef\"\n"
    "        number = len(data)\n"
    "        encoded = bytearray()\n"
    "        while number:\n"
    "            encoded.append(digits[number & 15])\n"
    "            number >>= 4\n"
    "        encoded.reverse()\n"
    '        write(bytes(encoded) + b"\\r\\n")\n'
)
BAD = '        write(b"1\\r\\n")\n'


def run(*argv: str, cwd: Path | None = None, env: dict[str, str] | None = None,
        expect_failure: bool = False) -> None:
    completed = subprocess.run(argv, cwd=cwd, env=env, check=False)
    if (completed.returncode == 0) == expect_failure:
        raise AssertionError(f"unexpected exit status {completed.returncode}: {argv}")


def modify(repo: Path, replacement: str, commit: str) -> None:
    source = repo / "h11/_writers.py"
    original = source.read_text()
    if original.count(OLD) != 1:
        raise ValueError("source anchor changed; refusing unreviewed transformation")
    source.write_text(original.replace(OLD, replacement))
    run("git", "-C", str(repo), "add", "h11/_writers.py")
    run("git", "-C", str(repo), "commit", "-qm", commit)


def probe(repo: Path, role: str, output: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    run(sys.executable, str(repo / "research/preservation/probe.py"),
        "--root", str(repo), "--role", role, "--output", str(output),
        cwd=repo, env=env)


def check(root: Path, candidate: Path, work: Path, candidate_file: Path,
          output: Path, expect_failure: bool = False) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    run(sys.executable, str(root / "research/preservation/check.py"),
        "--baseline", str(root), "--candidate", str(candidate),
        "--baseline-observation", str(work / "baseline-observations.json"),
        "--candidate-observation", str(candidate_file),
        "--output", str(output), cwd=root, env=env,
        expect_failure=expect_failure)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    args = p.parse_args()
    source = args.source.resolve()
    work = args.work.resolve()
    if not work.is_dir() or source == work or source in work.parents:
        raise ValueError("work directory must be outside repository and already exist")
    original = work / "baseline"
    candidate = work / "candidate"
    mutant = work / "mutant"
    for target in (original, candidate, mutant):
        run("git", "clone", "-q", "--shared", str(source), str(target))
        run("git", "-C", str(target), "config", "user.name", "Research Fixture")
        run("git", "-C", str(target), "config", "user.email",
            "fixture@example.invalid")
    modify(candidate, NEW, "fixture: use integer-only hexadecimal chunk-header encoding")
    modify(mutant, BAD, "fixture: intentionally violate chunk length encoding")
    probe(original, "baseline", work / "baseline-observations.json")
    probe(candidate, "candidate", work / "candidate-observations.json")
    check(original, candidate, work, work / "candidate-observations.json",
          work / "preservation.json")

    baseline_sha = subprocess.check_output(
        ["git", "-C", str(original), "rev-parse", "HEAD"], text=True).strip()
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
    patch = subprocess.check_output(
        ["git", "-C", str(candidate), "diff", "--binary",
         baseline_sha, candidate_sha])
    (work / "candidate.patch").write_bytes(patch)
    attest_env = dict(os.environ, PYTHONPATH=str(original))
    evidence_command = [
        sys.executable, str(original / "research/preservation/attest.py"),
        "--work", str(work),
        "--baseline", str(original), "--candidate", str(candidate),
    ]
    run(evidence_command[0], evidence_command[1], "emit", *evidence_command[2:],
        cwd=original, env=attest_env)
    run(evidence_command[0], evidence_command[1], "verify", *evidence_command[2:],
        cwd=original, env=attest_env)

    unsigned = work / "preservation.intoto.json"
    correct = unsigned.read_bytes()
    invalid = json.loads(correct)
    invalid["predicate"]["result"] = "FAILED"
    unsigned.write_text(json.dumps(invalid, sort_keys=True) + "\n")
    run(evidence_command[0], evidence_command[1], "verify", *evidence_command[2:],
        cwd=original, env=attest_env, expect_failure=True)
    unsigned.write_bytes(correct)
    run(evidence_command[0], evidence_command[1], "verify", *evidence_command[2:],
        cwd=original, env=attest_env)


    probe(mutant, "candidate", work / "mutant-observations.json")
    check(original, mutant, work, work / "mutant-observations.json",
          work / "bad-preservation.json", expect_failure=True)
    if (work / "bad-preservation.json").exists():
        raise AssertionError("invalid writer received a preservation certificate")

    altered = json.loads((work / "candidate-observations.json").read_text())
    altered["rows"][3]["writes"].append("00")
    forged = work / "forged-observations.json"
    forged.write_text(json.dumps(altered, sort_keys=True) + "\n")
    check(original, candidate, work, forged, work / "forged-preservation.json",
          expect_failure=True)
    if (work / "forged-preservation.json").exists():
        raise AssertionError("forged observation received a preservation certificate")
    evidence = json.loads((work / "preservation.json").read_text())
    print(json.dumps({
        "finite_trace_count": evidence["scope"]["case_count"],
        "baseline": evidence["source"]["baseline_commit"],
        "candidate": evidence["source"]["candidate_commit"],
        "preserved_claims": [x["id"] for x in evidence["claims"]],
        "negative_mutation_refused": True,
        "forged_evidence_refused": True,
        "altered_in_toto_status_refused": True,
        "in_toto_statement_verified": True,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
