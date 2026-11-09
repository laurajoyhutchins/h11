# Python 3.13 semantics for the h11 writer refinement

This note separates three things that should not be conflated:

1. **Specified language/library behavior**: public Python 3.13 contracts used
   to interpret the exact Python ASTs checked by `formal_bridge.py`.
2. **Source obligations**: verified properties of the baseline and scratch
   candidate Git trees, not properties established by Python documentation.
3. **Contextual assumptions**: properties of callers, imports, execution
   environment, and observability that neither the language reference nor
   the Lean theorem establishes.

The proof is universal over *finite `bytes` payload sequences in its model*.
It is not a universal claim about every Python object that h11 might accept.

## Language semantics used by the source bridge

| Python expression or operation | Python 3.13 specification | Status |
| --- | --- | --- |
| `if not data` | Empty built-in sequences are false; a `bytes` object is empty exactly when its length is zero | Specified for genuine `bytes` |
| `len(data)` | `len` returns the length of a sequence; `bytes` is a sequence of integers | Specified for genuine `bytes` |
| `b"%x\\r\\n" % len(data)` | Bytes `%` formatting uses `x` for lowercase hexadecimal; no width, precision, sign flag, or alternate-form flag is requested | Specified for nonnegative integer length |
| `number & 15` | Bitwise AND on nonnegative `int`; this extracts the low four bits, equivalently `number % 16` | Specified integer operation |
| `number >>= 4` | Right shift by four is floor division by `2**4`, equivalently `number // 16` | Specified integer operation |
| `digits[number & 15]` | Indexing `bytes` returns an integer in `0..255`; the 16-byte alphabet supplies the ASCII hexadecimal digit | Specified built-in sequence operation |
| `encoded.append(...)`, `encoded.reverse()`, `bytes(encoded)` | `bytearray` is mutable and supports append/reverse; construction of `bytes` copies the resulting integer byte sequence | Specified built-in sequence operations |
| Call/statement order | Expressions evaluate left to right; each statement executes in its written sequence | Specified evaluation order |

Authoritative sources:

- [Built-in types, truth-value testing](https://docs.python.org/3.13/library/stdtypes.html#truth-value-testing)
- [Built-in functions, `len`](https://docs.python.org/3.13/library/functions.html#len)
- [Built-in types, bitwise integer operations](https://docs.python.org/3.13/library/stdtypes.html#bitwise-operations-on-integer-types)
- [Built-in types, binary sequences and mutable-sequence methods](https://docs.python.org/3.13/library/stdtypes.html#binary-sequence-types-bytes-bytearray-memoryview)
- [Built-in types, printf-style bytes formatting](https://docs.python.org/3.13/library/stdtypes.html#printf-style-bytes-formatting)
- [Language reference, expression evaluation order](https://docs.python.org/3.13/reference/expressions.html#evaluation-order)

Together with the checked AST templates and the Lean arithmetic theorem,
these specifications justify the encoding *value* correspondence for the
declared domain, **conditional on Python 3.13 conforming to its documentation**.
No extra empirical bound on chunk length is needed in the mathematical model.
Of course an actual `bytes` object must fit in finite available memory.

## Not guaranteed by the Python language reference

### 1. The caller supplies actual `bytes`

The `data: bytes` annotation does not by itself enforce that incoming
objects are built-in `bytes`. h11's existing `h11/_writers.py` explicitly
mentions accepting unusual sendfile-style objects that provide a length and
are forwarded to `write`. The proof does **not** quantify over those
objects, their overloaded truth values, their lengths, or their side effects.

If they are allowed at runtime, they remain **UNSUPPORTED BY THIS PROOF**,
even if the new writer may happen to work for some of them.

### 2. Equal callback traces are not arbitrary contextual equivalence

Lean proves equality of an ordered list of callback arguments. The bridge
assumes a callback that observes only those byte values and their order,
does not throw, does not mutate the payload, and does not inspect stack
frames, function code objects, timing, or allocation behavior. A callback
with arbitrary Python side effects can distinguish the two implementations
despite receiving equal arguments.

Memory exhaustion and exception timing are outside the Lean model.

### 3. Reader noninterference is a separate frame obligation

Only `ChunkedWriter.send_data` changes in the scratch candidate Git tree,
and the baseline reader source remains unchanged. But Python permits
modification of module namespaces, `sys.modules` caching/reloading, import
hooks, runtime introspection, and function `__code__` inspection. Therefore
**unchanged reader source does not, by itself, prove unchanged execution
in every surrounding Python context**.

For the previously tested reader/composition cases, the transported
conclusion explicitly assumes:

- identical input byte streams reach the same reader entrypoints;
- no code path relevant to those observations introspects or monkeypatches
  `ChunkedWriter.send_data` or varies import-time behavior by its body;
- the earlier runtime and module initialization assumptions still apply.

The earlier whole-package manifest **changes** when the writer changes,
so that manifest cannot itself establish this frame condition. The
candidate reader tests are intentionally not rerun.

Authoritative sources for the limits of this inference:

- [Python data model, user-defined functions and `__code__`](https://docs.python.org/3.13/reference/datamodel.html)
- [Python import system, mutable module cache and import hooks](https://docs.python.org/3.13/reference/import.html)
- [Python execution model, name binding and global namespaces](https://docs.python.org/3.13/reference/executionmodel.html)

## Final claim classification

| Claim | Basis | What survives |
| --- | --- | --- |
| Hex digit representation | Lean 4.35.0 + documented Python integer/bytes semantics + exact AST templates | Universal *within the finite built-in-`bytes` input model* |
| Ordered chunk writer callback arguments | Lean theorem + documented built-ins + pure observer assumption | Universal *within the trace observation model* |
| Existing reader observations | Prior Git/JUnit/in-toto evidence, plus explicit contextual frame assumption | Previously tested inputs only; conditional |
| Existing composition observations | Writer trace equality + prior finite reader evidence + frame assumption | The 24 recorded old composition cases; conditional |
| Arbitrary objects, introspective callbacks, module monkeypatches, error timing, all HTTP correctness | Not established | **UNSUPPORTED** |

The source documentation supports **language semantics**, not a proof
of Python's entire implementation or unrestricted downstream independence.
