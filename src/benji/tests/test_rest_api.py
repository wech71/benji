# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Phase F7: REST API smoke test — server starts, 1-2 endpoints deliver expected structure.
# Requires the rest-api extras (bottle, gunicorn, webargs) and BENJI_EXPERIMENTAL=1.
import json
import os
import signal
import subprocess
import time
import urllib.request
from importlib.util import find_spec

import pytest


def _rest_api_available() -> bool:
    """Check if REST API dependencies are installed."""
    return all(find_spec(mod) is not None for mod in ('bottle', 'gunicorn', 'webargs'))


rest_api_available = _rest_api_available()


@pytest.mark.skipif(not rest_api_available, reason='REST API dependencies (bottle/gunicorn/webargs) not installed')
class TestRestApiSmoke:
    """F7: REST API smoke test — server starts, endpoints respond with expected structure."""

    @pytest.fixture(autouse=True)
    def _setup_rest_api(self, benji_cli, benji_sqlite_config, working_dir):
        """Start the REST API server for the test."""
        # Initialize database with a backup
        benji_cli(['database-init'])
        image = str(working_dir / 'rest_image')
        with open(image, 'wb') as f:
            f.truncate(4 * 1024 * 1024)
            f.write(bytes(range(256)) * (4 * 1024 * 1024 // 256))
        result = benji_cli(['backup', f'file:{image}', 'rest-vol', '-s', 'snap'])
        assert result.returncode == 0, f'backup failed: {result.stderr}'

        # Start REST API server
        env = dict(os.environ)
        env['BENJI_EXPERIMENTAL'] = '1'
        env['BENJI_WORKING_DIR'] = str(working_dir)

        benji_binary_path = env.get('BENJI_BINARY')
        if not benji_binary_path:
            import shutil
            benji_binary_path = shutil.which('benji')
        assert benji_binary_path, 'benji binary not found'

        bind_port = 18080 + hash(str(working_dir)) % 1000
        cmd = [
            benji_binary_path, '--config-file', benji_sqlite_config, '--no-color', 'rest-api', '-a', '127.0.0.1', '-p',
            str(bind_port)
        ]

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        # Wait for server to start
        url = f'http://127.0.0.1:{bind_port}'
        max_wait = 15
        for _ in range(max_wait):
            try:
                urllib.request.urlopen(f'{url}/apis/core/v1/version-info', timeout=2)
                break
            except Exception:
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate(timeout=5)
                    pytest.fail(f'REST API server exited early:\nstdout: {stdout}\nstderr: {stderr}')
                time.sleep(1)
        else:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)
            pytest.fail(f'REST API server did not start within {max_wait}s:\nstderr: {stderr}')

        self.server_url = url
        self.server_proc = proc
        self.config = benji_sqlite_config

        yield

        # Cleanup: kill the server process group
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

    def _get(self, path):
        url = self.server_url + path
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, body

    def test_version_info_endpoint(self):
        """GET /apis/core/v1/version-info should return version information."""
        status, body = self._get('/apis/core/v1/version-info')
        assert status == 200, f'Unexpected status: {status}, body: {body}'

        data = json.loads(body)
        assert 'version' in data, f'Missing "version" key in response: {data}'
        assert 'configuration_version' in data
        assert 'database_metadata_version' in data
        assert 'object_metadata_version' in data

    def test_storages_endpoint(self):
        """GET /apis/core/v1/storages should return a list of storage names."""
        status, body = self._get('/apis/core/v1/storages')
        assert status == 200, f'Unexpected status: {status}, body: {body}'

        data = json.loads(body)
        assert isinstance(data, list), f'Expected list, got {type(data)}: {data}'
        assert 'file-rvx' in data, f'file-rvx not in storages: {data}'

    def test_versions_list_endpoint(self):
        """GET /apis/core/v1/versions should return a list of versions."""
        status, body = self._get('/apis/core/v1/versions')
        assert status == 200, f'Unexpected status: {status}, body: {body}'

        data = json.loads(body)
        assert 'versions' in data, f'Missing "versions" key: {data}'
        assert len(data['versions']) > 0, f'No versions returned: {data}'
        assert data['versions'][0]['volume'] == 'rest-vol', f'Unexpected volume: {data["versions"][0]}'

    def test_database_init_endpoint(self):
        """POST /apis/core/v1/database should initialize the database (idempotent)."""
        url = self.server_url + '/apis/core/v1/database'
        req = urllib.request.Request(url, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status in (200, 204), f'Unexpected status: {resp.status}'
