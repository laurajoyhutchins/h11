# Contract preservation under a real implementation change

This experiment replaces a chunked writer's Python integer-to-hex formatting
with a digit-by-digit bitwise encoder in a **disposable local Git commit**.
No production h11 source is pushed or edited on the research branch.

The baseline and candidate are two real Git trees. The verifier enforces that
their *only* source change is the body of `ChunkedWriter.send_data`.
The candidate does not rerun reader or reader/writer-composition tests.

## Verification obligations

1. Generate an explicit, deterministic, 108-trace finite corpus of valid
   sequences of HTTP Data events followed by EndOfMessage.
2. Run the **baseline writer** with an ordered, nonthrowing byte-collecting
   callback, then run the **baseline reader** on each resulting wire message at
   segment sizes 1, 7, 257 and 8192. Check payloads, trailers and unread suffix.
3. Run the **candidate writer only** on exactly the same corpus.
4. Check that the complete ordered *write-callback traces* are identical for
   each input, not merely the concatenated output.
5. Check all other Git-tracked source paths are identical and that the only
   Python AST difference is inside `ChunkedWriter.send_data`.
6. Apply the pure-context congruence rule over each input in the corpus:
   if `W_old(x) = W_new(x)` and `R` is the unchanged deterministic
   reader, then `R(W_old(x)) = R(W_new(x))`. Carry the bounded
   composition observation without calling the candidate reader.
7. Corrupt an independent writer fixture and a recorded observation. Each
   must prevent a preservation certificate from being issued.

The emitted `preservation.json` distinguishes **freshly tested writer
equivalence** from **source-identity carried reader evidence** and a **derived
composition claim**. It records every trace's observed hash and both Git OIDs.

## What this establishes

**Within the finite, explicit corpus and restricted execution context**:
a materially changed writer method preserves a bounded, independently
observed downstream composition claim without rerunning the downstream
component against the candidate implementation.

It does *not* prove equivalence for arbitrary data lengths, arbitrary
callback effects, all possible Python contexts, or unrestricted runtime
dependencies. Even a syntactically restricted method change may have
unexamined behavior outside the corpus. This is a mechanically checked
finite observation certificate plus a composition rule, not formal
end-to-end refinement of Python programs.

The experiment intentionally avoids adding a new contract service, database,
dependency manager, or executor. It uses Git commits, Python's AST, unittest
and immutable JSON observations. The certificate can later be carried in a
signed in-toto envelope, but is currently **unsigned**.

## Reproduce

From a checkout of `research/contract-preservation`:

```bash
PYTHONPATH=research/preservation python -m unittest -v \
    discover -s research/preservation -p 'test_*.py'
mkdir -p /tmp/h11-contract-preservation
python research/preservation/run.py --source . \
    --work /tmp/h11-contract-preservation
```


The runner uses three local Git clones: unchanged baseline, real method
refactoring, and a knowingly incorrect writer mutation. It produces the
two observations and a certificate only for the valid refactoring.
