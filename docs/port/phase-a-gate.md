<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# Phase A — Analysis & Baseline (Gate report)

Phase A is **analysis only — no code changes**, per AGENTS.md rule 2.
All deliverables (A1–A6) are complete. This file is the phase gate summary.

## Deliverables

| Task | Status | Artifact |
|---|---|---|
| A1 Branch `port/py313` | ✅ | branch exists, `upstream` remote retained |
| A2 Ist-Zustand (deps, Python min, C-extensions, rados/rbd) | ✅ | `baseline/README.md` |
| A3 `pipdeptree` + `pip-audit` baseline | ✅ | `baseline/pipdeptree.txt`, `baseline/pip-audit.txt`, `baseline/installed-packages.txt` |
| A4 Test inventory + reference run | ✅ | `baseline/test-inventory.md`, `baseline/test-baseline-3.13.txt`, `baseline/test-baseline-3.13-passing.txt` |
| A5 Feature matrix (CLI + NBD + REST + exit codes + log format) | ✅ | `feature-matrix.md` |
| A6 Data format & DB schema reference | ✅ | `data-format-schema.md` |

## Key findings that drive Phase C/D work

### Hard blockers (must resolve before any test can run)
1. **`sparsebitfield` 0.2.5 C extension does not build on Python 3.13.**
   The checked-in Cython output (`cimpl/field.c`) accesses the removed
   `PyLongObject.ob_digit` member. The `.pyx` source is clean, so
   regenerating with Cython ≥3.0 is the likely fix (C7). This is
   escalation point #1 — confirmed.
   Impact: 4 core modules (`benji.benji`, `blockuidhistory`, `commands`,
   `nbdserver`) and 10 of 16 unit-test files fail at collection.

### Confirmed deprecation/removal issues (Phase C)
2. **`pkg_resources` removed in setuptools ≥81.** benji uses
   `pkg_resources.resource_filename` (`config.py:14`) and the `ruamel`
   namespace declaration. Migrate to `importlib.resources` + PEP 420
   (C2/C10). Worked around in the baseline venv by pinning `setuptools<81`.
3. **`bottle` 0.12.x imports stdlib `cgi` (removed in 3.13).**
   `benji.restapi` cannot import. REST API is Variante (b) but must at
   least start; raise `bottle` to ≥0.13 and adjust the `<0.13.0` pin
   (escalation #4 — confirmed).
4. **`pyparsing` 2.x imports `sre_constants` (deprecated in 3.12+).**
   Bump to `>=3.1,<4` and re-verify the retention/version grammar (C3,
   escalation #3 — pending verification).
5. **`ruamel.yaml` 0.16** uses `pkg_resources.declare_namespace('ruamel')`
   (deprecated). Bump to `>=0.18,<0.19` (C2).

### Safety-critical byte-parity contracts (must not change)
6. **GCM auth tag is discarded** — `aes_256_gcm.py` uses GCM as a tag-less
   stream cipher (16-byte nonce, tag never written/verified). The port
   MUST reproduce this exactly or restores diverge. See
   `data-format-schema.md` §4.
7. **Crypto envelope byte layout** (RFC 3394 key wrap, PBKDF2-HMAC-SHA512
   32-byte output, ECC ECDH+SHA256 variant) is fully documented in
   `data-format-schema.md` §4 — this is the C6/C8 parity target.
8. **Object key scheme** `{prefix}{md5[0:2]}/{md5[2:4]}/{key}`, `.meta`
   sidecar pairing, BLAKE2b/256 content hash, checksum-based dedup —
   `data-format-schema.md` §3.
9. **Exit-code mapping is non-standard** — `os.EX_*` codes (e.g.
   `KeyboardInterrupt`→66, not 130); exception→code ordering is
   load-bearing (`ScrubbingError` before `IOError`). `feature-matrix.md` §4.
10. **Log format** — structlog processor chain, 4 formatters, stdout/stderr
    split is a contract. `feature-matrix.md` §5.

### Other (non-blocking)
- `diskcache` 5.6.3 — **CVE-2025-69872**, no fix release yet. Monitor/replace.
- Pre-existing bugs in test infra: root `conftest.py:39`
  (`addinivalue_line(markers=...)` wrong signature) and `testcase.py`
  uses `random`. Fix in Phase E.
- DB: block-UID columns are 32-bit `Integer` with 64-bit path
  zero-extension — latent overflow already flagged upstream.

## Environment note

The host has **only Python 3.13.5** (no old interpreter), so the A4
baseline was taken under 3.13 with original pins rather than under the
original 3.7–3.11. The true reference behaviour is captured by the
upstream history and will be locked by the golden-master fixtures (Phase B).

## Phase A gate: GREEN

All analysis tasks complete; no code was modified. The way is clear to
begin **Phase B (Golden-Master Fixtures)** once its prerequisites are met,
and **Phase C (Core Portierung)**, whose first action should be C7
(`sparsebitfield`) to unblock the test suite.
