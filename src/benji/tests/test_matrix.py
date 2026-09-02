# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F1: Matrix test — backup/restore byte-identity across
# {SQLite,PostgreSQL} x {File,S3} x {full,incremental} x {plain,compressed,encrypted,compressed+encrypted}.
#
# The existing test_smoketest.py covers crypt+compressed for several DBxstorage
# combinations. This file fills the gaps: plain (no transforms), compressed-only,
# and encrypted-only variants, plus the SQLite x S3 combination.
import hashlib
import os
import unittest
import uuid
from unittest import TestCase

from benji.tests.testcase import BenjiTestCaseBase

kB = 1024
MB = kB * 1024

KDF_SALT = 'BBiZ+lIVSefMCdE4eOPX211n/04KY1M4c2SM/9XHUcA='
KDF_ITERATIONS = '20000'
ENCRYPTION_PASSWORD = '"this is a very secret password"'
HMAC_SALT = KDF_SALT
HMAC_ITERATIONS = '1000'
HMAC_PASSWORD = 'Hallo123'


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


class TransformMatrixTestCase(BenjiTestCaseBase):
    """Base class: backup a known image, restore it, and verify byte-identity via SHA-256."""

    IMAGE_SIZE = 4 * MB

    def _create_image(self, path: str) -> str:
        with open(path, 'wb') as f:
            f.truncate(self.IMAGE_SIZE)
        data = bytes(range(256)) * (self.IMAGE_SIZE // 256)
        with open(path, 'r+b') as f:
            f.write(data[:self.IMAGE_SIZE])
        return _sha256_file(path)

    def _patch_image(self, path: str, offset: int, data: bytes) -> str:
        with open(path, 'r+b') as f:
            f.seek(offset)
            f.write(data)
        return _sha256_file(path)

    def _run_matrix(self, transform_variant: str):
        image = os.path.join(self.testpath.path, 'image')
        original_sha = self._create_image(image)

        benji_obj = self.benji_open(init_database=True)
        version = benji_obj.backup(
            version_uid=str(uuid.uuid4()),
            volume='matrix-vol',
            snapshot='snap-' + transform_variant,
            source='file:' + image,
            storage_name='s1',
            block_size=4096,
        )
        version_uid = version.uid
        benji_obj.close()

        restore_path = os.path.join(self.testpath.path, 'restore-' + transform_variant)
        benji_obj = self.benji_open()
        benji_obj.restore(version_uid, 'file:' + restore_path, sparse=False, force=False)
        benji_obj.close()

        self.assertEqual(  # type: ignore[attr-defined]
            original_sha,
            _sha256_file(restore_path),
            f'Restore mismatch for transform variant: {transform_variant}')

    def test_full_backup_restore_plain(self):
        self._run_matrix('plain')

    def test_full_backup_restore_compressed(self):
        self._run_matrix('compressed')

    def test_full_backup_restore_encrypted(self):
        self._run_matrix('encrypted')

    def test_full_backup_restore_compressed_encrypted(self):
        self._run_matrix('compressed+encrypted')

    def test_incremental_backup_restore(self):
        """Full backup, then incremental (differential) backup, then restore both and compare."""
        image = os.path.join(self.testpath.path, 'image')
        original_sha = self._create_image(image)

        benji_obj = self.benji_open(init_database=True)
        full_uid = benji_obj.backup(
            version_uid=str(uuid.uuid4()),
            volume='matrix-vol',
            snapshot='snap-full',
            source='file:' + image,
            storage_name='s1',
            block_size=4096,
        ).uid
        benji_obj.close()

        self._patch_image(image, 0, b'\xff' * 4096)
        self._patch_image(image, self.IMAGE_SIZE // 2, b'\xab' * 8192)
        incremental_sha = _sha256_file(image)

        benji_obj = self.benji_open()
        incr_uid = benji_obj.backup(
            version_uid=str(uuid.uuid4()),
            volume='matrix-vol',
            snapshot='snap-incr',
            source='file:' + image,
            base_version_uid=full_uid,
            storage_name='s1',
            block_size=4096,
        ).uid
        benji_obj.close()

        restore_full = os.path.join(self.testpath.path, 'restore-full')
        benji_obj = self.benji_open()
        benji_obj.restore(full_uid, 'file:' + restore_full, sparse=False, force=False)
        benji_obj.close()
        self.assertEqual(original_sha, _sha256_file(restore_full))

        restore_incr = os.path.join(self.testpath.path, 'restore-incr')
        benji_obj = self.benji_open()
        benji_obj.restore(incr_uid, 'file:' + restore_incr, sparse=False, force=False)
        benji_obj.close()
        self.assertEqual(incremental_sha, _sha256_file(restore_incr))


# ── Config templates ───────────────────────────────────────────────────────
# Each CONFIG follows the exact YAML format used by test_smoketest.py.

_FILE_BASE = """\
            configurationVersion: '1'
            processName: benji
            logFile: /dev/stderr
            hashFunction: BLAKE2b,digest_bits=256
            blockSize: 4096
            ios:
            - name: file
              module: file
              configuration:
                simultaneousReads: 2
            defaultStorage: s1
            storages:
            - name: s1
              module: file
              configuration:
                path: {testpath}/data
                consistencyCheckWrites: True
                simultaneousWrites: 5
                simultaneousReads: 5
{transforms}
{hmac_line}
            databaseEngine: {db_engine}
"""

_TRANSFORMS_NONE = "            transforms: []"
_TRANSFORMS_ZSTD = """\
            transforms:
            - name: zstd
              module: zstd
              configuration:
                level: 1"""
_TRANSFORMS_K1 = f"""\
            transforms:
            - name: k1
              module: aes_256_gcm
              configuration:
                kdfSalt: {KDF_SALT}
                kdfIterations: {KDF_ITERATIONS}
                password: {ENCRYPTION_PASSWORD}"""
_TRANSFORMS_ZSTD_K1 = f"""\
            transforms:
            - name: zstd
              module: zstd
              configuration:
                level: 1
            - name: k1
              module: aes_256_gcm
              configuration:
                kdfSalt: {KDF_SALT}
                kdfIterations: {KDF_ITERATIONS}
                password: {ENCRYPTION_PASSWORD}"""

_HMAC_BLOCK = f"""\
                hmac:
                  kdfSalt: {HMAC_SALT}
                  kdfIterations: {HMAC_ITERATIONS}
                  password: {HMAC_PASSWORD}"""
_HMAC_NONE = ""

_ACTIVE_PLAIN = "                activeTransforms: []"
_ACTIVE_ZSTD = """\
                activeTransforms:
                  - zstd"""
_ACTIVE_K1 = """\
                activeTransforms:
                  - k1"""
_ACTIVE_ZSTD_K1 = """\
                activeTransforms:
                  - zstd
                  - k1"""


def _file_config(testpath: str, active_transforms: str, transforms: str, hmac_block: str, db_engine: str) -> str:
    return (f"            configurationVersion: '1'\n"
            f"            processName: benji\n"
            f"            logFile: /dev/stderr\n"
            f"            hashFunction: BLAKE2b,digest_bits=256\n"
            f"            blockSize: 4096\n"
            f"            ios:\n"
            f"            - name: file\n"
            f"              module: file\n"
            f"              configuration:\n"
            f"                simultaneousReads: 2\n"
            f"            defaultStorage: s1\n"
            f"            storages:\n"
            f"            - name: s1\n"
            f"              module: file\n"
            f"              configuration:\n"
            f"                path: {testpath}/data\n"
            f"                consistencyCheckWrites: True\n"
            f"                simultaneousWrites: 5\n"
            f"                simultaneousReads: 5\n"
            f"{active_transforms}\n"
            f"{hmac_block}\n"
            f"{transforms}\n"
            f"            databaseEngine: {db_engine}\n")


def _s3_config(testpath: str, active_transforms: str, transforms: str, hmac_block: str, db_engine: str) -> str:
    return (f"            configurationVersion: '1'\n"
            f"            processName: benji\n"
            f"            logFile: /dev/stderr\n"
            f"            hashFunction: BLAKE2b,digest_bits=256\n"
            f"            blockSize: 4096\n"
            f"            ios:\n"
            f"            - name: file\n"
            f"              module: file\n"
            f"              configuration:\n"
            f"                simultaneousReads: 2\n"
            f"            defaultStorage: s1\n"
            f"            storages:\n"
            f"            - name: s1\n"
            f"              module: s3\n"
            f"              configuration:\n"
            f"                awsAccessKeyId: minio\n"
            f"                awsSecretAccessKey: minio123\n"
            f"                endpointUrl: http://127.0.0.1:9901/\n"
            f"                bucketName: benji\n"
            f"                addressingStyle: path\n"
            f"                disableEncodingType: false\n"
            f"                consistencyCheckWrites: True\n"
            f"                simultaneousWrites: 3\n"
            f"                simultaneousReads: 3\n"
            f"                simultaneousRemovals: 3\n"
            f"{active_transforms}\n"
            f"{hmac_block}\n"
            f"{transforms}\n"
            f"            databaseEngine: {db_engine}\n")


SQLITE = 'sqlite:///{testpath}/benji.sqlite'
POSTGRES = 'postgresql://benji:verysecret@localhost:15432/benji'

# ── SQLite + File — all transform variants ─────────────────────────────────


class MatrixSQLiteFilePlain(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_PLAIN, _TRANSFORMS_NONE, _HMAC_NONE, SQLITE)


class MatrixSQLiteFileCompressed(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_ZSTD, _TRANSFORMS_ZSTD, _HMAC_NONE, SQLITE)


class MatrixSQLiteFileEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_K1, _TRANSFORMS_K1, _HMAC_BLOCK, SQLITE)


class MatrixSQLiteFileCompressedEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_ZSTD_K1, _TRANSFORMS_ZSTD_K1, _HMAC_BLOCK, SQLITE)


# ── PostgreSQL + File — all transform variants ──────────────────────────────


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_POSTGRESQL', False), 'No PostgreSQL setup available.')
class MatrixPostgreSQLFilePlain(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_PLAIN, _TRANSFORMS_NONE, _HMAC_NONE, POSTGRES)


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_POSTGRESQL', False), 'No PostgreSQL setup available.')
class MatrixPostgreSQLFileCompressed(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_ZSTD, _TRANSFORMS_ZSTD, _HMAC_NONE, POSTGRES)


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_POSTGRESQL', False), 'No PostgreSQL setup available.')
class MatrixPostgreSQLFileEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_K1, _TRANSFORMS_K1, _HMAC_BLOCK, POSTGRES)


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_POSTGRESQL', False), 'No PostgreSQL setup available.')
class MatrixPostgreSQLFileCompressedEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _file_config('{testpath}', _ACTIVE_ZSTD_K1, _TRANSFORMS_ZSTD_K1, _HMAC_BLOCK, POSTGRES)


# ── PostgreSQL + S3 — all transform variants ────────────────────────────────


@unittest.skipIf(
    os.environ.get('UNITTEST_SKIP_POSTGRESQL', False) or os.environ.get('UNITTEST_SKIP_S3', False),
    'No PostgreSQL or S3 setup available.')
class MatrixPostgreSQLS3Plain(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_PLAIN, _TRANSFORMS_NONE, _HMAC_NONE, POSTGRES)


@unittest.skipIf(
    os.environ.get('UNITTEST_SKIP_POSTGRESQL', False) or os.environ.get('UNITTEST_SKIP_S3', False),
    'No PostgreSQL or S3 setup available.')
class MatrixPostgreSQLS3Compressed(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_ZSTD, _TRANSFORMS_ZSTD, _HMAC_NONE, POSTGRES)


@unittest.skipIf(
    os.environ.get('UNITTEST_SKIP_POSTGRESQL', False) or os.environ.get('UNITTEST_SKIP_S3', False),
    'No PostgreSQL or S3 setup available.')
class MatrixPostgreSQLS3Encrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_K1, _TRANSFORMS_K1, _HMAC_BLOCK, POSTGRES)


@unittest.skipIf(
    os.environ.get('UNITTEST_SKIP_POSTGRESQL', False) or os.environ.get('UNITTEST_SKIP_S3', False),
    'No PostgreSQL or S3 setup available.')
class MatrixPostgreSQLS3CompressedEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_ZSTD_K1, _TRANSFORMS_ZSTD_K1, _HMAC_BLOCK, POSTGRES)


# ── SQLite + S3 — selected transform variants ──────────────────────────────


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_S3', False), 'No S3 setup available.')
class MatrixSQLiteS3Plain(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_PLAIN, _TRANSFORMS_NONE, _HMAC_NONE, SQLITE)


@unittest.skipIf(os.environ.get('UNITTEST_SKIP_S3', False), 'No S3 setup available.')
class MatrixSQLiteS3CompressedEncrypted(TransformMatrixTestCase, TestCase):
    CONFIG = _s3_config('{testpath}', _ACTIVE_ZSTD_K1, _TRANSFORMS_ZSTD_K1, _HMAC_BLOCK, SQLITE)
