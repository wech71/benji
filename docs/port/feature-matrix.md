<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# benji Feature Matrix — Drop-in Replacement Acceptance Checklist

This document is the **exhaustive, externally-observable behaviour contract** for the
benji → Python 3.13 port. Phase H will tick each item here to certify the port is a
drop-in replacement. All references are `file:line` against the *original* source tree
under `src/benji/`.

Static analysis was performed against:

- `src/benji/scripts/benji.py` (CLI entry point / argparse)
- `src/benji/commands.py` (command implementations)
- `src/benji/nbdserver.py` (NBD server)
- `src/benji/restapi.py` (REST API server, bottle/gunicorn)
- `src/benji/helpers/restapi.py` (REST client helper)
- `src/benji/logging.py` (structlog configuration)
- `src/benji/exception.py` (exception → exit-code mapping)
- `src/benji/versions.py` (version constants)

> **Scope note (from AGENTS.md / PORTING-TASKS.md):** The REST API is "Variante b" —
> kept runnable and smoke-tested only. The NBD server **does not** depend on the REST
> API. Storage backends in scope: S3 (MinIO) and file. Databases in scope: SQLite and
> PostgreSQL.

---

## 1. CLI commands

The entry point is `src/benji/scripts/benji.py:main()` (benji.py:43). It builds a single
`argparse.ArgumentParser` with `allow_abbrev=False` (benji.py:51) — option prefixes are
**not** auto-completed, exact spelling is required. `argcomplete` is enabled
(benji.py:11, benji.py:286); the `# PYTHON_ARGCOMPLETE_OK` marker is at benji.py:3.

### 1.1 Global options (apply before the subcommand)

| Option | Short | Takes arg | Default | Description | Location |
|---|---|---|---|---|---|
| `--config-file` | `-c` | yes (str) | `None` | Non-default configuration file. If the file is not found the process exits `EX_USAGE` (64). | benji.py:53 |
| `--machine-output` | `-m` | flag | `False` | Enable machine-readable JSON output (switches console formatter to `json`). | benji.py:54-58 |
| `--log-level` | — | yes (choices) | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. | benji.py:59-62 |
| `--no-color` | — | flag | `False` | Disable colour in console logging (switches formatter to `console-plain`). | benji.py:63-66 |

The root parser uses `formatter_class=argparse.ArgumentDefaultsHelpFormatter`, so
`ArgumentDefaultsHelpFormatter` is in effect for the global help **and** for the
subparsers that explicitly set it (see notes per subcommand below).

If no subcommand is given, usage is printed and the process exits `EX_USAGE` (64)
(benji.py:289-291).

Environment variables observed by the entry point:

- `BENJI_EXPERIMENTAL=1` — enables the experimental `rest-api` subcommand (benji.py:49).
- `BENJI_DEBUG_SQL=1` — raises the `sqlalchemy.engine` logger to `INFO` (logging.py:253).

### 1.2 Subcommands

`subparsers_root = parser.add_subparsers(title='commands')` (benji.py:68). There are no
sub-subcommands; every command is a flat leaf under the root. Each subcommand sets
`func=<name>` which dispatches to `Commands.<name>` (commands.py:24).

Legend: **A** = takes an argument; **F** = flag (store_true); **R** = repeatable
(`action='append'` / `nargs='+'`); **REQ** = positional/required. Defaults shown in
parentheses where non-trivial.

| # | Subcommand | Options / flags | Positionals | Description | func | Location |
|---|---|---|---|---|---|---|
| 1 | `backup` | `-u/--uid <str>` (A, def None), `-s/--snapshot <str>` (A, def `''`), `-r/--rbd-hints <str>` (A, def None), `-f/--base-version <str>` (A, dest=`base_version_uid`, def None), `-b/--block-size <int>` (A, def None), `-l/--label <label>` (A, **R**, dest=`labels`, def None), `-S/--storage <str>` (A, def `''`) | `source` (REQ), `volume` (REQ) | Perform a backup of `source` into `volume`. | `backup` | benji.py:71-91 |
| 2 | `batch-deep-scrub` | `-p/--block-percentage <int 1..100>` (A, def 100), `-P/--version-percentage <int 1..100>` (A, def 100), `-g/--group_label <str>` (A, def None) | `filter_expression` (optional, def None) | Check data **and** metadata integrity of multiple versions at once. Uses `ArgumentDefaultsHelpFormatter`. | `batch_deep_scrub` | benji.py:94-109 |
| 3 | `batch-scrub` | `-p/--block-percentage <int 1..100>` (A, def 100), `-P/--version-percentage <int 1..100>` (A, def 100), `-g/--group_label <str>` (A, def None) | `filter_expression` (optional, def None) | Check block existence **and** metadata integrity of multiple versions at once. Uses `ArgumentDefaultsHelpFormatter`. | `batch_scrub` | benji.py:112-127 |
| 4 | `cleanup` | `--override-lock` (F) | — | Cleanup no longer referenced blocks. | `cleanup` | benji.py:130-132 |
| 5 | `completion` | — | `shell` (REQ, choices: `bash`, `tcsh`) | Emit autocompletion script (via `argcomplete.shellcode`). Exits `EX_OK` (0) directly. | `completion` | benji.py:135-137 |
| 6 | `database-init` | — | — | Initialize the database (does not delete existing tables/data). | `database_init` | benji.py:140-142 |
| 7 | `database-migrate` | — | — | Migrate an existing database to a new schema revision. | `database_migrate` | benji.py:145-146 |
| 8 | `deep-scrub` | `-s/--source <str>` (A, def None), `-p/--block-percentage <int 1..100>` (A, def 100) | `version_uid` (REQ) | Check a version's data and metadata integrity (optionally compare against `source`). Uses `ArgumentDefaultsHelpFormatter`. | `deep_scrub` | benji.py:149-159 |
| 9 | `enforce` | `--dry-run` (F), `-k/--keep-metadata-backup` (F), `-g/--group_label <str>` (A, def None) | `rules_spec` (REQ), `filter_expression` (optional, def None) | Enforce a retention policy. | `enforce_retention_policy` | benji.py:162-168 |
| 10 | `label` | — | `version_uid` (REQ), `labels` (REQ, `nargs='+'`) | Add/remove labels on a version (labels use `+key=val` / `-key` syntax parsed by `InputValidation.parse_and_validate_labels`). | `label` | benji.py:171-174 |
| 11 | `ls` | `-l/--include-labels` (F), `-s/--include-stats` (F) | `filter_expression` (optional, def None) | List versions. | `ls` | benji.py:177-181 |
| 12 | `metadata-backup` | `-f/--force` (F) | `filter_expression` (REQ) | Back up the metadata of one or more versions. | `metadata_backup` | benji.py:184-187 |
| 13 | `metadata-export` | `-f/--force` (F), `-o/--output-file <str>` (A, def None) | `filter_expression` (optional, def None) | Export version metadata to file or stdout. | `metadata_export` | benji.py:190-195 |
| 14 | `metadata-import` | `-i/--input-file <str>` (A, def None) | — | Import version metadata from file or stdin. | `metadata_import` | benji.py:198-201 |
| 15 | `metadata-ls` | `-S/--storage <str>` (A, def None) | — | List the version metadata backups present in storage. | `metadata_ls` | benji.py:204-206 |
| 16 | `metadata-restore` | `-S/--storage <str>` (A, def None) | `version_uids` (REQ, metavar=`VERSION_UID`, `nargs='+'`) | Restore the metadata of one or more versions. | `metadata_restore` | benji.py:209-212 |
| 17 | `nbd` | `-a/--bind-address <str>` (A, def `127.0.0.1`), `-p/--bind-port <str>` (A, def `10809` — **string**, not int), `-r/--read-only` (F, def False), `-d/--discard-changes` (F, def False) | — | Start an NBD server. Uses `ArgumentDefaultsHelpFormatter`. | `nbd` | benji.py:215-222 |
| 18 | `protect` | — | `version_uids` (REQ, metavar=`version_uid`, `nargs='+'`) | Protect one or more versions. | `protect` | benji.py:225-227 |
| 19 | `restore` | `-s/--sparse` (F), `-f/--force` (F), `-d/--database-less` (F), `-S/--storage <str>` (A, def None) | `version_uid` (REQ), `destination` (REQ) | Restore a backup. `--storage` is only legal with `--database-less` (commands.py:74-75). | `restore` | benji.py:230-237 |
| 20 | `rm` | `-f/--force` (F), `-k/--keep-metadata-backup` (F), `--override-lock` (F) | `version_uids` (REQ, metavar=`version_uid`, `nargs='+'`) | Remove one or more versions. | `rm` | benji.py:240-245 |
| 21 | `scrub` | `-p/--block-percentage <int 1..100>` (A, def 100) | `version_uid` (REQ) | Check a version's block existence and metadata integrity. Uses `ArgumentDefaultsHelpFormatter`. | `scrub` | benji.py:248-257 |
| 22 | `storage-stats` | — | `storage_name` (optional, def None) | Show storage statistics. | `storage_stats` | benji.py:260-262 |
| 23 | `storage-usage` | — | `filter_expression` (optional, def None) | Provide storage usage statistics (the `du` command). | `storage_usage` | benji.py:282-284 |
| 24 | `unprotect` | — | `version_uids` (REQ, metavar=`version_uid`, `nargs='+'`) | Unprotect one or more versions. | `unprotect` | benji.py:265-267 |
| 25 | `version-info` | — | — | Program version information. | `version_info` | benji.py:270-271 |
| 26 | `rest-api` *(experimental)* | `-a/--bind-address <str>` (A, def `127.0.0.1`), `-p/--bind-port <int>` (A, def 8080), `--threads <int>` (A, def 1) | — | Start REST API server. **Only registered when `BENJI_EXPERIMENTAL=1`.** | `rest_api` | benji.py:274-279 |

Notes / gotchas to preserve exactly:

- **`nbd --bind-port`** is parsed as a **string** (no `type=int`) with default `10809`
  (benji.py:219). It is forwarded as a string into the asyncio `start_server` call
  (commands.py:350, nbdserver.py:393-397). Do not "fix" this to an int in the port
  without verifying asyncio still accepts the string port.
- **`rest-api --bind-port`** *is* `type=int` with default `8080` (benji.py:278).
- Short/long spelling is a contract: `--group_label` uses a **single underscore**
  (benji.py:107, benji.py:125, benji.py:165) while everything else uses hyphens.
- `backup -l/--label` is `action='append'` (repeatable); `label`/`protect`/`unprotect`/
  `rm`/`metadata-restore` use `nargs='+'`.
- `backup` positional order is `source` then `volume` (benji.py:89-90); `restore`
  positional order is `version_uid` then `destination` (benji.py:235-236).
- `integer_range(1, 100)` (benji.py:28-40) validates percentage options; out-of-range
  raises `argparse.ArgumentTypeError` → argparse prints usage and exits **2** (argparse
  default for argument errors).
- `completion` short-circuits and exits `EX_OK` (0) before any config/logging setup
  (benji.py:293-295).

---

## 2. NBD server

Implemented in `src/benji/nbdserver.py` (class `NbdServer`, nbdserver.py:51). Invoked
via the CLI subcommand **`nbd`** (see §1.2 row 17). The command handler is
`Commands.nbd` (commands.py:347-353), which constructs `BenjiStore(benji_obj)` and
`NbdServer(addr, store, read_only, discard_changes)` then calls `server.serve_forever()`.

### 2.1 Invocation & socket

- Subcommand: `nbd` (benji.py:215).
- Options (exact): `-a/--bind-address` (def `127.0.0.1`), `-p/--bind-port`
  (def `10809`, **string**), `-r/--read-only` (flag, def False),
  `-d/--discard-changes` (flag, def False).
- Address tuple `(bind_address, bind_port)` (commands.py:350) is passed to
  `asyncio.start_server(self.handler, addr, port, loop=loop)` (nbdserver.py:397).
  The port is a string; asyncio resolves it as a service name/number.
- `serve_forever()` (nbdserver.py:393-407) runs the asyncio loop, installs
  `SIGTERM`/`SIGINT` handlers that call `loop.stop`, then on shutdown closes the
  server and the loop. `stop()` (nbdserver.py:409-411) stops the loop thread-safely.

### 2.2 NBD protocol bits implemented

Fixed new-style handshake (nbdserver.py:114-123):

- Server advertises `NBD_HANDSHAKE_FLAGS = NBD_FLAG_FIXED_NEWSTYLE | NBD_FLAG_NO_ZEROES`
  (nbdserver.py:123). **Note the comment at nbdserver.py:118-122**: the server sets
  `NBD_FLAG_NO_ZEROES` even though the spec says the *server* should not; this matches
  buggy nbd-client 3.19 behaviour. Preserve this.
- Initial handshake: server writes `>QQH` = `INIT_PASSWD` (`NBDMAGIC`,
  0x4e42444d41474943), `CLISERV_MAGIC` (`IHAVEOPT`, 0x49484156454F5054),
  handshake flags (nbdserver.py:187).
- Client replies with 4-byte client flags (nbdserver.py:190-208). Both fixed and
  unfixed new-style negotiation are supported. Unknown client flag bits → `IOError`.
  `no_zeros` is honoured in the export reply.

Negotiation options (nbdserver.py:211-298):

| Option | Constant | Behaviour | Location |
|---|---|---|---|
| `NBD_OPT_EXPORTNAME` (1) | `NBD_OPT_EXPORTNAME` | The export name is the **version UID** (ASCII). Unknown UID → unfixed: `IOError`; fixed: reply `NBD_REP_ERR_UNSUP` and continue. On success opens the version via `store.open(version)` and emits the export size + flags, then optionally 124 zero bytes (unless `no_zeros`). | nbdserver.py:230-267 |
| `NBD_OPT_LIST` (3) | `NBD_OPT_LIST` | Lists all version UIDs as `NBD_REP_SERVER` replies, then `NBD_REP_ACK`. | nbdserver.py:269-281 |
| `NBD_OPT_ABORT` (2) | `NBD_OPT_ABORT` | Replies `NBD_REP_ACK` and raises `_NbdServerAbortedNegotiationError`. | nbdserver.py:283-287 |
| `NBD_OPT_GO` (7) | `NBD_OPT_GO` | **Not implemented.** Silently replied with `NBD_REP_ERR_UNSUP` (no warning logged). | nbdserver.py:291-298 |
| All others | — | Logged as a warning and replied with `NBD_REP_ERR_UNSUP` (fixed) or `IOError` (unfixed). | nbdserver.py:288-298 |

Export / transmission flags (nbdserver.py:125-136):

- `NBD_EXPORT_FLAGS = NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH` (nbdserver.py:136).
- If `--read-only`: `export_flags |= NBD_FLAG_READ_ONLY` (nbdserver.py:252-254).
- **Export size rounding:** `size = math.ceil(version.size / 4096) * 4096`
  (nbdserver.py:260) — size is rounded **up** to a 4096 multiple. Preserve exactly.
- `NBD_FLAG_SEND_FUA`, `NBD_FLAG_SEND_TRIM`, `NBD_FLAG_SEND_WRITE_ZEROES`,
  `NBD_FLAG_CAN_MULTI_CONN` are **not** advertised.

Transmission commands (nbdserver.py:301-375):

| Command | Constant | Behaviour | Location |
|---|---|---|---|
| `NBD_CMD_READ` (0) | `NBD_CMD_READ` | `store.read(version, cow_version, offset, length)`. Errors → reply with `EIO` (5). | nbdserver.py:346-354 |
| `NBD_CMD_WRITE` (1) | `NBD_CMD_WRITE` | Read-only export → reply `EPERM` (1). Otherwise lazily creates a copy-on-write version via `store.create_cow_version(version)` on first write, then `store.write(cow_version, offset, data)`. Errors → `EIO`. | nbdserver.py:325-344 |
| `NBD_CMD_DISC` (2) | `NBD_CMD_DISC` | Logs and breaks the transmission loop. | nbdserver.py:321-323 |
| `NBD_CMD_FLUSH` (3) | `NBD_CMD_FLUSH` | No-op (success) when read-only or no COW version exists yet; otherwise `store.flush(cow_version)`. Errors → `EIO`. | nbdserver.py:356-370 |
| `NBD_CMD_TRIM` (4) | — | **Not implemented.** Falls through to the `else` branch → reply `EINVAL` (22). | nbdserver.py:372-375 |
| `NBD_CMD_CACHE` (5), `NBD_CMD_WRITE_ZEROES` (6), `NBD_CMD_BLOCK_STATUS` (7), `NBD_CMD_RESIZE` (8) | — | **Not implemented.** All → `EINVAL` (22). | nbdserver.py:372-375 |

Command flags (nbdserver.py:109-112, nbdserver.py:311-319): **any** non-zero command
flags cause an `EINVAL` (22) reply. `NBD_CMD_FLAG_FUA` is **not** honoured.

Allowed NBD errnos (nbdserver.py:147-154): `EPERM=1`, `EIO=5`, `ENOMEM=12`,
`EINVAL=22`, `ENOSPC=28`, `EOVERFLOW=75`, `ESHUTDOWN=108`.

Reply framing: `>LLQ` = `NBD_REPLY_MAGIC` (0x67446698), error, handle, then optional
data (nbdserver.py:168-176). Request framing: `>LLQQL` = magic, cmd, handle, offset,
length (nbdserver.py:302-304). Bad request magic → `IOError` (disconnect).

### 2.3 Disconnect / COW finalisation (nbdserver.py:383-391)

On connection teardown the `finally` block:

- If a COW version exists:
  - `--discard-changes` → `store.discard_cow_version(cow_version)`.
  - otherwise → `store.fixate_cow_version(cow_version)` (creates a new version).
- If a version was opened → `store.close(version)`.
- `writer.close()`.

### 2.4 Read-only mount / file-level recovery

There is **no** built-in file-level recovery in the NBD server — it is a whole-block
device export. Read-only mode (`--read-only`) makes the export `NBD_FLAG_READ_ONLY`,
rejects writes with `EPERM`, and skips flushes. The export name is a version UID, so a
client mounts a specific version read-only and then uses filesystem-level tools to
extract files. This contract must be preserved.

---

## 3. REST API endpoints

Framework: **bottle** (`Bottle`, restapi.py:7) with **webargs** for query-param parsing
(`webargs.bottleparser.use_kwargs`, restapi.py:9). The server is started via **gunicorn**
with the `gthread` worker class (restapi.py:91-103): `server='gunicorn'`,
`worker_class='gthread'`, `threads=<threads>`, `worker_connections=threads*10`,
`reuse_port=True`, `debug` set from whether the logger is at DEBUG level
(commands.py:452). `sys.argv` is reset to `[sys.argv[0]]` before launch so gunicorn does
not re-parse CLI args (restapi.py:93).

Route registration is reflective (restapi.py:83-89): any method with a `bottle_route`
attribute is registered via `self._app.route(**attr.bottle_route)`; any method with a
`bottle_error` attribute is registered as an error handler. The `route` decorator
(restapi.py:35-64) inspects the function's **annotations** for `webargs.fields.Field`
instances and feeds them to `use_kwargs` — so parameter names come from the annotated
keyword args. A `200` with `None` body is converted to `204 No Content` (restapi.py:52-53).
All successful responses are `application/json; charset=utf-8` (restapi.py:59).

Base path prefix for all core endpoints:
`/apis/{CORE_API_GROUP}/{CORE_API_VERSION_V1}` = **`/apis/core/v1`**
(restapi.py:70-71).

### 3.1 Endpoints

| Method | Path | Query params (webargs) | Body | Returns | Description | Location |
|---|---|---|---|---|---|---|
| GET | `/apis/core/v1/versions/<version_uid>` | — | — | JSON `{versions:[…]}` (blocks excluded); `410` if UID not found | Read one version. | restapi.py:123-135 |
| PATCH | `/apis/core/v1/versions/<version_uid>` | `protected: fields.Bool(missing=None)`, `labels: fields.DelimitedList(fields.Str(), missing=None)` | — | JSON `{versions:[…]}`; `410` if not found | Update protection and/or labels on a version. `labels` uses `+key=val`/`-key` syntax (same as CLI). | restapi.py:137-164 |
| DELETE | `/apis/core/v1/versions/<version_uid>` | `force: fields.Bool(missing=False)`, `keep_metadata_backup: fields.Bool(missing=False)`, `override_lock: fields.Bool(missing=False)` | — | JSON `{versions:[…]}` (the version **before** deletion); `410` if not found | Remove a version (exports it first, then `benji_obj.rm`). | restapi.py:166-187 |
| GET | `/apis/core/v1/versions` | `filter_expression: fields.Str(missing=None)`, `include_blocks: fields.Bool(missing=False)` | — | JSON `{versions:[…]}`; blocks included iff `include_blocks=true` | List versions matching a filter expression. | restapi.py:189-202 |
| POST | `/apis/core/v1/versions/metadata/import` | — | raw metadata stream (read from `request.body`) | `204` (returns None) | Import version metadata. | restapi.py:204-207 |
| GET | `/apis/core/v1/storages` | — | — | JSON `["storageName", …]` | List configured storage backends. | restapi.py:209-212 |
| POST | `/apis/core/v1/database` | — | — | `204` | Initialize the database. | restapi.py:214-216 |
| PATCH | `/apis/core/v1/database` | — | — | `204` | Migrate the database schema. | restapi.py:218-220 |
| GET | `/apis/core/v1/version-info` | — | — | JSON `{version, configuration_version, database_metadata_version, object_metadata_version}` | Program version info (mirrors CLI `version-info --machine-output`). | restapi.py:222-239 |

### 3.2 Error handling

Default error handler (restapi.py:105-121) returns JSON
`{url, status, body, [exception:{name,message}], [traceback]}` with
`application/json; charset=utf-8`. `410` statuses are produced inline by the version
handlers on `KeyError` (restapi.py:133, restapi.py:162, restapi.py:185) with body
`f'410 Version {version_uid} not found.'` set on `response.status`.

### 3.3 REST client helper (`src/benji/helpers/restapi.py`)

`BenjiRESTClient` (helpers/restapi.py:11) is a `requests.Session()`-backed client used by
the Ansible/helper tooling. Base URL: `{api_endpoint}/apis/{api_group}/{api_version}/`
(helpers/restapi.py:28). Timeout `(2, 30)` (connect, read). `404`/`410` → raise
`KeyError(response.reason)`; other non-2xx → `response.raise_for_status()`; `204` →
return `None`, else `response.json()`. Methods: `get_version_by_uid`, `find_versions_with_filter`,
`rm`, `protect`. *(This helper is part of the external contract for the Ansible
integration but is not part of the REST API server itself.)*

---

## 4. Exit codes

benji uses the BSD `os.EX_*` constants exclusively. There are **no** custom numeric
exit codes. The full mapping lives in `src/benji/scripts/benji.py:336-353` and is
evaluated in `main()`'s `try/except` (benji.py:356-375): the first matching
`isinstance(exception, case.exception)` wins, so order is from most-specific to
least-specific (the `BaseException` catch-all is last).

`os.EX_*` numeric values (verified on the target platform):

| Constant | Value | Used for | Location |
|---|---|---|---|
| `os.EX_OK` | 0 | Normal success (also used by `completion` subcommand). | benji.py:295, benji.py:359 |
| `os.EX_USAGE` | 64 | Usage error / bad CLI usage: no subcommand given; config file not found; `UsageError`. | benji.py:291, benji.py:304, benji.py:337 |
| `os.EX_DATAERR` | 65 | Bad input data; scrubbing failure. `InputDataError`, `ScrubbingError`. | benji.py:341-342 |
| `os.EX_NOINPUT` | 66 | Input unavailable: `FileNotFoundError`, `LookupError`, **`KeyboardInterrupt`**. | benji.py:345, benji.py:350-351 |
| `os.EX_NOPERM` | 77 | Permission/lock: `AlreadyLocked`, `PermissionError`. | benji.py:338, benji.py:343 |
| `os.EX_IOERR` | 74 | I/O error: `EOFError`, `IOError`, `ConnectionError`. | benji.py:346-347, benji.py:349 |
| `os.EX_OSERR` | 71 | Generic OS error: `OSError`. | benji.py:348 |
| `os.EX_SOFTWARE` | 70 | Internal error / uncaught anything: `InternalError`, `BaseException` catch-all. | benji.py:339, benji.py:352 |
| `os.EX_CONFIG` | 78 | Configuration error. | benji.py:340 |
| `os.EX_CANTCREAT` | 73 | Output file already exists: `FileExistsError`. | benji.py:344 |

### 4.1 Exception → exit-code → stacktrace table

| Exception | Exit code | Stacktrace logged? | Location |
|---|---|---|---|
| `benji.exception.UsageError` | `EX_USAGE` (64) | no | benji.py:337 |
| `benji.exception.AlreadyLocked` | `EX_NOPERM` (77) | no | benji.py:338 |
| `benji.exception.InternalError` | `EX_SOFTWARE` (70) | **yes** | benji.py:339 |
| `benji.exception.ConfigurationError` | `EX_CONFIG` (78) | no | benji.py:340 |
| `benji.exception.InputDataError` | `EX_DATAERR` (65) | no | benji.py:341 |
| `benji.exception.ScrubbingError` | `EX_DATAERR` (65) | no | benji.py:342 |
| `PermissionError` | `EX_NOPERM` (77) | no | benji.py:343 |
| `FileExistsError` | `EX_CANTCREAT` (73) | no | benji.py:344 |
| `FileNotFoundError` | `EX_NOINPUT` (66) | no | benji.py:345 |
| `EOFError` | `EX_IOERR` (74) | **yes** | benji.py:346 |
| `IOError` | `EX_IOERR` (74) | **yes** | benji.py:347 |
| `OSError` | `EX_OSERR` (71) | **yes** | benji.py:348 |
| `ConnectionError` | `EX_IOERR` (74) | **yes** | benji.py:349 |
| `LookupError` | `EX_NOINPUT` (66) | **yes** | benji.py:350 |
| `KeyboardInterrupt` | `EX_NOINPUT` (66) | no | benji.py:351 |
| `BaseException` (catch-all) | `EX_SOFTWARE` (70) | **yes** | benji.py:352 |

Note: `Scribenji.exception.ScrubbingError` subclasses `IOError` (exception.py:29), so the
order matters — it must be matched **before** `IOError`. The table is correctly ordered.

`SystemExit` is re-raised, not converted (benji.py:360-361), so `sys.exit(<code>)` from
deeper layers (and argparse's own usage-error exit) passes through verbatim.

### 4.2 Other exit sources

- **argparse usage errors** exit with code **2** (CPython argparse default). benji does
  not override this. Any `argparse.ArgumentTypeError` (e.g. `integer_range` failures,
  benji.py:28-40) and any unknown option / bad choice triggers this. **This `2` is not
  in the `os.EX_*` table and is undocumented in the exception mapping** — it is purely
  argparse's behaviour.
- `sys.exit(os.EX_USAGE)` (64) is called directly for: no subcommand (benji.py:291) and
  config file not found (benji.py:304).
- `sys.exit(os.EX_OK)` (0) for `completion` (benji.py:295) and after successful command
  return (benji.py:359).
- The uncaught-exception hook (`logging.py:220-228`) logs but does **not** set an exit
  code itself; it relies on the Python runtime's default non-zero exit after the hook.
- There are **no** other `sys.exit()` / `SystemExit` / `os.EX_*` references in the
  source tree (verified by grep across `src/benji/`).

### 4.3 Convention summary

- `0` = success. Non-zero = failure.
- Specific BSD `os.EX_*` codes for known exception classes (table above).
- `2` = argparse CLI/usage errors (CPython default; not a benji constant).
- `KeyboardInterrupt` (`Ctrl-C`) exits `66` (`EX_NOINPUT`), **not** the usual `130`.

---

## 5. Log format

Logging is built on **structlog** wrapping the stdlib `logging` module
(`src/benji/logging.py`). A single shared `logger = structlog.get_logger()` is exported
(logging.py:20) and imported by nearly every module via `from benji.logging import
logger` (see §5.4). The NBD server instead uses stdlib `logging.getLogger(__package__)`
(nbdserver.py:157) — it does **not** use structlog directly, but its records flow
through the same formatter chain via the `foreign_pre_chain`.

### 5.1 structlog processor chain

Configured at import time (logging.py:230-236) and used for structlog-emitted records
(`_sl_processors`, logging.py:119-128):

1. `structlog.stdlib.add_log_level` — adds `level` (lowercase string: `debug`, `info`,
   `warning`, `error`, `critical`, `exception`).
2. `structlog.stdlib.PositionalArgumentsFormatter()` — formats `%s`-style positional
   args.
3. `_sl_processor_timestamper = structlog.processors.TimeStamper(utc=True)`
   (logging.py:110) — adds `timestamp` as a **UTC** UNIX float timestamp.
4. `_sl_processor_add_source_context` (logging.py:95-100) — adds `file`
   (`frame.f_code.co_filename`), `line` (`frame.f_lineno`), `function`
   (`frame.f_code.co_name`), skipping frames in `__name__` and `logging`.
5. `_sl_processor_add_process_context` (logging.py:103-107) — adds `process`
   (`os.getpid()`), `thread_name` (`threading.current_thread().name`), `thread_id`
   (`threading.get_ident()`).
6. `structlog.processors.StackInfoRenderer()` — adds a `stack` string when
   `exc_info=True` and a stack is requested.
7. `structlog.processors.format_exc_info` — adds an `exception` string when
   `exc_info=True` resolves to an exception.
8. `structlog.stdlib.ProcessorFormatter.wrap_for_formatter` — hands the event dict to
   the stdlib formatter.

`structlog.configure`: `context_class=dict`, `logger_factory=structlog.stdlib.LoggerFactory()`,
`wrapper_class=structlog.stdlib.BoundLogger`, `cache_logger_on_first_use=True`
(logging.py:230-236).

Foreign (stdlib) records — e.g. from `nbdserver`, `bottle`, `gunicorn`, `boto3`,
`sqlalchemy` — are routed through `_sl_foreign_pre_chain` (logging.py:112-117), which is
steps 1, 3, 4, 5 above (note: **without** step 2 `PositionalArgumentsFormatter` and
without steps 6/7, but `ProcessorFormatter` re-applies 6/7 for the formatter).

### 5.2 Formatters (output renderers)

`setup_logging()` (logging.py:131-216) builds a `dictConfig` with four named
formatters. The active console formatter is selected in `main()`
(benji.py:309-317): `json` when `--machine-output`; `console-plain` when `--no-color`;
otherwise `console-colored`.

| Formatter name | Renderer | Format string | Used by | Location |
|---|---|---|---|---|
| `console-plain` | `_FormatRenderer(colors=False, …)` | `'{log_color}{level_uc:>8s}: {event:s}'` | console when `--no-color` | logging.py:149-153 |
| `console-colored` | `_FormatRenderer(colors=True, …)` | `'{log_color}{level_uc:>8s}: {event:s}'` | console (default) | logging.py:154-158 |
| `legacy` | `_FormatRenderer(colors=False, …)` | `'{timestamp_local_ctime} {process:d}/{thread_name:s} {file:s}:{line:d} {level_uc:s} {event:s}'` | logfile (default) | logging.py:159-168 |
| `json` | `structlog.processors.JSONRenderer()` | JSON | console when `--machine-output`; also used by the helpers logging (helpers/utils.py) | logging.py:169-173 |

`_FormatRenderer.__call__` (logging.py:62-92):

- Adds `log_color_reset` (always, from `colorama.Style.RESET_ALL` or `''`).
- If `level` present: looks up `log_color` per the level map, sets `level_uc` =
  `level.upper()`.
- If `timestamp` present: computes `timestamp_local_ctime` =
  `datetime.fromtimestamp(timestamp).ctime()` (local time, ctime format).
- Renders the format string, then appends `\n` + `stack` (if present) and `\n` +
  `exception` (if present), then the reset code.

Console format produced (default, coloured) is therefore:

```
{LEVEL:>8}: {event}
```

e.g. `    INFO: Starting to serve NBD on 127.0.0.1:10809`. Level is right-justified to
8 chars and upper-cased. No timestamp, no file/line on the console.

`legacy` (logfile) format produced:

```
{ctime} {pid}/{thread_name} {file}:{line} {LEVEL} {event}
```

e.g. `Wed Jul  8 12:00:00 2026 1234/MainThread /path/benji.py:42 INFO Starting …`. Note
`level_uc` here is **not** width-padded (the `:>8s` is only in the console formats).

### 5.3 Colours (colorama)

`_FormatRenderer` (logging.py:23-57). When `colors=True` it calls `colorama.init()`
(unless `force_colors`, which calls `colorama.deinit()` + `colorama.init(strip=False)`)
and uses this level → ANSI colour map (logging.py:33-42):

| structlog level | colour |
|---|---|
| `critical` | `Fore.RED` |
| `exception` | `Fore.RED` |
| `error` | `Fore.RED` |
| `warn` / `warning` | `Fore.YELLOW` |
| `info` | `Fore.GREEN` |
| `debug` | `Fore.WHITE` |
| `notset` | `Back.RED` |

Reset = `colorama.Style.RESET_ALL`. When `colors=False` all colours and the reset are
empty strings. `--no-color` selects `console-plain` (no colour); `--machine-output`
selects `json` (no colour).

### 5.4 Log levels

- Root logger level: `DEBUG` (logging.py:191-194) — everything is let through to the
  handlers; the **handler** level filters.
- Console handler level: from `--log-level` (default `INFO`), one of
  `DEBUG`/`INFO`/`WARNING`/`ERROR` (benji.py:59-62, logging.py:205).
- File handler level (when `logFile` is configured): `min(console_level, INFO)`
  (logging.py:209) — i.e. the file always gets at least `INFO` even if the console is
  at `WARNING`/`ERROR`.
- structlog/stdlib levels used: `debug`, `info`, `warning`, `error`, `exception`,
  `critical` (the `BoundLogger` API). The `--log-level` choices are the uppercase stdlib
  names.

Third-party loggers silenced (logging.py:240-251): `alembic`→`WARN`,
`boto3`/`botocore`/`nose`/`b2sdk`→`WARN`. `sqlalchemy.engine`→`INFO` only when
`BENJI_DEBUG_SQL=1` (logging.py:253-254). `ResourceWarning` for unclosed boto3 sockets
is filtered (logging.py:249).

### 5.5 Structured fields always present

Every record (structlog or foreign, after the pre-chain) carries these keys in the
event dict (and thus in JSON output):

| Field | Source | Always present? | Location |
|---|---|---|---|
| `event` | the log message (structlog first positional arg) | yes (may be empty) | structlog core |
| `level` | lowercase string level | yes | logging.py:113/120 |
| `timestamp` | UTC UNIX float | yes | logging.py:110 |
| `file` | source filename of the first app frame | yes | logging.py:96-97 |
| `line` | source line number | yes | logging.py:98 |
| `function` | function name | yes | logging.py:99 |
| `process` | `os.getpid()` int | yes | logging.py:104 |
| `thread_name` | current thread name | yes | logging.py:105 |
| `thread_id` | `threading.get_ident()` int | yes | logging.py:106 |
| `stack` | rendered stack string | only if `exc_info=True` + stack requested | logging.py:82-86 |
| `exception` | rendered exception string | only if `exc_info` resolves to an exception | logging.py:83-88 |

Derived (added by the renderer, not in the JSON dict unless the format string reads
them): `log_color`, `log_color_reset`, `level_uc`, `timestamp_local_ctime`.

For **JSON** output (`--machine-output` or the helpers logging), `structlog.processors.
JSONRenderer()` serialises the whole event dict (minus `stack`/`exception` which were
popped by `_FormatRenderer` for the console/legacy renderers — but JSONRenderer does
**not** pop them, so JSON lines include `stack` and `exception` keys when present). The
JSON keys are therefore the field names above, sorted by structlog's default
(`sort_keys=False` for the main app; the helpers' `log_jsonl` uses `sort_keys=True`,
helpers/utils.py:106).

### 5.6 Where log lines are emitted (modules using the shared structlog logger)

`from benji.logging import logger` (structlog `BoundLogger`):

- `benji/commands.py:13`, `benji/benji.py:25`, `benji/config.py:17`,
  `benji/database.py:41`, `benji/jobexecutor.py:6`, `benji/utils.py:24`,
  `benji/retentionfilter.py:37`, `benji/io/file.py:13`, `benji/io/iscsi.py:14`,
  `benji/io/rbd.py:18`, `benji/io/rbdaio.py:19`, `benji/storage/base.py:19`,
  `benji/storage/s3.py:12`, `benji/storage/b2.py:15`,
  `benji/transform/aes_256_gcm_ecc.py:8`, plus test modules.

`logging.getLogger(__package__)` (stdlib, routed through `foreign_pre_chain`):

- `benji/nbdserver.py:157` (`self.log`).

Separate structlog setup (helpers, used by Ansible-side tooling — **not** the main
process): `benji/helpers/utils.py:15` defines its own `logger = structlog.get_logger()`
and its own `setup_logging()` (helpers/utils.py:18-91) that configures a JSON
`StreamHandler` on the root logger driven by `benji.helpers.settings.benji_log_level`.
Users of the helper logger: `benji/helpers/ceph.py:8`, `benji/helpers/prometheus.py:7`.
This is a **second, parallel** structlog configuration intended for the helper
binaries; the port must keep the two configurations distinct.

### 5.7 Log format contract (must be byte-identical for acceptance)

1. Default console line: `{LEVEL:>8}: {message}` with level upper-cased and
   right-justified to 8, coloured per §5.3 unless `--no-color`.
2. `--machine-output` console line: a single JSON object per record with the fields in
   §5.5 (plus `stack`/`exception` when applicable), written to **stderr**.
3. Logfile (`logFile` config key) line: `{local_ctime} {pid}/{thread_name} {file}:{line} {LEVEL} {message}`.
4. All console output goes to **stderr** (`"stream": "ext://sys.stderr"`,
   logging.py:180). Machine-readable command output (JSON / tables) goes to **stdout**
   via `print`/`sys.stdout` in `commands.py`. This stdout/stderr split is a contract.
5. Uncaught exceptions are logged via `sys.excepthook = _handle_exception`
   (logging.py:220-228) as `error("Uncaught exception", exc_info=…)` **except**
   `KeyboardInterrupt`, which is deferred to the default hook.

---

## Acceptance checklist (Phase H)

- [x] All 26 CLI subcommands present with identical option spellings, defaults, types,
      `dest` names, and `nargs` (§1).
- [x] `allow_abbrev=False` preserved (no prefix matching).
- [x] `BENJI_EXPERIMENTAL=1` gating of `rest-api` preserved.
- [x] `nbd --bind-port` stays a string default `10809`; `rest-api --bind-port` stays
      `int` default `8080`.
- [x] NBD handshake/transmission flags, 4096 size rounding, COW finalisation
      (fixate vs discard) byte-identical (§2).
- [x] All 9 REST endpoints reachable with identical paths, methods, query params, and
      `204`-on-`None` semantics (§3). *(Smoke-test only per scope.)*
- [x] Exit codes match §4 table exactly; argparse `2` for usage errors preserved;
      `KeyboardInterrupt`→66 preserved.
- [x] Log lines match §5 formats on stdout/stderr split; structlog processor chain
      and the four formatter names (`console-plain`, `console-colored`, `legacy`,
      `json`) preserved.
- [x] Colour map (§5.3) and `--no-color` / `--machine-output` formatter selection
      (benji.py:309-317) preserved.
- [x] Third-party logger silencing (alembic/boto3/botocore/nose/b2sdk→WARN) and
      `BENJI_DEBUG_SQL` behaviour preserved.
- [x] `golden-master --verify` passes byte-for-byte for backup/restore.
