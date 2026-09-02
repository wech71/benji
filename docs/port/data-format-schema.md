<!-- SPDX-License-Identifier: LGPL-3.0-only -->

# benji data-format schema

Phase A analysis reference for the Python 3.13 port. This document is a
**static** reading of the existing source under `src/benji/`. It is the
on-disk and database contract that the port must reproduce byte-for-byte so
that restores are identical to the original and existing repositories can be
opened unchanged.

All file:line references point to the original tree at
`/mnt/benji-ki-portierung/src/benji/`.

> **WARNING — safety-critical:** Several envelope fields are surprising
> (see "Notable findings" at the end and inline notes). The GCM
> authentication tag is **never written or verified**; the AES-GCM nonce is
> 16 bytes (not the GCM-recommended 12); the block hash is configurable and
> its digest length must not exceed 64 bytes. The port must reproduce all of
> this exactly, including the weaknesses, to remain a drop-in replacement.

---

## 1. Database schema

### 1.1 Supported engines and connection setup

- Engines in scope: **SQLite** and **PostgreSQL** (`database.py:939-955`,
  `AGENTS.md`). The engine is chosen by the `databaseEngine` config string,
  e.g. `sqlite:////tmp/benji.sqlite` or
  `postgresql+psycopg2://user:pass@host/db`.
- SQLite PRAGMA `foreign_keys=ON` is forced on every connect
  (`database.py:50-55`).
- For SQLite the connect `timeout` is set to `3 * Version.TIMED_COMMIT_INTERVAL`
  = `3 * 20` = **60 seconds** (`database.py:949`) to mitigate "database is
  locked" errors.
- `pool_pre_ping=True` is enabled (`database.py:950`).
- An in-memory engine (`sqlite://`) is used by the test suite
  (`database.py:953`).

### 1.2 Naming convention (drives all constraint/index names)

`MetaData` is created with an explicit `naming_convention`
(`database.py:286-293`):

| type | template |
|------|----------|
| index  | `ix_%(column_0_label)s` |
| unique | `uq_%(table_name)s_%(column_0_name)s` |
| check  | `ck_%(table_name)s_%(constraint_name)s` |
| foreign key | `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` |
| primary key | `pk_%(table_name)s` |

`Base = sqlalchemy.orm.declarative_base(metadata=metadata)` (`database.py:294`).
`Session = scoped_session(sessionmaker())` (`database.py:296`).

### 1.3 Custom column types

| Type | impl | notes | ref |
|------|------|-------|-----|
| `BenjiDateTime` | `DateTime` | On bind: if `tzinfo` is set, convert to UTC and strip tzinfo; if a `str`, parse with `dateparser` (formats `['%Y-%m-%dT%H:%M:%S']`, locales `['en']`, past preference, timezone-aware, UTC) and strip tzinfo. `cache_ok=False`. | `database.py:58-86` |
| `VersionStatusType` | `Integer` | Maps `VersionStatus` enum <-> int. `cache_ok=True`. | `database.py:113-136` |
| `VersionUidType` | `String(255)` | Wraps `VersionUid`. `cache_ok=True`. | `database.py:165-181` |
| `ChecksumType` | `LargeBinary` | Stores the **raw bytes** of the checksum: bind does `unhexlify(hexstring)`, read returns `hexlify(bytes).decode('ascii')`. So the DB column holds binary; the Python attribute is a lowercase hex string. | `database.py:184-200` |

`VersionStatus` enum (`database.py:89-110`): `incomplete=1`, `valid=2`,
`invalid=3`. `min=incomplete`, `max=invalid`.

### 1.4 Table: `versions`

Source: `database.py:299-716`.

`__table_args__ = {'sqlite_autoincrement': True}` (`database.py:310`) —
ensures SQLite does not reuse rowids for the `id` PK.

| column | SQL type | nullable | PK | unique | default | index | FK | notes |
|--------|----------|----------|----|--------|--------|-------|----|-------|
| `id` | `Integer` autoincrement | NO | YES | — | auto | — | — |
| `uid` | `VersionUidType` (`String(255)`) | NO | — | YES | — | — | — | version UID string |
| `date` | `BenjiDateTime` | NO | — | — | — | — | — | naive UTC |
| `volume` | `String(255)` | NO | — | — | — | YES (`ix_versions_volume`) | — | |
| `snapshot` | `String(255)` | NO | — | — | — | — | — | |
| `size` | `BigInteger` | NO | — | — | — | — | — | image size in bytes |
| `block_size` | `Integer` | NO | — | — | — | — | — | |
| `storage_id` | `Integer` | NO | — | — | — | — | `fk_versions_storage_id_storages` → `storages.id` | |
| `status` | `VersionStatusType` (`Integer`) | NO | — | — | — | — | — | check constraint `ck_versions_status`: `status >= 1 AND status <= 3` (`database.py:322-326`) |
| `protected` | `Boolean(name='protected')` | NO | — | — | — | — | — | produces `ck_versions_protected` |
| `bytes_read` | `BigInteger` | YES | — | — | — | — | — | statistic |
| `bytes_written` | `BigInteger` | YES | — | — | — | — | — | statistic |
| `bytes_deduplicated` | `BigInteger` | YES | — | — | — | — | — | statistic |
| `bytes_sparse` | `BigInteger` | YES | — | — | — | — | — | statistic |
| `duration` | `BigInteger` | YES | — | — | — | — | — | statistic (seconds) |

Relationships:
- `storage` → `Storage`, `lazy='joined'` (`database.py:321`).
- `labels` → `Label`, `backref='version'`, ordered by `Label.name` asc,
  `passive_deletes=True`, `cascade='all, delete-orphan'`,
  `collection_class=attribute_mapped_collection('name')`, `lazy='selectin'`
  (`database.py:339-345`).

Non-mapped attribute: `blocks_count = ceil(size / block_size)`
(`database.py:352`).

The `blocks` relationship is **not** a SQLAlchemy relationship; it is a
generator property that yields `Block` rows in `idx` order, synthesizing
sparse blocks (`BlockUid(None,None)`) for missing indices in windows of
`BLOCKS_PER_CALL = 10000` (`database.py:531-559`).

### 1.5 Table: `labels`

Source: `database.py:718-728`.

| column | SQL type | nullable | PK | unique | default | index | FK |
|--------|----------|----------|----|--------|--------|-------|----|
| `version_id` | `Integer` | NO | YES (part) | — | — | — | `fk_labels_version_id_versions` → `versions.id` `ondelete=CASCADE` |
| `name` | `String(255)` | NO | YES (part) | — | — | YES (`ix_labels_name`) | — |
| `value` | `String(255)` | NO | — | — | — | YES (`ix_labels_value`) | — |

Primary key is composite `(version_id, name)` → `pk_labels`.
There is also a unique constraint `uq_labels_version_uid` on
`(version_uid, name)` created by migration `2e028f08346b` on the **old**
schema; after the `da25cc147a07` rebuild the PK is `(version_id, name)`. See
§2.

### 1.6 Table: `blocks`

Source: `database.py:769-794`.

`MAXIMUM_CHECKSUM_LENGTH = 64` (bytes) (`database.py:772`). The configured
block hash digest must be ≤ 64 bytes (`utils.py:145-147`).

Column declaration order in the ORM is intentionally sorted for PostgreSQL
row alignment (`database.py:775-785`); the on-disk column set is:

| column | SQL type | nullable | PK | unique | default | index | FK |
|--------|----------|----------|----|--------|--------|-------|----|
| `idx` | `Integer` | NO | YES (part) | — | — | — | — | block index within version |
| `uid_right` | `Integer` | YES | — | — | — | — | — | high part of `BlockUid` |
| `uid_left` | `Integer` | YES | — | — | — | — | — | low part of `BlockUid` |
| `size` | `Integer` | YES | — | — | — | — | — | actual data length |
| `version_id` | `Integer` | NO | YES (part) | — | — | — | `fk_blocks_version_id_versions` → `versions.id` `ondelete=CASCADE` |
| `valid` | `Boolean(name='valid')` | NO | — | — | — | — | — | `ck_blocks_valid` |
| `checksum` | `ChecksumType` (`LargeBinary(64)`) | YES | — | — | — | YES | — | stored as raw bytes (see `ChecksumType`) |

`__table_args__` (`database.py:788-794`):
- `PrimaryKeyConstraint('version_id', 'idx')` → `pk_blocks`.
- `Index(None, 'uid_left', 'uid_right')` → `ix_blocks_uid_left` (composite,
  non-unique).
- `Index(None, 'checksum', mysql_length=MAXIMUM_CHECKSUM_LENGTH)` →
  `ix_blocks_checksum` (the `mysql_length` hint is ignored on SQLite/PG).

`uid` is a `sqlalchemy.orm.composite(BlockUid, uid_left, uid_right,
comparator_factory=BlockUidComparator)` (`database.py:787`). `BlockUid` is a
`MutableComposite` (`database.py:212-280`); see §3.2.

A sparse block is represented by the **absence** of a row, or by a row whose
`uid_left`/`uid_right` are both `NULL` (`SparseBlockUid = BlockUid(None,None)`,
`database.py:283`). `Block(None,None)` with `size == block_size` is treated as
fully sparse and is not persisted (`database.py:421-435`).

### 1.7 Table: `deleted_blocks`

Source: `database.py:810-825`.

Tracks block UIDs that have been unlinked from a version and are candidates
for physical deletion from storage after a grace period.

| column | SQL type | nullable | PK | unique | default | index | FK |
|--------|----------|----------|----|--------|--------|-------|----|
| `date` | `BenjiDateTime` | NO | — | — | — | — | — | deletion time |
| `id` | `Integer` autoincrement | NO | YES | — | auto | — | — | |
| `storage_id` | `Integer` | NO | — | — | — | — | `fk_deleted_blocks_storage_id_storages` → `storages.id` |
| `uid_left` | `Integer` | NO | — | — | — | — | — | |
| `uid_right` | `Integer` | NO | — | — | — | — | — | |

`__table_args__`: `Index(None, 'uid_left', 'uid_right')` →
`ix_deleted_blocks_uid_left` (`database.py:825`).
`uid` is composite `BlockUid(uid_left, uid_right)`.
`storage` relationship `lazy='joined'` (`database.py:819`).

### 1.8 Table: `locks`

Source: `database.py:884-893`.

| column | SQL type | nullable | PK | unique | default | index | FK |
|--------|----------|----------|----|--------|--------|-------|----|
| `lock_name` | `String(255)` | NO | YES | — | — | — | — |
| `host` | `String(255)` | NO | — | — | — | — | — |
| `process_id` | `String(255)` | NO | — | — | — | — | — |
| `reason` | `String(255)` | NO | — | — | — | — | — |
| `date` | `BenjiDateTime` | NO | — | — | — | — | — |

`process_id` is `"{uuid1_hex}-{thread_ident}"` (`database.py:1427-1430`).
`host` is `platform.node()` (`database.py:1426`).

### 1.9 Table: `storages`

Source: `database.py:896-903`.

| column | SQL type | nullable | PK | unique | default | index | FK |
|--------|----------|----------|----|--------|--------|-------|----|
| `id` | `Integer` autoincrement | NO | YES | — | auto | — | — |
| `name` | `String(255)` | NO | — | YES (`uq_storages_name`) | — | — | — |

`Storage.sync()` (`database.py:910-928`) inserts a storage row from config,
optionally pinning a configured `storageId`.

### 1.10 Engine-specific DDL / behaviour

- SQLite: `sqlite_autoincrement=True` on `versions` (`database.py:310`);
  foreign keys enabled via PRAGMA; migrations run with
  `PRAGMA foreign_keys=OFF` (env.py, see §2.4).
- PostgreSQL: the `da25cc147a07` migration renames old PK constraints before
  rebuilding tables and resets the `versions_new.id` sequence via
  `setval(pg_get_serial_sequence(...))` (`da25cc147a07_volume_version_uid.py`).
- No PostgreSQL-specific index types are currently emitted (a commented-out
  `postgresql_using='hash'` on `blocks.checksum` exists at
  `database.py:792` but is not active).

---

## 2. Alembic migrations

### 2.1 Layout

- `alembic.ini`: `src/benji/sql_migrations/alembic.ini` — `script_location =
  %(here)s/alembic`. No `sqlalchemy.url` (the engine connection is injected
  via `config.attributes['connection']`, see `database.py:972,992`).
- `env.py`: `src/benji/sql_migrations/alembic/env.py`.
- versions: `src/benji/sql_migrations/alembic/versions/`.

### 2.2 Version table

The alembic version table is named **`alembic_version`** (explicitly passed to
`env_context.configure(connection, version_table="alembic_version")` in
`database.py:975`; env.py does not override it).

### 2.3 env.py specifics (`env.py:1-80`)

- `target_metadata = Base.metadata` (the ORM metadata from §1.2).
- `compare_type=True`, `compare_server_default=True`,
  `render_as_batch=True` (batch mode is required for SQLite ALTER support).
- `process_revision_directives` filters out redundant `DropIndexOp` for
  tables being dropped and suppresses empty autogenerate migrations.
- For SQLite connections, `PRAGMA foreign_keys=OFF` is executed before
  migrations and `PRAGMA foreign_keys=ON` afterwards (`env.py:60-74`).
- **Offline mode is rejected** (`env.py:77-80`); only online migrations are
  supported.
- `benji_config` is passed through `config.attributes` (`database.py:993`)
  so migrations can read the user config (used by `dd844d630d49` to seed
  `storages`).

### 2.4 Migration chain (oldest → head)

The head revision is **`3d014d45493f`** (no revision has it as
`down_revision`).

| order | revision | down_revision | description | schema change |
|------:|----------|---------------|-------------|---------------|
| 1 | `2e028f08346b` | `None` | `update_20190118-1` (base) | Rebuild indexes on `blocks` (`ix_blocks_uid_left` on `(uid_left,uid_right)`, drop `ix_blocks_uid_left_uid_right`) and `deleted_blocks` (`ix_deleted_blocks_uid_left`, drop `ix_blocks_uid_left_uid_right_2`). Widen `labels.name/value`, `locks.*`, `version_statistics.name/snapshot_name`, `versions.name/snapshot_name` from `VARCHAR` to `String(255)` and make several `NOT NULL`. Add `uq_labels_version_uid` on `(version_uid, name)`. |
| 2 | `b1fa564a0ebf` | `2e028f08346b` | Add version status | Add `versions.status Integer NOT NULL DEFAULT 2`; add check `ck_versions_status` (`status >= 1 AND status <= 3`); set `status=3` where old `valid=False`; drop `versions.valid`. |
| 3 | `fe79ce75cefa` | `b1fa564a0ebf` | Fix locking design | Drop and recreate `locks` with columns `lock_name PK, host, process_id, reason, date` (all `String(255)`/`DateTime`, `NOT NULL`). |
| 4 | `151248f94062` | `fe79ce75cefa` | Remove stats table | Add `versions.bytes_dedup/bytes_read/bytes_sparse/bytes_written/duration` (`BigInteger`, nullable); copy data from `version_statistics` by `uid`; drop table `version_statistics`. |
| 5 | `368014edd88c` | `151248f94062` | Fix blocks primary key | Drop `pk_blocks`, recreate `pk_blocks` on `(version_uid, id)`. |
| 6 | `013dd9461e2c` | `368014edd88c` | Rename snapshot_name → snapshot | `versions.snapshot_name` → `versions.snapshot` (`String(255) NOT NULL`). |
| 7 | `2bb97229fe36` | `013dd9461e2c` | Rename id → idx in blocks | `blocks.id` → `blocks.idx` (`Integer NOT NULL`). |
| 8 | `dd844d630d49` | `2bb97229fe36` | Add table storages | Create `storages(id PK autoincrement, name String(255) NOT NULL, uq_storages_name)`; seed from config `storages` list (`name`, optional `storageId`); add FK `versions.storage_id → storages.id` and `deleted_blocks.storage_id → storages.id`. |
| 9 | `da25cc147a07` | `dd844d630d49` | volume_version_uid (major rebuild) | Rebuild `versions` adding a new autoincrement `id` PK and converting the old integer `uid` into a string `uid` = `f'V{old_uid:010d}'`; rename `name`→`volume`; rebuild `blocks` to reference `version_id` (FK to `versions.id` `ondelete=CASCADE`) instead of `version_uid`, with PK `(version_id, idx)` and indexes `ix_blocks_checksum`, `ix_blocks_uid_left`; rebuild `labels` to reference `version_id` with PK `(version_id, name)` and indexes on `name`/`value`. PostgreSQL renames old PKs first and resets the sequence. |
| 10 | `3d014d45493f` | `da25cc147a07` | bytes_dedup → bytes_deduplicated | Rename `versions.bytes_dedup` → `versions.bytes_deduplicated` (`BigInteger`, nullable). **CURRENT HEAD** |

All migrations define `downgrade(): pass` (one-way only).

### 2.5 Init / stamp behaviour

`Database.init()` (`database.py:1010-1031`) creates all tables from the
current ORM metadata (`Base.metadata.create_all`) and then
`alembic_command.stamp(alembic_config, "head")` — i.e. a freshly initialised
database is stamped at `3d014d45493f` without running the migration scripts.
`Database.open()` (`database.py:999-1008`) refuses to run if the current
revision differs from head (requiring an explicit `migrate()` first).

---

## 3. Block-store / object layout

### 3.1 Storage backends

Two backends are in scope (`AGENTS.md`): **file** (`storage/file.py`) and
**S3** (`storage/s3.py`). B2 exists (`storage/b2.py`) but is out of scope.

- `StorageBase` (`storage/base.py:52`) defines the object contract; backends
  implement `_write_object`, `_read_object`, `_read_object_length`,
  `_rm_object`, `_list_objects`.
- `ReadCacheStorageBase` (`storage/base.py:506`) adds an optional on-disk
  `diskcache.FanoutCache` read cache; `S3.Storage` extends it.
- File backend (`storage/file.py`): object key `key` maps to file
  `<storage.path>/<key>`; directories are created on demand
  (`storage/file.py:29-41`). `os.walk` is used for listing, stripping the
  storage path prefix (`storage/file.py:77-92`).
- S3 backend (`storage/s3.py`): object key is used directly as the S3 key in
  the configured `bucketName` (`storage/s3.py:91-97`). Optional
  `storageClass`, `disableEncodingType`, etc.

### 3.2 Object key naming scheme

Defined by `StorageKeyMixIn` (`storage/key.py:8-43`). Every storage object is
addressed by a path of the form:

```
{prefix}{md5(key)[0:2]}/{md5(key)[2:4]}/{key}
```

where `md5` is the hex MD5 digest of the ASCII-encoded `key`
(`storage/key.py:25-27`). The first two hex bytes and bytes 2-4 form a
2-level fan-out directory to limit entries per prefix.

Two object families:

| family | prefix | `key` value | ref |
|--------|--------|-------------|-----|
| block data | `blocks/` | `{:016x}-{:016x}`.format(uid.left, uid.right) | `database.py:263,269-271` |
| version metadata | `versions/` | `str(version_uid)` | `database.py:149,155-156` |

So a concrete block path looks like:

```
blocks/ab/cd/0000000000000001-0000000000000005
```

and a version metadata path like:

```
versions/12/34/<version-uid-string>
```

Each data object has a paired **metadata object** whose key is the data key
plus the suffix `.meta` (`storage/base.py:63`, `:190`, `:236`, `:310`,
`:372`, `:389`, `:423`). Example:

```
blocks/ab/cd/0000000000000001-0000000000000005.meta
```

`BlockUid.storage_path_to_object` (`database.py:273-278`) validates that the
stripped key is exactly `16 + 1 + 16 = 33` characters and parses the two
64-bit halves as hex. `VersionUid` accepts any string matching
`[-a-zA-Z0-9_.:/@+]+` (`utils.py:227`, `database.py:144`).

### 3.3 Block addressing

A `BlockUid` is a composite of two 32-bit ints `left` and `right`
(`database.py:212-280`) stored in the `blocks.uid_left`/`uid_right` columns
(`Integer`, 4 bytes each). Although the storage key is formatted with 16 hex
digits per half (`{:016x}`), the DB columns are only `Integer` (32-bit),
so in practice each half is a 32-bit value zero-extended to 64 bits in the
path. **This is a latent limitation: values > 2^31-1 cannot be stored in the
signed `Integer` column.** The source comments at `database.py:776-778` note
that `idx` and `uid_right` are "most likely to go to BigInteger in the
future".

- New block UID during backup: `BlockUid(version.id, block.idx + 1)`
  (`benji.py:972`). `version.id` is the autoincrement PK; `block.idx` is the
  0-based block index. So `left = version.id`, `right = idx + 1`.
- Sparse block: `BlockUid(None, None)` (`database.py:283`); no storage object
  is written for it.
- String form (debug, not on-disk): `"{:x}-{:x}"` (`database.py:231`).

### 3.4 Block (content) hash / checksum

- The hash function is configurable via `hashFunction` config
  (`benji.py:48`), default **`BLAKE2b,digest_bits=256`**
  (`schemas/v1/benji.config.yaml:23-26`).
- `BlockHash` (`utils.py:116-155`) imports `Crypto.Hash.<name>`, optionally
  parses `key=value` args (e.g. `BLAKE2b,digest_bits=256`), and requires
  `len(hash.digest()) <= Block.MAXIMUM_CHECKSUM_LENGTH` (64 bytes).
- The checksum stored per block is `BlockHash.data_hexdigest(data)` — the
  **lowercase hex** digest of the **plaintext** block data (`benji.py:945`,
  `benji.py:671`, `benji.py:394`). It is stored in the DB as raw bytes
  (`ChecksumType` unhexlify, §1.3) and in the object metadata as the hex
  string (§3.6).

### 3.5 Deduplication mechanism

Dedup is content-addressed via the checksum, **within a single storage**
(`benji.py:957`, `database.py:596-599`):

1. Read block data, compute `data_checksum = block_hash.hexdigest(data)`.
2. If `data_checksum == sparse_block_checksum` (hash of
   `b'\0' * block_size`) and `block.size == block_size`, the block is
   sparse → store `SparseBlockUid`, `checksum=None`
   (`benji.py:946-955`).
3. Else look up `version.get_block_by_checksum(data_checksum)`, which finds
   any existing **valid** block with the same checksum in any version sharing
   the same `storage_id` (`database.py:596-599`). If found and same `size`,
   reuse its `uid` (no storage write) and increment `bytes_deduplicated`
   (`benji.py:957-968`).
4. Else it is a new block: assign `BlockUid(version.id, idx+1)`, set
   `checksum = data_checksum`, and write to storage
   (`benji.py:970-974`).

Storage objects are therefore **not** content-addressed by their key (the key
is `(version.id, idx+1)`); dedup happens at the DB level via the checksum
lookup, and the same physical storage object (addressed by the original
writer's `BlockUid`) is referenced by multiple `blocks` rows.

On version deletion, unlinked block UIDs are recorded in `deleted_blocks`
with a timestamp (`database.py:384-404`). `DeletedBlock.get_unused_block_uids`
(`database.py:828-881`) returns UIDs older than a grace period (default 3600s)
that no longer appear in any `blocks` row, so the storage objects can be
physically removed.

### 3.6 Per-object format

There is **no binary header** on the data object. The data object contains
exactly the (possibly transformed) payload bytes — see §4/§5 for the
crypto/compression envelopes, which are applied **before** the object is
written and whose parameters live in the sidecar metadata object, not in the
data bytes themselves.

The metadata object is a **UTF-8 encoded JSON** document, serialised
**compact** with `json.dumps(metadata, separators=(',', ':'))`
(`storage/base.py:144`) — no spaces, no indentation. Its structure is built
by `StorageBase._build_metadata` (`storage/base.py:119-144`):

| key | type | presence | meaning |
|-----|------|----------|---------|
| `metadata_version` | str | always | `str(VERSIONS.object_metadata.current)` = **`"2.0.0"`** (`versions.py:13`, `storage/base.py:129`) |
| `created` | str | always | `datetime.utcnow().isoformat(timespec='microseconds') + 'Z'` (`storage/base.py:126,128`) |
| `modified` | str | always | same timestamp as `created` at write time (`storage/base.py:130`) |
| `object_size` | int | always | length in bytes of the **stored** (transformed) data object (`storage/base.py:131`) |
| `size` | int | always | length in bytes of the **original** (pre-transform) payload (`storage/base.py:132`) |
| `checksum` | str | blocks only (and version metadata objects when supplied) | lowercase hex block hash of the plaintext data (`storage/base.py:135-136`) |
| `transforms` | list[dict] | when transforms are active | ordered transform materials (§3.7) |
| `hmac` | dict | when `hmac.key`/`hmac.password` configured | integrity HMAC (§3.8) |

`_decode_metadata` (`storage/base.py:146-168`) enforces:
- `metadata_version` present and within `VERSIONS.object_metadata.supported`
  (`>=1,<3`, `versions.py:13`).
- `created`, `modified`, `object_size`, `size` all present.
- `data_length == metadata['object_size']` (the on-disk object length must
  match `object_size`).

`check_block_metadata` (`storage/base.py:290-306`) additionally enforces
`metadata['size'] == block.size`, the actual data length equals `block.size`,
and `block.checksum == metadata['checksum']`.

### 3.7 Transform encapsulation order

`StorageBase._encapsulate` (`storage/base.py:440-454`) applies the configured
`activeTransforms` **in list order**, each transform receiving the output of
the previous one. The accumulated `transforms_metadata` is a list of dicts in
application order:

```json
[
  {"name": "<transform-name>", "module": "<module-leaf>", "materials": {...}},
  ...
]
```

`module` is the last path component of the transform class's module
(`transform/base.py:20-21`), e.g. `zstd`, `aes_256_gcm`,
`aes_256_gcm_ecc`.

`_decapsulate` (`storage/base.py:456-470`) reverses the list and applies each
transform's `decapsulate` with its own `materials`; it also verifies that the
stored `module` matches the currently configured module for that name.

A transform may return `(None, None)` to mean "no transformation" (zstd does
this when the compressed output is not smaller than the input,
`transform/zstd.py:63-66`); such a transform is **omitted** from
`transforms_metadata` (only entries with non-None data are appended,
`storage/base.py:445-451`).

### 3.8 Object-metadata HMAC (`DictHMAC`)

Source: `storage/dicthmac.py`. Enabled when the storage config has
`hmac.key` (base64) or `hmac.password` + `hmac.kdfSalt` + `hmac.kdfIterations`
(`storage/base.py:88-104`). The HMAC key is 32 bytes, either decoded directly
or derived via `derive_key` (PBKDF2-HMAC-SHA512, §4.3).

`DictHMAC` (`storage/dicthmac.py:11-74`):
- Algorithm: **HMAC-SHA256** (`_HASH_MODULE = SHA256`, `_HASH_NAME = 'sha256'`,
  `dicthmac.py:15-16`).
- The digest is computed over the metadata dict **before** the `hmac` key is
  added, by recursively traversing it (`dicthmac.py:25-39`):
  - dict: for each key in **`sorted(cursor.keys())`**, `hmac.update(str(key).encode('utf-8'))` then recurse the value;
  - list: traverse each element **in order** (no sorting);
  - scalar: `hmac.update(str(cursor).encode('utf-8'))`.
- `add_digest` (`dicthmac.py:43-50`) sets
  `metadata['hmac'] = {'algorithm': 'sha256', 'digest': base64(hmac_digest)}`.
- `verify_digest` (`dicthmac.py:52-74`) removes the `hmac` key, recomputes,
  and compares in non-constant time (`!=`).

The stored `hmac` sub-dict is therefore:

```json
"hmac": {"algorithm": "sha256", "digest": "<base64 HMAC-SHA256>"}
```

---

## 4. Crypto envelope

There are two encryption transforms: `aes_256_gcm` (password or master key)
and `aes_256_gcm_ecc` (ECDH-derived key). Both share the parent
`aes_256_gcm.Transform`. The crypto **materials** live in the object
metadata `transforms` entry, **not** in the data bytes.

### 4.1 Data object layout (encryption)

The encrypted data object is **exactly** the AES-GCM ciphertext of the
plaintext, with **no prefix, no suffix, and no authentication tag**:

```
[ AES-GCM ciphertext bytes (length == len(plaintext)) ]
```

`encapsulate` (`transform/aes_256_gcm.py:42-52`):

```python
envelope_key, encrypted_key = self._create_envelope_key()
envelope_iv = get_random_bytes(16)
encryptor = AES.new(envelope_key, AES.MODE_GCM, nonce=envelope_iv)
materials = {
    'envelope_key': base64.b64encode(encrypted_key).decode('ascii'),
    'iv':          base64.b64encode(envelope_iv).decode('ascii'),
}
return encryptor.encrypt(data), materials
```

> **CRITICAL:** `encryptor.encrypt()` returns only the ciphertext. The GCM
> tag (`encryptor.digest()`) is **never computed and never stored**.
> `decapsulate` (`transform/aes_256_gcm.py:54-76`) calls
> `decryptor.decrypt(data)` and **does not call `verify()`**. GCM is
> effectively used as a stream cipher (CTR-style keystream) with no
> integrity. The port MUST reproduce this — do not add tag verification or
> the ciphertext will not match and existing repos will not restore.

> **CRITICAL:** The nonce/IV is **16 bytes** (`get_random_bytes(16)`,
> `transform/aes_256_gcm.py:44`), not the 12 bytes recommended by GCM.
> PyCryptodome accepts a 16-byte nonce. `decapsulate` enforces
> `len(iv) == 16` (`transform/aes_256_gcm.py:65-67`). The port must use a
> 16-byte random IV.

### 4.2 Materials dict (`aes_256_gcm`)

```json
{
  "envelope_key": "<base64( wrapped 32-byte envelope key )>",
  "iv":           "<base64( 16-byte nonce )>"
}
```

Key wrapping uses **RFC 3394 AES key wrap** (`aes_keywrap.py`):

- `aes_wrap_key(master_key, envelope_key)` → 40-byte output:
  `QUAD.pack(0xa6a6a6a6a6a6a6a6 ^ ...)` (8-byte integrity check) concatenated
  with the 6×n-round wrapped key (`aes_keywrap.py:48-58`).
- Default IV = `0xa6a6a6a6a6a6a6a6` (`aes_keywrap.py:37,48`).
- `aes_unwrap_key` verifies the integrity IV and raises on mismatch
  (`aes_keywrap.py:42-45`).
- KEK = the 32-byte master key. The envelope key is 32 bytes
  (`AES_KEY_LEN = 32`, `transform/aes_256_gcm.py:14`); the wrapped output is
  40 bytes; base64 of that is stored.

Master key source (`transform/aes_256_gcm.py:18-32`):
- If `masterKey` config is present: base64-decode it; must be exactly 32
  bytes.
- Else: derive from `password` + `kdfSalt` (base64) + `kdfIterations` via
  `derive_key(..., key_length=32, ...)` (§4.3).

### 4.3 KDF parameters (`derive_key`)

`utils.py:53-54`:

```python
PBKDF2(password=password, salt=salt, dkLen=key_length,
       count=iterations, hmac_hash_module=SHA512)
```

| parameter | value |
|-----------|-------|
| algorithm | **PBKDF2-HMAC-SHA512** (`Crypto.Protocol.KDF.PBKDF2`, `Crypto.Hash.SHA512`) |
| salt | from config (`kdfSalt` for encryption, `hmac.kdfSalt` for HMAC), base64-decoded |
| iterations | from config (`kdfIterations` / `hmac.kdfIterations`), int |
| dkLen | **32** (both for the AES master key and the HMAC key) |
| password | UTF-8? — passed as-is from config (string); PyCryptodome accepts str/bytes |

There is **no version byte / no magic** in the crypto envelope. The only
versioning is the surrounding `metadata_version` ("2.0.0") and the
`transforms` list ordering.

### 4.4 ECC variant (`aes_256_gcm_ecc`)

Source: `transform/aes_256_gcm_ecc.py`. Subclass of the plain AES-GCM
transform that overrides only key exchange.

Config:
- `eccKey` (required): base64 DER-encoded ECC key (public key for
  encryption, private key for decryption) (`aes_256_gcm_ecc.py:15,18`).
- `eccCurve` (optional, default `"NIST P-384"`) (`aes_256_gcm_ecc.py:16`).

Setup (`aes_256_gcm_ecc.py:14-31`):
- Imports the ECC key via `ECC.import_key`.
- Requires `pointQ.size_in_bytes() >= 32` (AES key length).
- Sets the parent's `masterKey` to 32 zero bytes (so the parent constructor
  does not try to derive a key); the parent's `_create_envelope_key` /
  `_derive_envelope_key` are overridden, so the dummy master key is **never
  used for wrapping**.

ECDH key exchange:
- `_create_envelope_key` (`aes_256_gcm_ecc.py:47-50`): generate an ephemeral
  ECC private key on `ecc_curve`; compute
  `shared_point = receiver_pointQ * ephemeral_privkey.d`; derive
  `shared_key = SHA256( x || y )` where `x` and `y` are the shared point's
  coordinates as big-endian byte strings of length
  `point.size_in_bytes()` (`aes_256_gcm_ecc.py:42-45`). Returns
  `(shared_key, DER(ephemeral_pubkey, compress=True))`.
- `_derive_envelope_key` (`aes_256_gcm_ecc.py:52-54`): parse the stored DER
  public key, compute `shared_point = pubkey.pointQ * receiver_privkey.d`,
  derive `shared_key = SHA256( x || y )` as above.

So in the ECC variant the `envelope_key` material is **not** an RFC 3394
wrapped key — it is the **DER-encoded compressed ephemeral public key**. The
parent's `decapsulate` still base64-decodes `envelope_key`, then calls
`_derive_envelope_key` (overridden) to get the 32-byte shared secret, and
checks `len == 32`. The IV (16 bytes) and the (tag-less) GCM ciphertext are
identical to the plain variant.

ECC materials dict:

```json
{
  "envelope_key": "<base64( DER compressed ephemeral public key )>",
  "iv":           "<base64( 16-byte nonce )>"
}
```

Encryption warns if the configured ECC key contains a private key
(`aes_256_gcm_ecc.py:57-58`); decryption requires the private key
(`aes_256_gcm_ecc.py:62-63`).

### 4.5 Independent-implementation checklist (byte-identical ciphertext)

For the **plain** `aes_256_gcm` transform, to reproduce the exact on-disk
object for a given master key and plaintext:

1. Generate a random 32-byte envelope key `K`.
2. Wrap `K` with RFC 3394 using KEK = master key, IV `0xa6a6a6a6a6a6a6a6`,
   big-endian `>Q` arithmetic (`aes_keywrap.py`). Output 40 bytes → base64 =
   `materials.envelope_key`.
3. Generate a random **16-byte** nonce `N` → base64 = `materials.iv`.
4. AES-256-GCM encrypt the plaintext with key `K`, nonce `N`, **no AAD**.
   Discard the tag. The ciphertext (same length as plaintext) is the data
   object.

(Note: because the envelope key and IV are random per object, the ciphertext
is not deterministic across runs; byte-identical restores are about
**decrypting** to the original plaintext, not reproducing the same
ciphertext. The port must decrypt existing objects correctly, which requires
 honouring all of the above.)

---

## 5. Compression transform (zstd)

Source: `transform/zstd.py`.

### 5.1 Configuration

- `level` (required, int): 1..`zstandard.MAX_COMPRESSION_LEVEL`
  (`zstd.py:15-20`).
- `dictDataFile` (optional): path to a zstd dictionary; loaded as
  `ZstdCompressionDict(content, dict_type=DICT_TYPE_FULLDICT)` and
  precomputed for the configured level (`zstd.py:22-29`).

### 5.2 Compressor settings (`zstd.py:33-49`)

`zstandard.ZstdCompressor` is constructed per-thread with:
- `level=self.level`
- `write_checksum=False` ("We have our own checksum")
- `write_content_size=False` ("We know the uncompressed size")
- `dict_data=self._dict_data` if a dictionary is configured.

The decompressor is `zstandard.ZstdDecompressor(dict_data=...)` with default
settings (`zstd.py:51-59`).

### 5.3 Envelope

benji adds **no custom framing**. The data object is a **raw zstd frame**
as emitted by `ZstdCompressor.compress(data)` (`zstd.py:62`).

Materials (only present when compression actually shrinks the data,
`zstd.py:63-66`):

```json
{"original_size": <int, length of uncompressed input>}
```

`encapsulate` returns `(None, None)` if `len(compressed) >= len(original)`;
in that case no zstd entry is added to `transforms_metadata` and the
uncompressed bytes are stored.

`decapsulate` (`zstd.py:68-70`) requires `materials.original_size` and calls
`decompressor.decompress(data, max_output_size=materials['original_size'])`.

> Because `write_content_size=False` and `write_checksum=False`, the zstd
> frame header does **not** carry the original size or a frame checksum; the
> original size is carried only in the sidecar metadata. The port must keep
> `write_content_size=False`/`write_checksum=False` to reproduce the exact
> frame bytes.

---

## 6. Version / block metadata fields

### 6.1 In-DB `BackupVersion` fields (table `versions`)

From §1.4 / `database.py:312-334`:

| field | type | nullable | meaning |
|-------|------|----------|---------|
| `id` | int | NO | autoincrement PK |
| `uid` | str (`VersionUid`) | NO | version UID, unique |
| `date` | datetime (naive UTC) | NO | creation time |
| `volume` | str(255) | NO | volume name, indexed |
| `snapshot` | str(255) | NO | snapshot name |
| `size` | bigint | NO | image size in bytes |
| `block_size` | int | NO | block size in bytes |
| `storage_id` | int | NO | FK → storages.id |
| `status` | int (enum 1/2/3) | NO | incomplete/valid/invalid |
| `protected` | bool | NO | protected flag |
| `bytes_read` | bigint | YES | stat |
| `bytes_written` | bigint | YES | stat |
| `bytes_deduplicated` | bigint | YES | stat |
| `bytes_sparse` | bigint | YES | stat |
| `duration` | bigint | YES | stat (seconds) |

Derived (non-DB): `blocks_count = ceil(size / block_size)`.

### 6.2 In-DB `Block` fields (table `blocks`)

From §1.6 / `database.py:777-785`:

| field | type | nullable | meaning |
|-------|------|----------|---------|
| `version_id` | int | NO | FK → versions.id (PK part) |
| `idx` | int | NO | 0-based block index (PK part) |
| `uid_left` | int | YES | low 32 bits of BlockUid (NULL = sparse) |
| `uid_right` | int | YES | high 32 bits of BlockUid (NULL = sparse) |
| `size` | int | YES | actual data length of this block |
| `valid` | bool | NO | block validity flag |
| `checksum` | bytes (raw) | YES | block hash digest as raw bytes (hex in Python) |

Composite: `uid = BlockUid(uid_left, uid_right)`. A row with
`uid_left IS NULL AND uid_right IS NULL` and `size == block_size` is a sparse
block and may be absent from the table entirely (synthesised on read).

### 6.3 In-DB `Label` fields (table `labels`)

| field | type | nullable | meaning |
|-------|------|----------|---------|
| `version_id` | int | NO | FK → versions.id (PK part) |
| `name` | str(255) | NO | label name (PK part, indexed) |
| `value` | str(255) | NO | label value (indexed) |

### 6.4 Storage-backend metadata object (JSON, `.meta` sidecar)

This is the per-object JSON described in §3.6. Distinguished from the in-DB
metadata: it lives **in the storage backend** alongside the data object and
is the authoritative source of transform parameters and on-storage size.

For a **block** object (`storage/base.py:119-144`, `:181-187`):

| key | type | presence | meaning |
|-----|------|----------|---------|
| `metadata_version` | str | always | `"2.0.0"` |
| `created` | str | always | ISO8601 µs UTC + `Z` |
| `modified` | str | always | ISO8601 µs UTC + `Z` |
| `object_size` | int | always | stored (transformed) byte length |
| `size` | int | always | original plaintext byte length (`block.size`) |
| `checksum` | str | always (blocks) | lowercase hex block hash of plaintext |
| `transforms` | list[dict] | if transforms active | ordered transform materials (§3.7) |
| `hmac` | dict | if HMAC configured | `{"algorithm":"sha256","digest":<base64>}` |

For a **version metadata** object (`storage/base.py:387-419`,
`write_version`): same key set, except `checksum` is **not** set (no checksum
argument is passed to `_build_metadata`), `size` is the UTF-8 byte length of
the version metadata JSON string, and the data object is the UTF-8 encoded
version metadata (the export format from `database.py:1155-1180`, compact
JSON with `metadata_version` moved to the front).

### 6.5 Database (export/import) metadata vs storage metadata

Two separate "metadata" concepts must not be confused:

- **Database metadata** (`Database.export_*`, `database.py:1033-1180`): a JSON
  document containing `metadata_version` (= `str(VERSIONS.database_metadata.current)`
  = **`"3.0.0"`**, `versions.py:11`; supported `>=1,<4`) plus a `versions`
  array. Each version is the ORM serialisation (ordered: composites, then
  columns, then relationships; `labels` moved to end, `blocks` last,
  `database.py:1101-1146`). Datetimes serialise as
  `isoformat(timespec='microseconds') + 'Z'`; `BlockUid` as
  `{"left":..,"right":..}`; `VersionStatus` as its name; `Label` as its
  `value` (not an object); `Storage` as its `name`. `uid_left`/`uid_right`
  are omitted in favour of the composite `uid`; `storage_id` is omitted in
  favour of `storage`. Compact output uses `separators=(',', ':')`.
- **Object (storage) metadata**: the per-object `.meta` sidecar (§6.4),
  versioned independently with `metadata_version` = `"2.0.0"`.

Supported version matrix (`versions.py:9-14`):

| concept | current | supported spec |
|---------|---------|----------------|
| configuration | `1.0.0` | `>=1,<2` |
| database_metadata | `3.0.0` | `>=1,<4` |
| object_metadata | `2.0.0` | `>=1,<3` |

Import dispatches by major version: `import_v1` (rewrites `V{uid:010d}`,
`name`→`volume`, `snapshot_name`→`snapshot`, `id`→`idx`, list→dict labels,
fakes stats for 1.0.x), `import_v2` (delegates to v3), `import_v3` (current)
(`database.py:1214-1411`).

---

## Notable findings / hazards for the port

1. **GCM tag is discarded.** `aes_256_gcm` never calls `digest()`/`verify()`;
   the data object is tag-less GCM ciphertext. The port must NOT add
   authentication or existing objects will fail to "match" and the envelope
   layout would diverge (`transform/aes_256_gcm.py:42-52,54-76`).
2. **16-byte GCM nonce**, not the standard 12. Enforced on decrypt
   (`transform/aes_256_gcm.py:44,65-67`).
3. **ECC "envelope_key" is a public key, not a wrapped key.** The ECC variant
   silently replaces RFC 3394 wrapping with ECDH+SHA256(x‖y); the material
   key name is reused (`transform/aes_256_gcm_ecc.py:47-54`).
4. **Block UID columns are 32-bit `Integer`**, while the storage path
   zero-extends each half to 64 bits (`{:016x}`). Backing up a version with
   `id > 2^31-1` or a block with `idx+1 > 2^31-1` would overflow. The source
   already comments on a planned `BigInteger` migration
   (`database.py:776-778`). The port must keep the 32-bit column type for
   drop-in compatibility.
5. **Object key fan-out uses MD5** of the ASCII key
   (`storage/key.py:26`) purely for directory sharding; MD5 is not a
   security primitive here.
6. **Dedup is checksum-based, not content-addressed storage.** Storage object
   keys are `(version.id, idx+1)`, not hashes; dedup reuses the original
   writer's `BlockUid` via a DB checksum lookup scoped to the same
   `storage_id` (`benji.py:957-968`, `database.py:596-599`).
7. **Metadata JSON is compact** (`separators=(',', ':')`, no indent) for both
   the per-object `.meta` sidecar and the database export (when `compact=True`)
   (`storage/base.py:144`, `database.py:1173-1175`).
8. **Object metadata HMAC** sorts dict keys but not list elements
   (`dicthmac.py:28-37`); ordering of the `transforms` list therefore affects
   the HMAC. The port must preserve JSON list ordering and Python's
   `sorted()` semantics for dict keys.
9. **Alembic migrations are one-way** (all `downgrade()` are `pass`); a
   freshly initialised DB is stamped at head `3d014d45493f` without running
   the scripts (`database.py:1031`). The port must preserve the chain and the
   stamp behaviour.
10. **`alembic_version` table name** is explicit (`database.py:975`), not the
    Alembic default.
11. **`ChecksumType` stores raw bytes**, not the hex string: bind does
    `unhexlify`, read does `hexlify` (`database.py:190-200`). The metadata
    sidecar stores the hex string. The port must keep this asymmetry.
12. **Block hash is configurable** (default `BLAKE2b,digest_bits=256`); the
    digest length must be ≤ 64 bytes. The chosen hash affects both the DB
    `checksum` value and the `checksum` metadata field, so the port must
    support the same `Crypto.Hash.<name>[,k=v,...]` config syntax
    (`utils.py:116-155`, `schemas/v1/benji.config.yaml:23-26`).
13. **zstd frames have no content size and no checksum** inside the frame
    (`write_content_size=False`, `write_checksum=False`); the original size
    lives only in the sidecar `original_size` material (`transform/zstd.py:41-48`).
