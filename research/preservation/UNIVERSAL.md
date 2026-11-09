# Universal hexadecimal writer preservation

This is the stronger follow-up to the 112-trace experiment in
`research/contract-preservation`. No h11 production source changes are
pushed. A scratch Git commit rewrites only `ChunkedWriter.send_data`.

## What Lean proves

The source `formal/HexPreservation.lean`, checked with Lean **4.35.0** and
only Lean's `Init`, proves three theorems:

1. **All positive natural numbers:** the candidate's repeated low-nibble
   extraction and right-shift, followed by reversal, equals the standard
   canonical base-16 digit sequence, without leading zeroes.
2. **All finite byte payloads:** the original and replacement writer
   emit exactly the same *ordered sequence of write-callback arguments*,
   including empty-data suppression and the CRLF boundaries.
3. **All finite sequences of byte payloads:** the complete writer trace is
   unchanged when the end-of-message callback sequence is unchanged.

These are universally quantified claims in the Lean model, not 112 test cases.
The proof uses strong induction on natural numbers and the library's
bitwise/division lemmas. The CI checks Lean's transitive axiom report, allowing
only `propext`, `Classical.choice`, and `Quot.sound`. It rejects an
unexpected axiom such as `sorryAx`.

## Connecting the model to Python

`formal_bridge.py` requires the actual baseline and scratch candidate
`ChunkedWriter.send_data` methods to match independently specified AST
templates. The existing Git source checker additionally requires that every
other tracked file and every other AST node remain unchanged.

The bridge explicitly assumes the usual CPython meaning of:

- `b"%x\r\n" % len(data)` for a nonnegative integer length;
- `digits[number & 15]`, `number >>= 4`, bytearray reverse and `bytes`;
- `data` being a byte sequence and `write` a nonthrowing ordered callback.

Lean does **not** verify CPython's interpreter implementation or memory
safety, arbitrary callback failures, aliasing custom data objects, or
all external dependency effects. The source bridge is *exact but syntactic*.
It prevents a silently modified Python function from inheriting the model
theorem, but it does not constitute a fully formal Python-language refinement.

## Prior evidence and what is preserved

The integration rechecks the old native test evidence from
[run 42667731213](https://github.com/laurajoyhutchins/h11/actions/runs/42667731213),
including Git objects, JUnit, in-toto digests, recorded claims, execution
environment, and authenticated GitHub workflow metadata.

The verified universal writer equality can then be composed with the
previous **finite** reader observations. Their corresponding downstream
composition claims remain justified over the previous four fixtures and
six fragmentation sizes (24 observations) without running a candidate reader.

This is a conditional statement:

```text
forall payloads : List (List UInt8),
  WriterNew(payloads) = WriterOld(payloads)

ReaderNew = ReaderOld              (unchanged trusted dependencies)
ExistingEvidence(ReaderOld, x)    (only for a stated set of x)
--------------------------------------------------------------
PreservedComposition(x)
```

The writer-trace theorem is universal. The previous reader correctness
claim is *not*: it is still limited to its finite tested conditions.
The old standalone writer test may also include behaviors outside the
model's byte-payload/nonthrowing-callback domain and must not be relabeled
universally verified.

## Published artifacts

The dedicated workflow emits:

- `universal-preservation.json`: explicitly differentiated formal-model,
  source-bridge, and previously finite downstream claims.
- `universal-preservation.intoto.json`: unsigned in-toto Statement v1,
  Test Result v0.1, with only the **executed** proof and verification
  obligations in `passedTests`; downstream claims are *not* fake test runs.
- `preservation.json` and `preservation.intoto.json`: the original finite
  source/trace certificate and its evidence identity.
- `prior-reference.json`: verified earlier workflow and claim lineage.
- `candidate.patch`: exact reversible Git source change, rather than
  a pushed mutation to h11.

Run [GitHub Actions 42680584883](https://github.com/laurajoyhutchins/h11/actions/runs/42680584883)
passed: Lean 4.35.0 proof checking, 25 Python regression tests, the
112-trace regression experiment, old evidence validation, emission and
independent regeneration/verification of both evidence statements, plus
negative controls for forged evidence and a deliberately incorrect writer.

## Reproduction

From a full checkout of `research/contract-preservation-universal`:

```bash
cd research/preservation/formal
lean HexPreservation.lean
cd ../../..
PYTHONPATH=research/preservation python -m unittest \
    discover -s research/preservation -p 'test_*.py' -v

# Requires CPython 3.13, pytest==9.2.0, Git, Lean 4.35.0, GitHub CLI,
# and authentication allowing Actions artifact access.
mkdir -p /tmp/h11-previous /tmp/h11-universal-work
gh api repos/laurajoyhutchins/h11/actions/runs/42667731213 \
    > /tmp/h11-trusted-run.json
gh run download 42667731213 --repo laurajoyhutchins/h11 \
    --name native-contract-evidence --dir /tmp/h11-previous
python research/preservation/run.py \
    --source . --work /tmp/h11-universal-work \
    --prior-artifacts /tmp/h11-previous \
    --trusted-run /tmp/h11-trusted-run.json
export PYTHONPATH=/tmp/h11-universal-work/baseline
args=(
    --root /tmp/h11-universal-work/baseline
    --baseline /tmp/h11-universal-work/baseline
    --candidate /tmp/h11-universal-work/candidate
    --work /tmp/h11-universal-work
    --prior-artifacts /tmp/h11-previous
    --trusted-run /tmp/h11-trusted-run.json
)
python research/preservation/universal.py emit "${args[@]}"
python research/preservation/universal.py verify "${args[@]}"
```

## Completion criterion

The proven result is **all finite byte-payload sequences in the abstract
writer model**, with a checked Python source bridge and explicit trusted
language/runtime assumptions. It is not a proof of all HTTP behavior or of
future client code. No automatic evidence reuse outside the declared domain
is authorized. The output is unsigned; obtaining a cryptographic provenance
chain would require a signed in-toto envelope and trusted CI identity.
