# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F2/F3: RBD backup → restore → SHA-256 comparison and
# incremental backup via RBD snapshot diff + restore chain verification.
#
# These tests use the conftest.py fixtures (rbd_image, benji_config_file, benji CLI)
# and require a running Ceph container started by run-integration-tests.sh.
# They are skipped automatically when Ceph is not available.
"""
Phase F2: RBD backup from simulated VM image → restore → byte-exact SHA-256 comparison.
Phase F3: Incremental backup via RBD snapshot diff → restore chain verification.
"""
import hashlib
import json
import os
import subprocess

import pytest


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _sha256_device(dev_path: str, size: int) -> str:
    h = hashlib.sha256()
    with open(dev_path, 'rb') as f:
        remaining = size
        while remaining > 0:
            chunk = f.read(min(65536, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


class TestRbdBackupRestore:
    """F2: RBD backup → restore → SHA-256 byte-exact comparison."""

    @pytest.mark.integration
    def test_rbd_backup_restore_sha256(self, benji, rbd_image, working_dir):
        """Back up an RBD image, restore it, and compare SHA-256 checksums."""
        if not rbd_image['dev_path']:
            pytest.skip('RBD image was not mapped to a block device (rbd-nbd unavailable).')

        dev = rbd_image['dev_path']
        image_size = int(rbd_image['size_gb']) * 1024 * 1024 * 1024

        # Write deterministic data to the RBD device
        with open(dev, 'wb') as f:
            f.truncate(image_size)
        pattern = bytes(range(256)) * (4096 // 256)
        for offset in range(0, min(image_size, 64 * 1024 * 1024), 4096):
            with open(dev, 'r+b') as f:
                f.seek(offset)
                f.write(pattern)

        # Compute SHA-256 of the source device
        source_sha = _sha256_device(dev, min(image_size, 64 * 1024 * 1024))

        # Create a file-based source from the device (benji backs up from file: or rbd: sources)
        source_file = str(working_dir / 'rbd_source')
        subprocess.run(['dd', f'if={dev}', f'of={source_file}', 'bs=4M', 'count=16'], check=True, capture_output=True)

        source_sha = _sha256_file(source_file)

        # Initialize database
        result = benji(['database-init'])
        assert result.returncode == 0, f'database-init failed: {result.stderr}'

        # Backup
        volume = 'rbd-test-vol'
        result = benji(['backup', f'file:{source_file}', volume, '-s', 'snap-base'])
        assert result.returncode == 0, f'backup failed: {result.stderr}'

        # Extract version UID from `benji ls --machine-output`
        result = benji(['--machine-output', 'ls', f'volume == "{volume}"'])
        assert result.returncode == 0, f'ls failed: {result.stderr}'
        ls_data = json.loads(result.stdout)
        assert len(ls_data['versions']) > 0, f'No version found for volume {volume}'
        version_uid = ls_data['versions'][0]['uid']

        # Restore to a new file
        restore_path = str(working_dir / 'rbd_restore')
        result = benji(['restore', version_uid, f'file:{restore_path}', '-f'])
        assert result.returncode == 0, f'restore failed: {result.stderr}'

        # Verify SHA-256 match
        restore_sha = _sha256_file(restore_path)
        assert source_sha == restore_sha, (f'SHA-256 mismatch: source={source_sha}, restore={restore_sha}')

    @pytest.mark.integration
    def test_rbd_backup_restore_machine_output(self, benji, rbd_image, working_dir):
        """Backup and restore using --machine-output (JSON) to verify machine-readable parity."""
        if not rbd_image['dev_path']:
            pytest.skip('RBD image was not mapped to a block device (rbd-nbd unavailable).')

        dev = rbd_image['dev_path']
        source_file = str(working_dir / 'rbd_source_json')
        subprocess.run(['dd', f'if={dev}', f'of={source_file}', 'bs=4M', 'count=4'], check=True, capture_output=True)
        source_sha = _sha256_file(source_file)

        benji(['database-init'])
        volume = 'rbd-json-vol'
        result = benji(['--machine-output', 'backup', f'file:{source_file}', volume])
        assert result.returncode == 0, f'backup failed: {result.stderr}'

        # Parse JSON output to get version UID
        import json as json_mod
        backup_data = json_mod.loads(result.stdout)
        assert 'versions' in backup_data, f'Unexpected JSON structure: {backup_data}'
        version_uid = backup_data['versions'][0]['uid']

        restore_path = str(working_dir / 'rbd_restore_json')
        result = benji(['restore', version_uid, f'file:{restore_path}', '-f'])
        assert result.returncode == 0, f'restore failed: {result.stderr}'

        assert source_sha == _sha256_file(restore_path), 'SHA-256 mismatch on machine-output backup/restore'


class TestRbdIncrementalRestore:
    """F3: Incremental backup via RBD snapshot diff + restore chain verification."""

    @pytest.mark.integration
    def test_incremental_backup_restore_chain(self, benji, rbd_image, working_dir):
        """
        Full backup → modify image → incremental backup → restore both → verify SHA-256.
        """
        if not rbd_image['dev_path']:
            pytest.skip('RBD image was not mapped to a block device (rbd-nbd unavailable).')

        dev = rbd_image['dev_path']
        source_file = str(working_dir / 'rbd_source_incr')
        subprocess.run(['dd', f'if={dev}', f'of={source_file}', 'bs=4M', 'count=4'], check=True, capture_output=True)
        original_sha = _sha256_file(source_file)

        benji(['database-init'])
        volume = 'rbd-incr-vol'

        # Full backup
        result = benji(['backup', f'file:{source_file}', volume, '-s', 'snap-full'])
        assert result.returncode == 0, f'full backup failed: {result.stderr}'

        # Get version UID from machine-output JSON
        result = benji(['--machine-output', 'ls', f'volume == "{volume}"'])
        assert result.returncode == 0
        ls_data = json.loads(result.stdout)
        full_uid = ls_data['versions'][0]['uid']

        # Modify the source file
        with open(source_file, 'r+b') as f:
            f.seek(0)
            f.write(b'\xff' * 4096)
            f.seek(1024 * 1024)
            f.write(b'\xab' * 8192)
        modified_sha = _sha256_file(source_file)

        # Create RBD diff hints for the modified regions
        hints = [
            {
                'offset': 0,
                'length': 4096,
                'exists': 'true'
            },
            {
                'offset': 1024 * 1024,
                'length': 8192,
                'exists': 'true'
            },
        ]
        hints_file = str(working_dir / 'rbd_diff_hints.json')
        with open(hints_file, 'w') as f:
            json.dump(hints, f)

        # Incremental backup with hints and base version
        result = benji(['backup', f'file:{source_file}', volume, '-s', 'snap-incr', '-r', hints_file, '-f', full_uid])
        assert result.returncode == 0, f'incremental backup failed: {result.stderr}'

        # Get incremental version UID (latest version for this volume)
        result = benji(['--machine-output', 'ls', f'volume == "{volume}"'])
        assert result.returncode == 0
        ls_data = json.loads(result.stdout)
        assert len(ls_data['versions']) >= 2, 'Expected at least 2 versions'
        incr_uid = ls_data['versions'][-1]['uid']

        # Restore the full backup — should match the original
        restore_full = str(working_dir / 'restore_full')
        result = benji(['restore', full_uid, f'file:{restore_full}', '-f'])
        assert result.returncode == 0, f'restore full failed: {result.stderr}'
        assert original_sha == _sha256_file(restore_full), 'Full backup restore SHA-256 mismatch'

        # Restore the incremental backup — should match the modified image
        restore_incr = str(working_dir / 'restore_incr')
        result = benji(['restore', incr_uid, f'file:{restore_incr}', '-f'])
        assert result.returncode == 0, f'restore incremental failed: {result.stderr}'
        assert modified_sha == _sha256_file(restore_incr), 'Incremental backup restore SHA-256 mismatch'

    @pytest.mark.integration
    def test_rbd_snapshot_diff_restore_chain(self, benji, rbd_image, working_dir, rbd_pool):
        """
        F3 core: Create RBD snapshots, compute diff between snapshots,
        feed to benji as incremental backup hints, verify restore chain.
        """
        if not rbd_image['dev_path']:
            pytest.skip('RBD image was not mapped to a block device (rbd-nbd unavailable).')

        dev = rbd_image['dev_path']
        image_name = rbd_image['name']
        ceph_container = os.environ.get('BENJI_TEST_LABEL', 'benji-integration') + '-ceph'
        pool = rbd_pool

        # Step 1: Write initial data and take a snapshot
        with open(dev, 'wb') as f:
            f.truncate(64 * 1024 * 1024)  # 64MB
        pattern = bytes(range(256)) * (4096 // 256)
        for offset in range(0, 32 * 1024 * 1024, 4096):
            with open(dev, 'r+b') as f:
                f.seek(offset)
                f.write(pattern)

        source_file = str(working_dir / 'snap_source_1')
        subprocess.run(['dd', f'if={dev}', f'of={source_file}', 'bs=4M', 'count=8'], check=True, capture_output=True)
        original_sha = _sha256_file(source_file)

        # Create RBD snapshot
        subprocess.run(['podman', 'exec', ceph_container, 'rbd', 'snap', 'create', f'{pool}/{image_name}@snap1'],
                       check=True,
                       capture_output=True)

        # Step 2: Modify data and take another snapshot
        with open(dev, 'r+b') as f:
            f.seek(0)
            f.write(b'\xff' * 8192)
            f.seek(16 * 1024 * 1024)
            f.write(b'\xab' * 12288)

        modified_file = str(working_dir / 'snap_source_2')
        subprocess.run(['dd', f'if={dev}', f'of={modified_file}', 'bs=4M', 'count=8'], check=True, capture_output=True)
        modified_sha = _sha256_file(modified_file)

        subprocess.run(['podman', 'exec', ceph_container, 'rbd', 'snap', 'create', f'{pool}/{image_name}@snap2'],
                       check=True,
                       capture_output=True)

        # Step 3: Compute RBD diff between snapshots
        diff_result = subprocess.run([
            'podman', 'exec', ceph_container, 'rbd', 'diff', f'{pool}/{image_name}', '--from', 'snap1', '--to', 'snap2',
            '--format', 'json'
        ],
                                     capture_output=True,
                                     text=True,
                                     timeout=30)
        assert diff_result.returncode == 0, f'rbd diff failed: {diff_result.stderr}'

        # rbd diff output format: {"0": {"length": 8192}, "16777216": {"length": 12288}}
        diff_data = json.loads(diff_result.stdout)
        hints = []
        for offset_str, info in diff_data.items():
            offset = int(offset_str)
            length = info['length']
            hints.append({'offset': offset, 'length': length, 'exists': 'true'})

        hints_file = str(working_dir / 'snap_diff_hints.json')
        with open(hints_file, 'w') as f:
            json.dump(hints, f)

        # Step 4: Full backup of snap1 state
        benji(['database-init'])
        volume = 'rbd-snapdiff-vol'

        result = benji(['backup', f'file:{source_file}', volume, '-s', 'snap1'])
        assert result.returncode == 0, f'full backup failed: {result.stderr}'

        result = benji(['--machine-output', 'ls', f'volume == "{volume}"'])
        ls_data = json.loads(result.stdout)
        full_uid = ls_data['versions'][0]['uid']

        # Step 5: Incremental backup using the RBD diff hints
        result = benji(['backup', f'file:{modified_file}', volume, '-s', 'snap2', '-r', hints_file, '-f', full_uid])
        assert result.returncode == 0, f'incremental backup failed: {result.stderr}'

        result = benji(['--machine-output', 'ls', f'volume == "{volume}"'])
        ls_data = json.loads(result.stdout)
        assert len(ls_data['versions']) >= 2
        incr_uid = ls_data['versions'][-1]['uid']

        # Step 6: Restore both and verify SHA-256
        restore_full = str(working_dir / 'restore_snap1')
        result = benji(['restore', full_uid, f'file:{restore_full}', '-f'])
        assert result.returncode == 0
        assert original_sha == _sha256_file(restore_full), 'Snap1 restore SHA-256 mismatch'

        restore_incr = str(working_dir / 'restore_snap2')
        result = benji(['restore', incr_uid, f'file:{restore_incr}', '-f'])
        assert result.returncode == 0
        assert modified_sha == _sha256_file(restore_incr), 'Snap2 restore SHA-256 mismatch'
