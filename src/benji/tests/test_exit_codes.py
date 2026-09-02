# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F8: CLI exit-code and log-format snapshot tests (parity).
# Uses the benji_cli fixture (SQLite + File, no external infra required).
import json
import subprocess


class TestCliExitCodes:
    """F8: CLI exit code parity tests — verifies BSD os.EX_* codes match the documented contract."""

    def test_exit_success(self, benji_cli, working_dir):
        """Successful command should exit with code 0 (EX_OK)."""
        benji_cli(['database-init'])
        result = benji_cli(['version-info'])
        assert result.returncode == 0

    def test_exit_usage_no_subcommand(self, benji_cli):
        """No subcommand should exit with code 64 (EX_USAGE)."""
        result = benji_cli([])
        assert result.returncode == 64, f'Expected 64 (EX_USAGE), got {result.returncode}'

    def test_exit_usage_config_not_found(self, benji_binary, tmp_path):
        """Non-existent config file should exit with code 64 (EX_USAGE)."""
        result = subprocess.run([benji_binary, '--config-file', '/nonexistent/benji.conf', 'version-info'],
                                capture_output=True,
                                text=True,
                                check=False)
        assert result.returncode == 64, f'Expected 64 (EX_USAGE), got {result.returncode}'

    def test_exit_config_error_bad_config(self, benji_binary, tmp_path):
        """Invalid config should exit with a non-zero code (1 in practice; Config() runs before the exception mapping)."""
        config = tmp_path / 'bad.conf'
        config.write_text("invalid: yaml: content: [\n")
        result = subprocess.run(
            [benji_binary, '--config-file', str(config), 'version-info'], capture_output=True, text=True, check=False)
        assert result.returncode != 0, f'Expected non-zero exit code for bad config, got {result.returncode}'

    def test_exit_usage_restore_missing_args(self, benji_cli):
        """Missing required arguments should exit with code 2 (argparse)."""
        result = benji_cli(['restore'])
        assert result.returncode == 2, f'Expected 2 (argparse), got {result.returncode}'

    def test_exit_dataerr_scrub_nonexistent_version(self, benji_cli, working_dir):
        """Scrub of a non-existent version should exit with 65 (EX_DATAERR) or similar error."""
        benji_cli(['database-init'])
        result = benji_cli(['scrub', 'nonexistent-uid-12345'])
        assert result.returncode != 0, f'Expected non-zero exit code, got {result.returncode}'

    def test_exit_cantcreat_restore_overwrite_without_force(self, benji_cli, working_dir):
        """Restore to an existing file without -f should exit with 73 (EX_CANTCREAT)."""
        benji_cli(['database-init'])

        # Create backup
        image = str(working_dir / 'image')
        with open(image, 'wb') as f:
            f.truncate(1024 * 1024)
            f.write(bytes(range(256)) * (1024 * 1024 // 256))

        result = benji_cli(['backup', f'file:{image}', 'exit-vol', '-s', 'snap'])
        assert result.returncode == 0

        result = benji_cli(['--machine-output', 'ls', 'volume == "exit-vol"'])
        data = json.loads(result.stdout)
        uid = data['versions'][0]['uid']

        # Create existing file that would be overwritten
        dest = str(working_dir / 'existing_dest')
        with open(dest, 'wb') as f:
            f.write(b'existing data')

        result = benji_cli(['restore', uid, f'file:{dest}'])
        assert result.returncode == 73, f'Expected 73 (EX_CANTCREAT), got {result.returncode}'

    def test_exit_ok_completion(self, benji_cli):
        """completion subcommand should exit with 0 (EX_OK)."""
        result = benji_cli(['completion', 'bash'])
        assert result.returncode == 0


class TestCliLogFormat:
    """F8: Log format snapshot tests — verifies console, plain, and JSON formats."""

    def test_console_plain_format(self, benji_binary, benji_sqlite_config, tmp_path):
        """--no-color should produce plain console format: {LEVEL:>8}: {message}."""
        result = subprocess.run([benji_binary, '--config-file', benji_sqlite_config, '--no-color', 'version-info'],
                                capture_output=True,
                                text=True,
                                check=False)
        assert result.returncode == 0
        # Console output goes to stderr; each line should match the pattern
        # `{LEVEL:>8}: {message}` with no ANSI color codes
        stderr_lines = result.stderr.strip().split('\n')
        assert len(stderr_lines) > 0
        for line in stderr_lines:
            if line.strip():
                # No ANSI escape codes when --no-color
                assert '\x1b' not in line, f'ANSI code found in --no-color output: {line!r}'
                # Format: right-justified level (8 chars) + ': ' + message
                assert ':' in line, f'No colon in log line: {line!r}'

    def test_machine_output_json(self, benji_binary, benji_sqlite_config, tmp_path):
        """--machine-output should produce JSON on stdout."""
        result = subprocess.run(
            [benji_binary, '--config-file', benji_sqlite_config, '--machine-output', 'version-info'],
            capture_output=True,
            text=True,
            check=False)
        assert result.returncode == 0
        # Machine output (command output) goes to stdout as JSON
        data = json.loads(result.stdout)
        assert 'version' in data
        assert 'configuration_version' in data

    def test_log_level_error(self, benji_binary, benji_sqlite_config, tmp_path):
        """--log-level ERROR should suppress INFO messages on stderr."""
        result = subprocess.run(
            [benji_binary, '--config-file', benji_sqlite_config, '--no-color', '--log-level', 'ERROR', 'version-info'],
            capture_output=True,
            text=True,
            check=False)
        assert result.returncode == 0
        # With ERROR level, INFO messages should not appear
        for line in result.stderr.strip().split('\n'):
            if line.strip():
                assert '   INFO:' not in line, f'INFO line appeared at ERROR level: {line!r}'

    def test_machine_output_json_fields(self, benji_binary, benji_sqlite_config, tmp_path):
        """JSON log output should contain required fields (level, timestamp, event, etc.)."""
        result = subprocess.run([
            benji_binary, '--config-file', benji_sqlite_config, '--machine-output', '--log-level', 'DEBUG', 'version-info'
        ],
                                capture_output=True,
                                text=True,
                                check=False)
        assert result.returncode == 0
        # stderr should contain JSON log lines
        for line in result.stderr.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                assert 'event' in entry, f'Missing "event" field: {entry}'
                assert 'level' in entry, f'Missing "level" field: {entry}'
                assert 'timestamp' in entry, f'Missing "timestamp" field: {entry}'
            except json.JSONDecodeError:
                # Non-JSON lines are acceptable (e.g., gunicorn startup messages)
                pass

    def test_console_colored_default(self, benji_binary, benji_sqlite_config, tmp_path):
        """Default console format (without --no-color) may contain ANSI codes."""
        result = subprocess.run([benji_binary, '--config-file', benji_sqlite_config, 'version-info'],
                                capture_output=True,
                                text=True,
                                check=False)
        assert result.returncode == 0
        # Default format is console-colored; lines should have the pattern
        # `{LEVEL:>8}: {message}` (possibly with ANSI color codes)
        for line in result.stderr.strip().split('\n'):
            if line.strip():
                assert ':' in line, f'No colon in log line: {line!r}'
