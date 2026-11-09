# Blind transfer experiment: ItsDangerous

**Status:** completed. The original h11-shaped sibling heuristic did **not** generalize to this independent repository. This is a negative structural result, not a failed execution.

## Frozen protocol

Before examining the target source or executing tests, we pinned:

- Public target: [Pallets ItsDangerous](https://github.com/pallets/itsdangerous)
- Exact source commit: `672971d66a2ef9f85151e53283113f33d642dabd`
- Exact Git tree: `ef4287f82d8234404b58c7b29d38197e1f38e207`
- Original matching rules: unchanged source-only independent sibling pairs and corresponding class-family ranking
- Generic compatibility change: support conventional `src/` package and root-level `tests/` layout, without changing the discovery scoring
- Module selection: `test_<module>.py` must directly import the corresponding production module
- Fault selection: at most two function-scoped `if` condition inversions per selected module, selected deterministically by SHA-256
- Precondition: a passing original upstream test suite
- Classification: original tests only measure sensitivity, not independent contract correctness

Preregistration: [itsdangerous_preregistration.json](itsdangerous_preregistration.json).

## Actual observations

Run: [GitHub Actions 42558585092](https://github.com/laurajoyhutchins/h11/actions/runs/42558585092).

The pinned original Python 3.13 environment passed **297/297** upstream pytest tests. Dependencies included pytest 9.0.2 and freezegun 1.5.5.

The discoverer identified eight production Python modules and five test files. **Zero independent sibling pairs** satisfied the frozen candidate rule. This means the existing `verify()` prototype had no candidate to verify. We did not add a retroactive manual candidate or pretend that this was successful automatic contract identification.

Separately, an entirely mechanical source/test matching step selected five modules and executed condition mutations.

| Automatically chosen module | Mutants tested | Detected as pytest failures | Inconclusive |
| --- | ---: | ---: | ---: |
| `itsdangerous.encoding` | 1 | 1 | 0 |
| `itsdangerous.serializer` | 2 | 2 | 0 |
| `itsdangerous.signer` | 2 | 0 | 2 |
| `itsdangerous.timed` | 2 | 2 | 0 |
| `itsdangerous.url_safe` | 2 | 2 | 0 |
| **Total** | **9** | **7** | **2** |

The two signer mutants generated **both test failures and test setup errors**. They cannot be counted as valid mutation kills under our strict policy. No cleanly executed mutant survived, but the set is small and dominated by conditional inversions, so it is not representative mutation coverage. Some "detected" outcomes reflect raised exceptions rather than independent proof of a behavioral contract.

Original source paths were restored byte-for-byte after each trial. The runner confirmed the worktree clean, the Git commit unchanged, and the exact original tree SHA after the experiment.

Machine-readable observations (including individual lines, original conditions and pytest summaries): [itsdangerous_observed.json](itsdangerous_observed.json). The full JSON was decoded from the corresponding GitHub Actions run logs.

## Interpretation

1. **The original discovery method is structurally too narrow.** A project can expose important independently testable modules through a *vertical* dependency or extension graph, without any pair of independent siblings sharing matching class families.
2. **Existing tests are useful evidence but not a specification.** Automatically finding `test_signer.py` proves the test imports the signer; it does not establish the security semantics of cryptographic signing.
3. **Successful original tests and many killed mutants do not make a contract.** The transfer deliberately reports `TEST_SENSITIVITY_ONLY_NOT_CONTRACT_VERIFICATION`.
4. **No history should be generated from this discovery result.** The attempt did not recover a contract graph that could justify an executable explanatory history.

The next version should consider **test-exercised module closures and implementation inheritance**, not only matching independent sibling modules. This is a hypothesis derived *after* this trial and must be evaluated on a separately pinned, previously unseen repository; otherwise we would be fitting the discovery algorithm to ItsDangerous.

## Research files

- [Blind protocol and pinned revision](itsdangerous_preregistration.json)
- [Generic transfer runner](blind_transfer.py)
- [Observations](itsdangerous_observed.json)
- [Source-only discoverer](../contract_discovery/discover.py)
- [Actions workflow](../../.github/workflows/itsdangerous-transfer.yml)

No changes to `master`, generated history, or target repository.
