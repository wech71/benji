<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# Vendored dependencies

This directory holds patched copies of upstream packages that are required
for the Python 3.13+ port but are not (yet) available in a compatible form
on PyPI.  Each entry documents what was changed, why, and the upstream
license.

## sparsebitfield 0.2.5.post1

- **Upstream:** https://github.com/elemental-lf/sparsebitfield (BSD-2-Clause)
- **Original version:** 0.2.5 (PyPI sdist)
- **Vendored version:** `0.2.5.post1` (post-release marker for the py313 fix)

### Why vendored
sparsebitfield 0.2.5 does not build on Python 3.13.  The shipped
Cython-generated `cimpl/field.c` references removed/changed CPython
internals (`PyLongObject.ob_digit`, `_PyLong_AsByteArray` signature,
`_PyGen_SetStopIterationValue`).  See `docs/port/dependency-changes.md`
and `docs/port/phase-a-gate.md` (escalation point #1).

### What changed vs upstream 0.2.5
1. `cimpl/field.pyx`: one Python-2→3 fix in `SparseBitfield.load()`:
   `isinstance(item, (int, long))` → `isinstance(item, int)`.
   (The corresponding patch is preserved at
   `patches/sparsebitfield-0.2.5-py313.patch` for review provenance.)
2. `cimpl/field.c`: regenerated from the patched `.pyx` with
   **Cython 3.0.11**, `language_level=3`.  The new output uses a
   version-guarded `__Pyx_PyLong_Digits` macro (`long_value.ob_digit` on
   Python ≥ 3.12, `ob_digit` on older) and is therefore 3.13-compatible.
   It builds with just a C compiler and setuptools — **Cython is not
   required to install the vendored copy.**
3. `setup.py`: `version` bumped to `0.2.5.post1` so the patched build is
   distinguishable from the broken PyPI 0.2.5.

No behavioural change vs upstream 0.2.5 on Python 3 (`long` was merged into
`int`).

### Install
```bash
pip install vendor/sparsebitfield-0.2.5/
```
or, so pip can resolve it automatically from this directory:
```bash
pip install --find-links vendor/ -e .
```

### Verification
- Builds cleanly on Python 3.13.5 (one benign `-Wsign-compare` warning).
- Upstream test suite (`test/test_bitfield.py`): 17/17 passed.

### Upstream plan
`elemental-lf` maintains both benji and sparsebitfield.  The intended final
form is an upstream `sparsebitfield>=0.2.6` release on PyPI containing the
fix and the regenerated `field.c`.  Once published, remove this vendored
copy, delete `patches/sparsebitfield-0.2.5-py313.patch`, and pin
`sparsebitfield>=0.2.6,<1` in `setup.py`.

### License
BSD-2-Clause — compatible with benji's LGPL-3.0-only.  Original copyright
holders (Steve Stagg, Lars Fenneberg) retained; see `README.md` and
`PKG-INFO` in the vendored tree.
