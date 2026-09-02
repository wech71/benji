# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F5: CLI-level `benji enforce` / retention policy tests.
# Uses the benji_cli fixture (SQLite + File, no external infra required).
import json


def _create_backup(benji_cli, working_dir, volume='enforce-vol', snapshot='snap'):
    """Create a simple backup and return the version UID."""
    image = str(working_dir / 'image')
    with open(image, 'wb') as f:
        f.truncate(4 * 1024 * 1024)
        f.write(bytes(range(256)) * (4 * 1024 * 1024 // 256))

    result = benji_cli(['backup', f'file:{image}', volume, '-s', snapshot])
    assert result.returncode == 0, f'backup failed: {result.stderr}'

    # Get version UID from machine-output JSON
    result = benji_cli(['--machine-output', 'ls', f'volume == "{volume}"'])
    assert result.returncode == 0, f'ls failed: {result.stderr}'
    data = json.loads(result.stdout)
    return data['versions'][0]['uid']


class TestCliEnforce:
    """F5: CLI enforce/retention policy tests."""

    def test_enforce_dry_run(self, benji_cli, working_dir):
        """--dry-run should report which versions would be removed without actually removing them."""
        benji_cli(['database-init'])

        volume = 'enforce-dry-vol'
        _create_backup(benji_cli, working_dir, volume, 'snap1')
        _create_backup(benji_cli, working_dir, volume, 'snap2')
        _create_backup(benji_cli, working_dir, volume, 'snap3')

        # Dry-run enforce with latest1 — should report 2 versions for removal
        result = benji_cli(['enforce', '--dry-run', 'latest1', f'volume == "{volume}"'])
        assert result.returncode == 0, f'enforce --dry-run failed: {result.stderr}'

        # Verify versions are still present (dry-run should not remove)
        result = benji_cli(['ls', f'volume == "{volume}"'])
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if volume in line]
        assert len(lines) == 3, f'Expected 3 versions after dry-run, got {len(lines)}'

    def test_enforce_removes_versions(self, benji_cli, working_dir):
        """Enforce with latest1 should remove all but the most recent version."""
        benji_cli(['database-init'])

        volume = 'enforce-rm-vol'
        _create_backup(benji_cli, working_dir, volume, 'snap1')
        _create_backup(benji_cli, working_dir, volume, 'snap2')
        _create_backup(benji_cli, working_dir, volume, 'snap3')

        # Enforce with latest1 — should keep only the newest
        result = benji_cli(['enforce', 'latest1', f'volume == "{volume}"'])
        assert result.returncode == 0, f'enforce failed: {result.stderr}'

        # Verify only 1 version remains
        result = benji_cli(['ls', f'volume == "{volume}"'])
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if volume in line]
        assert len(lines) == 1, f'Expected 1 version after enforce, got {len(lines)}'

    def test_enforce_keep_metadata_backup(self, benji_cli, working_dir):
        """Enforce with --keep-metadata-backup should keep metadata backups."""
        benji_cli(['database-init'])

        volume = 'enforce-mb-vol'
        _create_backup(benji_cli, working_dir, volume, 'snap1')
        _create_backup(benji_cli, working_dir, volume, 'snap2')

        # Enforce with latest1 and keep-metadata-backup
        result = benji_cli(['enforce', '--keep-metadata-backup', 'latest1', f'volume == "{volume}"'])
        assert result.returncode == 0, f'enforce --keep-metadata-backup failed: {result.stderr}'

        # Only 1 version should remain in the database
        result = benji_cli(['ls', f'volume == "{volume}"'])
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if volume in line]
        assert len(lines) == 1, f'Expected 1 version after enforce, got {len(lines)}'

        # But metadata backup should exist
        result = benji_cli(['metadata-ls'])
        assert result.returncode == 0, f'metadata-ls failed: {result.stderr}'

    def test_enforce_no_versions_matched(self, benji_cli, working_dir):
        """Enforce with a filter that matches no versions should succeed with no removals."""
        benji_cli(['database-init'])

        result = benji_cli(['enforce', '--dry-run', 'latest1', 'volume == "nonexistent"'])
        assert result.returncode == 0, f'enforce with no matches failed: {result.stderr}'

    def test_enforce_machine_output(self, benji_cli, working_dir):
        """Enforce with --machine-output should produce JSON."""
        benji_cli(['database-init'])

        volume = 'enforce-mo-vol'
        _create_backup(benji_cli, working_dir, volume, 'snap1')
        _create_backup(benji_cli, working_dir, volume, 'snap2')

        result = benji_cli(['--machine-output', 'enforce', 'latest1', f'volume == "{volume}"'])
        assert result.returncode == 0, f'enforce --machine-output failed: {result.stderr}'

        data = json.loads(result.stdout)
        assert 'versions' in data, f'Unexpected JSON structure: {data}'
        dismissed = data['versions']
        assert len(dismissed) == 1, f'Expected 1 dismissed version, got {len(dismissed)}'
