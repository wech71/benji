# Podman Integration Test Infrastructure

> Self-contained test harness for benji's Python 3.13+ port.  
> All backing services (Ceph, MinIO, PostgreSQL) run as Podman containers
> tagged with `app=benji` and `BENJI_TEST_LABEL` so they are always cleanable.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  run-integration-tests.sh  (Bash, set -euo pipefail)            │
│                                                                 │
│  Creates podman network  (subnet from CEPH_PUBLIC_NETWORK)      │
│                                                                 │
│  ┌──────────────┐  ┌──────────┐  ┌────────────┐                │
│  │  Ceph demo   │  │  MinIO   │  │ PostgreSQL │                │
│  │  :6789/udp   │  │ :9000    │  │ :5432      │                │
│  │  RGW :8080   │  │ :9001    │  │            │                │
│  └──────┬───────┘  └────┬─────┘  └────┬───────┘                │
│         │               │             │                         │
│         └───────────────┼─────────────┘                         │
│                         │  podman network                       │
│                         ▼                                       │
│               ┌─────────────────┐                               │
│               │  pytest -m int  │  ← conftest.py reads env vars │
│               └─────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Container Images

| Container | Image | Purpose |
|-----------|-------|---------|
| `benji-integration-ceph` | `quay.io/ceph/ceph:v17.2.8` | Ceph Quincy single-node demo (mon + osd + rgw) |
| `benji-integration-minio` | `quay.io/minio/minio:latest` | S3-compatible object store (bucket: `benji-test-bucket`) |
| `benji-integration-postgres` | `docker.io/library/postgres:16` | PostgreSQL 16 for `benji database` |

---

## Rootless vs Rootful

### Rootless (recommended for workstations / dev laptops)

Podman runs fully in user namespace — no daemon required, no root privileges.
The integration script auto-detects the socket at
`/run/user/$(id -u)/podman/podman.sock` and starts a transient service
if needed.

Requirements:
- `podman` ≥ 4.0
- `newuidmap` / `newgidmap` (part of `shadow` package on Debian)
- `/etc/subuid` and `/etc/subgid` entries for your user (automatic on Debian ≥12)

Caveat: Rootless networking has limitations (no host networking, no `--privileged`
in most setups). The Ceph demo container **requires `--privileged`** because it
manages kernel modules and host block devices. **Run the test suite from a
dedicated test VM, not your workstation.**

### Rootful (fallback for CI / VMs without subuid)

```bash
sudo ./run-integration-tests.sh
```

Podman connects to `/var/run/podman/podman.sock`. Full kernel access is available.
Only appropriate in an isolated VM.

---

## Ceph Demo Mode — Important Caveats

Ceph's official demo container (`quay.io/ceph/ceph:v17.2.8` with `CEPH_DAEMON=demo`)
starts a **simulated single-node cluster** for development / testing. It is **not**
a production deployment and:

- **Replaces** `/etc/ceph` and `/var/lib/ceph` inside the container (host not touched)
- **Requires `--privileged`** to load kernel modules and access block devices
- **Exposes RGW** on `${RGW_PORT}` (default 8080) — S3 endpoint for benji's `s3` backend
- **Creates an admin keyring** at `/etc/ceph/ceph.client.admin.keyring` — used by benji
- **Creates a default RBD pool** (`rbd`) but the test harness creates its own (`benji_test_pool`)
- **Health check**: `ceph health` inside the container must show `HEALTH_OK`

The demo cluster does **not** persist data between container restarts. Each test run
starts a fresh cluster. This is intentional — avoids state leakage between test cases.

**Security note**: The admin keyring is written to an environment variable
(`BENJI_TEST_CEPH_KEYRING_BASE64`) only for the lifetime of the script. It is never
written to disk. In a real environment, use `--keyring` in a secrets mount.

---

## Running the Tests

### Quick start (rootful — isolated VM)

```bash
# Override any setting via environment
export BENJI_TEST_LABEL="my-run-$(date +%s)"
export RGW_PORT=8081

./run-integration-tests.sh
```

### Keep containers alive after test run (debug mode)

```bash
./run-integration-tests.sh --keep
# containers stay up, no cleanup on EXIT
# when done:
source <(tail -n +57 run-integration-tests.sh)  # loads cleanup fn
cleanup
```

### Pass extra pytest arguments

```bash
./run-integration-tests.sh -- -k "test_rbd" -x
```

### Override image tags (CI / air-gap)

```bash
CEPH_IMAGE="my-registry.example.com/ceph/ceph:v17.2.8" \
MINIO_IMAGE="my-registry.example.com/minio/minio:latest" \
POSTGRES_IMAGE="my-registry.example.com/postgres:16" \
./run-integration-tests.sh
```

---

## Environment Variables

All defaults are in `.env.example`. The harness reads these at startup:

| Variable | Default | Description |
|----------|---------|-------------|
| `BENJI_TEST_LABEL` | `benji-integration` | Podman label value — all resources tagged |
| `CEPH_IMAGE` | `quay.io/ceph/ceph:v17.2.8` | Ceph demo image |
| `MINIO_IMAGE` | `quay.io/minio/minio:latest` | MinIO image |
| `POSTGRES_IMAGE` | `docker.io/library/postgres:16` | PostgreSQL image |
| `RBD_POOL` | `benji_test_pool` | RBD pool created for tests |
| `S3_BUCKET` | `benji-test-bucket` | MinIO bucket |
| `S3_ENDPOINT` | `http://localhost:9000` | S3 endpoint URL |
| `PG_PORT` | `5432` | PostgreSQL host port |
| `RGW_PORT` | `8080` | Ceph RGW HTTP port |
| `CEPH_PUBLIC_NETWORK` | `172.30.0.0/28` | Podman network subnet |
| `MINIO_ROOT_USER` | `minioadmin` | MinIO access key |
| `MINIO_ROOT_PASS` | `minioadmin123` | MinIO secret key |
| `PG_PASSWORD` | `benji_test_pass` | PostgreSQL password |

---

## Systemd Quadlet Units (Alternative to Shell Script)

Instead of the shell entrypoint, you can use [systemd quadlets](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
to manage containers as native systemd services:

```bash
# Copy *.container files to ~/.config/containers/systemd/
mkdir -p ~/.config/containers/systemd
cp tests/integration/podman/*.container ~/.config/containers/systemd/

# Reload systemd, start services
systemctl --user daemon-reload
systemctl --user start benji-ceph.service
systemctl --user start benji-minio.service
systemctl --user start benji-postgres.service

# Check status
systemctl --user status benji-ceph.service
```

Quadlets are **idempotent** — `podman generate systemd` style, `Restart=always`.
Suitable for developers who prefer systemd-native container management.

---

## Troubleshooting

### "cannot start: privileged mode not allowed"

Rootless Podman cannot grant `--privileged`. Run the test harness in a **dedicated VM**
with root access, or use rootful Podman (`sudo`).

### "Ceph health: HEALTH_ERR" after 180s

Ceph demo takes 60–120s to form quorum on first start. If the container is still
starting, increase `MAX_WAIT=300` and re-run. If it persists, check container logs:

```bash
podman logs benji-integration-ceph
```

### MinIO health probe fails

MinIO may need `--shm-size=256m` for large operations. The harness sets none by
default — add if needed:

```bash
export MINIO_EXTRA_ARGS="--readline"
# or patch the podman run command in run-integration-tests.sh
```

### PostgreSQL connection refused

Verify port mapping: `podman port benji-integration-postgres`. Should show `5432/tcp`.
If occupied, set `PG_PORT=5433`.

### "pg_isready not in PATH"

The script falls back to HTTP probe. Install `postgresql-client` to get `pg_isready`
in the host shell (not required inside the container).

---

## Cleanup

The `trap cleanup EXIT INT TERM` in the entrypoint guarantees removal of all labeled
resources even on Ctrl+C. Idempotent — safe to run multiple times.

To manually remove everything:

```bash
podman rm -f $(
    podman ps -a --format '{{.ID}}' --filter label=benji-integration
)
podman network rm benji-integration_net
podman volume rm $(
    podman volume ls --format '{{.Name}}' --filter label=benji-integration
)
```

---

## CI / Air-Gap Environment

For isolated environments without access to public container registries:

1. Mirror images into your private registry:
   ```bash
   podman pull quay.io/ceph/ceph:v17.2.8
   podman push my-registry/ceph:v17.2.8
   ```
2. Export env overrides:
   ```bash
   export CEPH_IMAGE="my-registry/ceph:v17.2.8"
   export MINIO_IMAGE="my-registry/minio:latest"
   export POSTGRES_IMAGE="my-registry/postgres:16"
   ```

No changes to test code or fixtures are needed.
