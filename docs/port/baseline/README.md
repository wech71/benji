<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# Phase A2 — Ist-Zustand / Baseline (Analysis only, no code changes)

Captured on the `port/py313` branch against Python 3.13.5
(Debian 13 Trixie host). This document records the *as-is* state of the
codebase and its dependencies before any porting work begins, so that later
phases can verify nothing regressed.

## Environment

| Item | Value |
|---|---|
| Host Python | 3.13.5 (`/usr/bin/python3.13`) |
| Old Python for baseline runs | **Not available.** Only 3.13 is installed; a separate 3.7–3.11 interpreter is not present on this host. The Phase-A baseline is therefore taken under 3.13 with the *original* dependency pins from `setup.py`. |
| Project venv | `/tmp/opencode/benji-venv` (created with `venv --copies` because the workspace mount forbids symlinks). Not installed system-wide, per AGENTS.md. |
| benji itself | Run via `PYTHONPATH=src` (editable install into the mount is impossible: the mount forbids writing `egg-info`). |
| Ceph bindings | `rados` / `rbd` importable from the **system** interpreter only (Debian `python3-rados`, `python3-rbd`). The isolated venv does not see them; this is a venv artefact, not a porting problem. System libs `librados.so.2`, `librbd.so.1`, `libpq.so.5` are present. |
| `libiscsi` | Not installed. `benji.io.iscsi` is out of scope (see scope table) and is expected to fail import. |

## Declared dependencies (from `setup.py` install_requires) and installed versions

The venv was populated by resolving the *original* `setup.py` pins under
3.13. Versions actually resolved are recorded in
`installed-packages.txt`. Highlights / pin-relevant observations:

| Dependency | setup.py pin | Resolved (3.13) | Note |
|---|---|---|---|
| ruamel.yaml | `>0.16,<0.17` | 0.16.13 | Last 0.16. Uses implicit `ruamel` namespace pkg → `pkg_resources.declare_namespace` deprecation. C2 raises to `>=0.18,<0.19`. |
| attrs | `>=21.4.0,<22` | 21.4.0 | Pinned very low. C3 raises to `>=23,<25`. |
| pyparsing | `>=2.3.0,<3` | 2.4.7 | 2.x imports `sre_constants` (deprecated in 3.12+). C3 raises to `>=3.1,<4`; grammar must be re-verified (escalation #3). |
| pycryptodome | `>=3.6.1,<4` | 3.23.0 | OK. Envelope byte-parity to be verified in C6 against B3 vectors (escalation #2). |
| sparsebitfield | `>=0.2.5,<1` | **0.2.5 — fails to build** | C extension, escalation #1 (see below). |
| cerberus | `>=1.2,<2` | 1.3.8 | To be replaced by Pydantic v2 in Phase D. |
| sqlalchemy | `>=2.0.7,<3` | 2.0.51 | Already 2.0; C4 cleans remaining 1.x-style deprecations. |
| psycopg2-binary | `>=2.7.4,<3` | 2.9.12 | py3.13 wheel available. C5 keeps psycopg2-binary. |
| diskcache | (unpinned upper) | 5.6.3 | **CVE-2025-69872** (see pip-audit). |
| bottle (rest-api extra) | `>=0.12.16,<0.13.0` | 0.12.25 | Imports `cgi` → **fails on 3.13** (`cgi` removed). Escalation #4. |
| webargs (rest-api extra) | `>=8.0.1,<8.1.0` | 8.0.1 | Pulls `marshmallow` 4.x; not yet import-verified under 3.13. |
| gunicorn (rest-api extra) | `>=20.1.0,<21` | 20.1.0 | Not yet import-verified under 3.13. |

### Extra packages installed for analysis/dev
`parameterized`, `pytest`, `pytest-cov`, `pipdeptree`, `pip-audit`,
`boto3`, `zstandard`, `b2sdk<2`, `blinker`, `prometheus_client`,
`requests`.

## Import smoke test (41 modules, Python 3.13)

Source: `import-smoke.txt`. Summary: **33/41 import OK, 8 fail**.

Failure causes (each is a porting work item, not a surprise):

| Module(s) | Cause | Phase / Task |
|---|---|---|
| `benji.benji`, `benji.blockuidhistory`, `benji.commands`, `benji.nbdserver` | `No module named 'sparsebitfield'` (C ext won't build on 3.13) | C7 (escalation #1) |
| `benji.restapi` | `No module named 'cgi'` — pulled transitively by `bottle` 0.12.x | C (rest-api deps), escalation #4 |
| `benji.io.iscsi` | `No module named 'libiscsi'` — out of scope, expected | — |
| `benji.io.rbd`, `benji.io.rbdaio` | `No module named 'rados'` — venv isolation only; bindings exist system-wide | — (venv artefact) |

### Deprecation warnings observed at import time
- `benji.config` (and anything importing it): `pkg_resources.declare_namespace('ruamel')` deprecation — caused by ruamel.yaml 0.16. Fixed by C2.
- `benji.database` / `benji.retentionfilter`: `module 'sre_constants' is deprecated` — caused by pyparsing 2.x. Fixed by C3.
- `pkg_resources` itself: deprecated as an API; benji uses it in **2 files** (`config.py` via `resource_filename`, and the namespace). Needs migration to `importlib.resources` (Phase C, add to C10).

## Escalation points confirmed (Phase A)

These match the "Eskalationspunkte" list in PORTING-TASKS.md. Reporting now,
no fix attempted (Phase A = analysis only).

1. **`sparsebitfield` Py3.13 build (escalation #1) — CONFIRMED.**
   `sparsebitfield` 0.2.5 is a Cython C extension (a fork by elemental-lf,
   the same author as benji, BSD-licensed). The *pre-generated* `cimpl/field.c`
   accesses the removed `PyLongObject.ob_digit` member directly (16+ sites),
   which is gone in CPython 3.12+. The `.pyx` source contains **no** direct
   `ob_digit` access, so the failure is in the checked-in Cython output, not
   the source logic. **Candidate fix for C7:** regenerate `field.c` with a
   modern Cython (≥3.0) that emits 3.12+-compatible long-access code, or
   build from `.pyx` with `--use-cython`. Upstream is elemental-lf's own fork,
   so a patched release is feasible. To be decided in Phase C; not acted on
   here.

2. **`pycryptodome` envelope byte-parity (escalation #2) — pending.**
   pycryptodome 3.23.0 imports fine. Parity must be verified against B3
   test vectors in Phase B/C (C6/C8). No anomaly found yet.

3. **`pyparsing` 3.x grammar (escalation #3) — pending.**
   Current pin is 2.x; `sre_constants` deprecation confirms a 3.x bump is
   needed. Grammar re-verification deferred to C3.

4. **REST-API deps under 3.13 (escalation #4) — CONFIRMED.**
   `bottle` 0.12.25 imports the stdlib `cgi` module, removed in Python 3.13.
   The REST API is Variante (b): keep runnable + smoke-test only. To make it
   import at all, `bottle` must be raised to ≥0.13 (which dropped `cgi`) and
   the `<0.13.0` upper pin adjusted; `webargs`/`gunicorn` to be re-checked.
   This is a Phase C task; not acted on here.

5. **Pydantic v2 vs Cerberus parity (escalation #5) — pending.**
   Deferred to Phase D; Cerberus 1.3.8 currently imports and works.

## Other findings (not on the escalation list, to be addressed in Phase C)

- **`pkg_resources` removal.** setuptools ≥81 (2025) removes `pkg_resources`.
  benji uses `pkg_resources.resource_filename` in `config.py` and relies on
  the `ruamel` namespace package declaration. Both must migrate to
  `importlib.resources` and PEP 420 namespace packages. Added to C10
  (deprecation cleanup) / C2 (ruamel bump).
- **Security:** `diskcache` 5.6.3 has CVE-2025-69872 (no fix release at
  baseline time). Tracked in `pip-audit.txt`; to be monitored/replaced if no
  fix lands before Phase C.

## Artifacts in this directory

- `installed-packages.txt` — frozen `pip freeze` of the baseline venv.
- `pipdeptree.txt` — full dependency tree (no conflicts, exit 0).
- `pip-audit.txt` — vulnerability scan (1 vuln: diskcache CVE-2025-69872).
- `import-smoke.txt` — per-module import results + deprecation warnings.

## Gate

Phase A is analysis only. No code was changed. Proceeding to A3/A4/A5/A6.
