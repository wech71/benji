<!-- SPDX-License-Identifier: LGPL-3.0-only -->
<!-- AI-assisted development notice: authored with AI assistance (opencode/glm-5.2). -->

# Phase D5 — Error message differences: Cerberus vs Pydantic v2

This document records the differences in validation error messages between
the original Cerberus-based config validation (Python 3.11) and the new
Pydantic v2-based validation (Python 3.13).

## Summary

The **exception type and top-level message are identical**:
`ConfigurationError: Configuration for module {module} is invalid.`

The **log detail lines** differ in wording but convey the same information.
Both implementations log individual field-level errors before raising the
exception. No user-facing behaviour changes — the CLI exit code and the
exception that callers catch are the same.

## Per-case comparison

### 1. Missing required field

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | `configuration.path: required field` | *(not logged — Pydantic raises immediately)* |
| **Exception** | `ConfigurationError: Configuration for module benji.storage.file is invalid.` | same |

**Difference:** Cerberus logs `configuration.path: required field` to the
error log. Pydantic's error is available in the exception's `errors()` list
but is only logged if it appears in `exception.errors()`. In practice the
Pydantic path logs all errors from `exception.errors()` but with different
wording: `path: Field required` instead of `configuration.path: required field`.

### 2. Unknown key (extra field)

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | `configuration.path: required field` (Cerberus reports the missing required field, not the extra key) | `asdasdas: Extra inputs are not permitted` |
| **Exception** | same | same |

**Difference:** Cerberus with `allow_unknown` not set on the `configuration`
sub-schema treats unknown keys differently depending on context. Pydantic
with `extra='forbid'` reports the unknown key explicitly. This is an
improvement — the user gets a clearer error.

### 3. Constraint violation (min/max)

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | *(not logged)* | `bandwidthRead: Input should be greater than or equal to 0` |
| **Exception** | same | same |

**Difference:** Pydantic provides a more descriptive message. Cerberus's
message for constraint violations was sometimes not logged at the field
level.

### 4. Wrong type

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | `configuration.path: must be of string type` | `path: Input should be a valid string` |
| **Exception** | same | same |

**Difference:** Wording only. Cerberus prefixes with `configuration.`;
Pydantic uses the bare field name.

### 5. Missing required field (S3 bucketName)

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | `configuration.bucketName: required field` | *(logged as `bucketName: Field required`)* |
| **Exception** | same | same |

### 6. Regex validation (RBD features)

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | *(not logged at field level)* | `newImageFeatures: Value error, newImageFeatures entries must match ^RBD_FEATURE_.*: 'ASASA'` |
| **Exception** | same | same |

**Difference:** Pydantic provides a more descriptive message that includes
the offending value.

### 7. Excludes/dependencies (crypto config)

| | Cerberus | Pydantic v2 |
|---|---|---|
| **Log** | `configuration.password: required field` | `: Value error, kdfSalt, kdfIterations and password must all be specified together` |
| **Exception** | same | same |

**Difference:** Pydantic reports the dependency group as a model-level
error (empty `loc`), while Cerberus reports it as a missing field on the
specific dependent. Both convey the same requirement.

## Path prefix difference

Cerberus error paths are prefixed with `configuration.` (e.g.,
`configuration.path`). Pydantic error paths use the bare field name (e.g.,
`path`). This is because Cerberus validates a wrapper dict
`{'configuration': config}` while Pydantic validates the config dict
directly.

## Conclusion

All differences are in log message wording, not in validation behaviour or
exception type. The config YAML syntax is unchanged. No user-facing error
messages (the `ConfigurationError` message) changed. The differences are
documented here for completeness per PORTING-TASKS D5.
