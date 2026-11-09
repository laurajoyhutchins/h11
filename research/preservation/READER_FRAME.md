# Reader noninterference as a checkable source frame

This experiment gives a deliberately constrained answer to the question:

> If `ChunkedWriter.send_data` changes, why should previously verified
> reader observations remain valid without running the candidate reader?

The answer is **not** that Python globally forbids interference. It does
not. Instead, we identify a reader-only program whose source dependencies
cannot reach the writer through its checked import graph, then show that
the reader-only program is unchanged across the Git transformation.

## The actual dependency boundary

The closure from `h11._readers` is pinned to these seven real source files:

```text
h11/_readers.py
  ├─ _abnf.py
  ├─ _events.py
  │   ├─ _headers.py
  │   └─ _util.py
  ├─ _receivebuffer.py
  └─ _state.py
```

The transitive closure has precisely seven modules:
`_readers`, `_abnf`, `_events`, `_headers`, `_util`,
`_receivebuffer`, and `_state`. The verifier computes imports from
Python's AST rather than accepting this diagram on trust.

For the actual scratch Git transformation, it also checks:

- candidate HEAD directly descends from baseline HEAD;
- the only changed tracked path is `h11/_writers.py`, and only
  `ChunkedWriter.send_data` differs in the module AST;
- each of the seven closure modules has identical **Git blob bytes**;
- reader closure imports are in the enumerated set, with no imports of
  `_writers` or `_connection`;
- known dynamic import, introspection and runtime evaluation constructs
  are rejected by the conservative static checker.

A source change that exceeds the supported subset is rejected; the
checker does not optimistically infer that it is harmless.

## Why an isolated loader is necessary

Normal `import h11` runs `h11/__init__.py`, which imports
`_connection`, which in turn imports `_writers`. Consequently the
ordinary package import closure includes the modified writer.

The verified reader-only environment is different and deliberately
constructed. In a fresh Python process the harness:

1. Installs an inert package stub named `h11` whose `__path__`
   points to the actual checked-out source, without executing
   `h11/__init__.py`.
2. Installs an import guard that rejects any `h11.*` module outside
   the seven-module closure.
3. Imports the **real** `ChunkedReader`, `ReceiveBuffer`, `Data`
   and `EndOfMessage`, not mocked copies.
4. Reads the four exact input fixtures and six fragmentation sizes
   from the previously verified Git source.
5. Replays all 24 combinations on **the original reader only**;
   verifies payload, trailers and unread suffix.
6. Confirms no writer module was imported. Reexecutes this sealed
   baseline in another child process before accepting the certificate.

No candidate reader is executed. The closure identity check establishes
that the candidate retains the same reader-only program within the
declared loader and interpreter semantics.

## Relation to the Lean theorem

The pinned Lean proof contains the additional theorem
`HexPreservation.sharedReaderCongruence`:

[
  W_{\text{new}}(x) = W_{\text{old}}(x)
  \quad\Longrightarrow\quad
  R(W_{\text{new}}(x)) = R(W_{\text{old}}(x)).
]

Here `R` is **one shared pure reader function**. The theorem does not
magically identify separate Python functions or assert that Python module
initialization has no effects. The source frame supplies the separately
checked reason that a shared reader-only program is available in this
restricted environment.

The consequence is preservation of reader/composition evidence **within
this sealed context**, still limited by the scope of the prior finite
observations and by the normal Python language/runtime semantics.

## Negative tests

The source checker rejects new reader imports of `_writers` or
`_connection`, unexpected transitive modules, use of dynamic importing,
reflection, and eval/exec/open. Regression tests construct two real
Git revisions to verify acceptance of a writer-only edit and rejection
of an import that crosses the frame boundary.

The replay verifier rejects missing or duplicated fragment cases, a
different earlier CI run, unexpected loaded modules, package initializer
execution, writer import, or any candidate reader execution. Normal
in-toto, JUnit, Git source, and malformed-proof negative controls are
retained.

## Boundaries that remain unproved

This is **not unrestricted noninterference for ordinary h11 imports**.
The normal initializer loads `_connection` and the writer. This
experiment deliberately avoids that context.

The source closure checker is a conservative analysis of seven pinned
modules, not a complete static semantics of arbitrary Python. The
argument assumes the interpreter and standard-library implementation
conform to Python 3.13, no hostile site code or import hooks, and no
unmodeled external mutation of module globals. The isolated child
process suppresses environment and site startup configuration.

Likewise, Lean proves callback traces equal in its mathematical model;
its Python bridge remains conditional on documented integer/bytes
semantics and byte-observing callbacks. We have **not** established
universal HTTP correctness, normal package contextual equivalence,
or an automatic semantic closure system for arbitrary repositories.

## Source of truth

- `reader_frame.py`: checked transitive import closure, source Git
  equality, replay authentication, and source-frame certificate.
- `sealed_reader.py`: fresh baseline-only reader executor with
  forbidden imports and a fake inert package root.
- `test_reader_frame.py`: static/forged/Git-transaction regressions.
- `formal/HexPreservation.lean`: universal writer equality and
  shared-reader congruence, checked by Lean 4.35.0.
- `.github/workflows/sealed-reader-frame.yml`: reproducible GitHub
  Actions verifier, producing `reader-frame.json`,
  `sealed-reader-observations.json`, and a new in-toto Test Result.

For the exact Python language guarantees and the assumptions not
covered by those guarantees, see [PYTHON_SEMANTICS.md](PYTHON_SEMANTICS.md).
