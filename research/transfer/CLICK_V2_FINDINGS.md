# Preregistered Click transfer: contract discovery v2

## What was frozen before inspecting Click

Target: public repository pallets/click, commit `8abb77a8432e03ed14a95f972b44f905279415a7`. See [frozen protocol](click_v2_preregistration.json). No Click source was inspected before that protocol was committed.

The experiment retains the original sibling-pair rule unchanged and adds two generic structural candidate families:

- **Test-import-observed module closures:** production submodules explicitly imported by original test modules (including statically reachable test helpers), and their runtime import closures.
- **Extension boundaries:** explicitly resolvable class inheritance, including within-module subclasses and subclasses of imported classes.

Both kinds are **candidates only**. A test importing a module does not prove it executes the module's behavior. Inheritance is not evidence of behavioral substitutability.

## Results

| Pinned repository | Production modules | Test files | Sibling pairs | Test-import closures | Inheritance edges | Cross-module inheritance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| h11 | 11 | 9 | 1 | 8 | 27 | 15 |
| ItsDangerous | 8 | 5 | 0 | 6 | 14 | 5 |
| Click (previously unseen) | 17 | 43 | 0 | 12 | 44 | 0 |

Click produced 56 structural candidates, while the old sibling-pair rule still produced zero. Click also had 23 facade-only tests, which were not attributed to private modules, and 19 unresolved class-base expressions, for which the analyzer did not invent ancestry edges. Class inheritance in Click was exclusively within modules according to this conservative static analysis.

All 56 Click candidate entries returned `INSUFFICIENT_EVIDENCE` when passed to the generic verifier without independently supplied oracles. This was a required fail-closed control, not an error.

The discovery output for Click was deterministic across two fresh invocations and had SHA-256 `758f7f2a631076e736784a18a155c7e3ceed370c08e0358116600485693707df`. The workflow checked the Git checkout remained clean and at the pinned commit.

## Reproduction

From the evidence branch, the standard-library commands are:

```bash
python research/contract_discovery/discover_v2.py /checkout/click \
  --package click --source-dir src --tests tests \
  --output /tmp/click-discovery.json

python research/contract_verify/verify.py /checkout/click \
  --discovery /tmp/click-discovery.json \
  --output /tmp/click-no-oracles.json
```

With no independent oracle plan, the second command must not report that any of the candidates are verified.

The full reproducible multi-repository run is in [GitHub Actions](https://github.com/laurajoyhutchins/h11/actions/runs/42559614934). Machine-readable counts and evidence hashes are in [click_v2_observed_summary.json](click_v2_observed_summary.json).

## Regression and interpretation

The generic toy package tests exercise explicit imported inheritance, module aliases, within-module inheritance, facade-only tests, determinism, ambiguous bases, and preservation of the old sibling heuristic. The existing h11 and ItsDangerous source-only regressions also passed.

The generic verifier was extended to recognize the two new kinds of candidate while preserving its no-oracle refusal. A separate toy package demonstrated actual bounded verification of both a test-import closure and a derived-class boundary using independently supplied assertion oracles and mutations; those are **toy package results**, not Click behavioral verification.

**The generalization result is narrower but real:** the old structural pattern was too specialized; the broader AST rules yield source-backed candidates in an unfamiliar package without human-chosen module names. We have *not* shown automatically inferred semantic contracts or correctness of the candidate ordering.

Remaining limitations: only two additional repositories have been tested after h11; static test imports are not actual coverage; complex dynamic imports and aliases can evade resolution; runtime package initialization can add dependencies; extension edges can carry no meaningful guarantees; full source-only JSON is reproducible by command but was not uploaded as a GitHub Actions artifact.

Next appropriate investigation: use independent oracles on a candidate selected by *frozen* scoring rules in a new held-out repository, with fault injection; compare against original tests without tailoring behavior to the repository.

Original source and existing contract-generated branches were not modified.
