<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# Phase A4 — Test inventory & baseline run (Analysis only)

## Constraint

"Bestehende Tests inventarisieren, unter altem Python laufen lassen, Ergebnis
als Referenz speichern." **No old Python is available on this host** — only
3.13.5. The baseline is therefore taken under Python 3.13 with the *original*
`setup.py` dependency pins. This is acceptable for A4 because the goal is a
reproducible reference; the original behaviour under 3.7–3.11 is captured in
the upstream repository history and the golden-master fixtures (Phase B).

## Test inventory (`src/benji/tests/`)

| File | Collected | Status under 3.13 (orig pins) | Blocker |
|---|---|---|---|
| `test_aes_keywrap.py` | 2 | PASS | — |
| `test_blockhash.py` | 3 | PASS | — |
| `test_dicthhmac.py` | 10 | PASS | — |
| `test_transform_ecc.py` | 5 | PASS | — |
| `test_retentionfilter.py` | 7 | PASS (pyparsing 2.x `sre_constants` DeprecationWarning) | — |
| `test_keys_exist.py` | 3 | collection warns (`TestClass` has `__init__`) | — |
| `test_blockuidhistory.py` | 2 | COLLECTION ERROR | `sparsebitfield` |
| `test_config.py` | 14 | COLLECTION ERROR | `sparsebitfield` (via `benji.benji`/`benji.config` chain) |
| `test_database.py` | 15 | COLLECTION ERROR | `sparsebitfield` |
| `test_import_export.py` | 5 | COLLECTION ERROR | `sparsebitfield` |
| `test_nbd.py` | 0 (parametrised at runtime) | COLLECTION ERROR | `sparsebitfield` |
| `test_smoketest.py` | 1 | COLLECTION ERROR | `sparsebitfield` |
| `test_store.py` | 6 | COLLECTION ERROR | `sparsebitfield` |
| `storage/test_b2.py` | 0 (parametrised) | COLLECTION ERROR | `sparsebitfield` |
| `storage/test_file.py` | 0 (parametrised) | COLLECTION ERROR | `sparsebitfield` |
| `storage/test_s3.py` | 0 (parametrised) | COLLECTION ERROR | `sparsebitfield` |

Integration tests (podman-driven, root `conftest.py` + `tests/integration/`)
are out of scope for the unit-test baseline; they are exercised by
`run-integration-tests.sh` in Phase E/F.

## Baseline run result (reference)

- **Unblocked subset (5 files):** `39 passed, 3 warnings in 92.65s`
  Warnings: `pkg_resources` deprecation (`config.py`), `ruamel` namespace
  deprecation, `pyparsing` `sre_constants` deprecation.
- **Full suite:** collection interrupted — 10 errors, all
  `ModuleNotFoundError: No module named 'sparsebitfield'` (the C extension
  does not build on 3.13; see A2 / escalation #1).

Artifacts:
- `test-baseline-3.13.txt` — full-suite run (10 collection errors).
- `test-baseline-3.13-passing.txt` — unblocked subset (39 passed).

## Pre-existing issues found in the test infrastructure (Phase A, no fix)

1. **Root `conftest.py:39` is broken under modern pytest.**
   `config.addinivalue_line(markers=...)` passes an unexpected keyword
   argument; the correct call is
   `config.addinivalue_line("markers", "integration: ...")`. This causes an
   `INTERNALERROR` before any test runs. Worked around here with
   `--noconftest`. To be fixed in Phase E (test infra).
2. **`testcase.py` uses `random`** (`random.choices`, `random.getrandbits`)
   for test data. This is pre-existing and predates the determinism rule
   (which targets golden-master fixtures). Flagged for review; not changed.
3. **`test_keys_exist.py:6` `TestClass`** has an `__init__`, so pytest cannot
   collect it — emits `PytestCollectionWarning`. Pre-existing.

## Gate

The single hard blocker for the unit-test baseline is `sparsebitfield`
(escalation #1, A2). Once C7 resolves it, the full suite must be re-run and
must reach the same 39+ passing tests with no new failures. Phase A is
analysis only — no code changed.
