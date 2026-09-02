# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F6: CLI-level scrub, deep-scrub, ls, metadata-export, metadata-import tests.
# Uses the benji_cli fixture (SQLite + File, no external infra required).
import json
import os


def _create_backup(benji_cli, working_dir, volume='cli-vol', snapshot='snap'):
    """Create a backup and return the version UID."""
    image = str(working_dir / 'image')
    with open(image, 'wb') as f:
        f.truncate(4 * 1024 * 1024)
        f.write(bytes(range(256)) * (4 * 1024 * 1024 // 256))

    result = benji_cli(['backup', f'file:{image}', volume, '-s', snapshot])
    assert result.returncode == 0, f'backup failed: {result.stderr}'

    result = benji_cli(['--machine-output', 'ls', f'volume == "{volume}"'])
    assert result.returncode == 0, f'ls failed: {result.stderr}'
    data = json.loads(result.stdout)
    return data['versions'][0]['uid']


class TestCliScrub:
    """F6: CLI scrub and deep-scrub tests."""

    def test_scrub(self, benji_cli, working_dir):
        """`benji scrub` should verify block existence and metadata integrity."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir)

        result = benji_cli(['scrub', uid])
        assert result.returncode == 0, f'scrub failed: {result.stderr}'

    def test_deep_scrub(self, benji_cli, working_dir):
        """`benji deep-scrub` should verify data and metadata integrity."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir)

        result = benji_cli(['deep-scrub', uid])
        assert result.returncode == 0, f'deep-scrub failed: {result.stderr}'

    def test_deep_scrub_with_source(self, benji_cli, working_dir):
        """`benji deep-scrub -s <source>` should compare version against source."""
        benji_cli(['database-init'])
        image = str(working_dir / 'image')
        uid = _create_backup(benji_cli, working_dir)

        result = benji_cli(['deep-scrub', '-s', f'file:{image}', uid])
        assert result.returncode == 0, f'deep-scrub with source failed: {result.stderr}'

    def test_batch_scrub(self, benji_cli, working_dir):
        """`benji batch-scrub` should scrub multiple versions."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='batch-vol')

        result = benji_cli(['batch-scrub', 'volume == "batch-vol"'])
        assert result.returncode == 0, f'batch-scrub failed: {result.stderr}'

    def test_batch_deep_scrub(self, benji_cli, working_dir):
        """`benji batch-deep-scrub` should deep-scrub multiple versions."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='batch-ds-vol')

        result = benji_cli(['batch-deep-scrub', 'volume == "batch-ds-vol"'])
        assert result.returncode == 0, f'batch-deep-scrub failed: {result.stderr}'


class TestCliLs:
    """F6: CLI ls (version listing) tests."""

    def test_ls_all(self, benji_cli, working_dir):
        """`benji ls` without filter should list all versions."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='ls-vol')

        result = benji_cli(['ls'])
        assert result.returncode == 0, f'ls failed: {result.stderr}'
        assert 'ls-vol' in result.stdout, f'Volume not in ls output: {result.stdout}'

    def test_ls_with_filter(self, benji_cli, working_dir):
        """`benji ls <filter>` should filter versions."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='ls-filter-1')
        _create_backup(benji_cli, working_dir, volume='ls-filter-2')

        result = benji_cli(['ls', 'volume == "ls-filter-1"'])
        assert result.returncode == 0, f'ls with filter failed: {result.stderr}'
        assert 'ls-filter-1' in result.stdout
        assert 'ls-filter-2' not in result.stdout

    def test_ls_include_labels(self, benji_cli, working_dir):
        """`benji ls -l` should include labels in output."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir, volume='ls-label-vol')

        result = benji_cli(['label', uid, 'env=test'])
        assert result.returncode == 0, f'label failed: {result.stderr}'

        result = benji_cli(['ls', '-l', 'volume == "ls-label-vol"'])
        assert result.returncode == 0, f'ls -l failed: {result.stderr}'
        assert 'env=test' in result.stdout, f'Label not in ls output: {result.stdout}'

    def test_ls_include_stats(self, benji_cli, working_dir):
        """`benji ls -s` should include statistics in output."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='ls-stats-vol')

        result = benji_cli(['ls', '-s', 'volume == "ls-stats-vol"'])
        assert result.returncode == 0, f'ls -s failed: {result.stderr}'
        assert 'read' in result.stdout.lower() or 'written' in result.stdout.lower()

    def test_ls_machine_output(self, benji_cli, working_dir):
        """`benji --machine-output ls` should produce JSON."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='ls-mo-vol')

        result = benji_cli(['--machine-output', 'ls'])
        assert result.returncode == 0, f'ls --machine-output failed: {result.stderr}'
        data = json.loads(result.stdout)
        assert 'versions' in data, f'Unexpected JSON: {data}'
        assert len(data['versions']) > 0


class TestCliMetadata:
    """F6: CLI metadata-export, metadata-import, metadata-backup, metadata-restore, metadata-ls tests."""

    def test_metadata_export_stdout(self, benji_cli, working_dir):
        """`benji metadata-export` should output JSON to stdout."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir, volume='meta-exp-vol')

        result = benji_cli(['metadata-export', 'volume == "meta-exp-vol"'])
        assert result.returncode == 0, f'metadata-export failed: {result.stderr}'

        data = json.loads(result.stdout)
        assert 'versions' in data, f'Unexpected JSON structure: {data}'
        assert len(data['versions']) > 0
        assert data['versions'][0]['uid'] == uid

    def test_metadata_export_to_file(self, benji_cli, working_dir):
        """`benji metadata-export -o <file>` should write to file."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='meta-file-vol')

        export_file = str(working_dir / 'export.json')
        result = benji_cli(['metadata-export', '-o', export_file, 'volume == "meta-file-vol"'])
        assert result.returncode == 0, f'metadata-export -o failed: {result.stderr}'
        assert os.path.exists(export_file), 'Export file not created'

        data = json.loads(open(export_file).read())
        assert 'versions' in data

    def test_metadata_export_force_overwrite(self, benji_cli, working_dir):
        """`benji metadata-export -f -o <file>` should overwrite existing file."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='meta-force-vol')

        export_file = str(working_dir / 'export.json')
        with open(export_file, 'w') as f:
            f.write('existing content')

        result = benji_cli(['metadata-export', '-f', '-o', export_file, 'volume == "meta-force-vol"'])
        assert result.returncode == 0, f'metadata-export -f failed: {result.stderr}'

        data = json.loads(open(export_file).read())
        assert 'versions' in data

    def test_metadata_export_refuses_overwrite(self, benji_cli, working_dir):
        """`benji metadata-export -o <file>` should refuse to overwrite existing file."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='meta-refuse-vol')

        export_file = str(working_dir / 'export.json')
        with open(export_file, 'w') as f:
            f.write('existing content')

        result = benji_cli(['metadata-export', '-o', export_file, 'volume == "meta-refuse-vol"'])
        assert result.returncode != 0, 'metadata-export should fail when file exists without -f'

    def test_metadata_backup_and_ls_and_restore(self, benji_cli, working_dir):
        """metadata-backup → rm → metadata-ls → metadata-restore roundtrip."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir, volume='meta-roundtrip-vol')

        # Backup metadata (force to overwrite if already exists in storage)
        result = benji_cli(['metadata-backup', '-f', 'volume == "meta-roundtrip-vol"'])
        assert result.returncode == 0, f'metadata-backup failed: {result.stderr}'

        # List metadata backups
        result = benji_cli(['metadata-ls'])
        assert result.returncode == 0, f'metadata-ls failed: {result.stderr}'
        assert uid in result.stdout, f'UID not in metadata-ls: {result.stdout}'

        # Remove the version from the database (keep metadata backup for restore)
        result = benji_cli(['rm', '-f', '--keep-metadata-backup', uid])
        assert result.returncode == 0, f'rm failed: {result.stderr}'

        # Verify version is gone
        result = benji_cli(['ls', f'uid == "{uid}"'])
        assert result.returncode == 0
        assert uid not in result.stdout or len(result.stdout.strip().split('\n')) <= 2

        # Restore metadata
        result = benji_cli(['metadata-restore', uid])
        assert result.returncode == 0, f'metadata-restore failed: {result.stderr}'

        # Verify version is back
        result = benji_cli(['ls', f'uid == "{uid}"'])
        assert result.returncode == 0
        assert uid in result.stdout, f'UID not restored: {result.stdout}'

    def test_metadata_import_from_file(self, benji_cli, working_dir):
        """`benji metadata-import -i <file>` should import metadata from a file."""
        benji_cli(['database-init'])
        uid = _create_backup(benji_cli, working_dir, volume='meta-import-vol')

        # Export to file
        export_file = str(working_dir / 'import_source.json')
        result = benji_cli(['metadata-export', '-o', export_file, 'volume == "meta-import-vol"'])
        assert result.returncode == 0

        # Remove version
        result = benji_cli(['rm', '-f', uid])
        assert result.returncode == 0

        # Import from file
        result = benji_cli(['metadata-import', '-i', export_file])
        assert result.returncode == 0, f'metadata-import failed: {result.stderr}'

        # Verify version is restored
        result = benji_cli(['ls', f'uid == "{uid}"'])
        assert result.returncode == 0
        assert uid in result.stdout, f'UID not found after import: {result.stdout}'

    def test_storage_stats(self, benji_cli, working_dir):
        """`benji storage-stats` should show storage statistics."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='stats-vol')

        result = benji_cli(['storage-stats'])
        assert result.returncode == 0, f'storage-stats failed: {result.stderr}'
        assert 'objects_count' in result.stdout or 'count' in result.stdout.lower()

    def test_storage_usage(self, benji_cli, working_dir):
        """`benji storage-usage` should show storage usage."""
        benji_cli(['database-init'])
        _create_backup(benji_cli, working_dir, volume='usage-vol')

        result = benji_cli(['storage-usage'])
        assert result.returncode == 0, f'storage-usage failed: {result.stderr}'
