"""Clean-build smoke for the redsql image: Redis stream in, TimescaleDB rows out.

Builds images/redsql with --no-cache, starts a throwaway Timescale database with the
real schema image (ait1/rdp-database), a throwaway Redis, and the repository's own
data-sync-service/config.yml; publishes one weather forecast to the configured stream
and checks that rows land in the `forecasts` table.

Every container, network and image belongs to this invocation (unique names); the
config is the repository file mounted read-only, and the network aliases `redis` and
`timescale` make it work unchanged. Only what this run created is removed, including
the database's anonymous data volume.

Usage: DOCKER="sudo -n docker" python tests/smoke_redsql_image.py
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = os.environ.get("DOCKER", "docker").split()
REDIS_IMAGE = "redis:7.2.17-alpine"
TIMESCALE_IMAGE = "timescale/timescaledb-ha@sha256:3f0b3f6bdf4912878444a36e6113a18346309583c4d1a61d81a0c511342a1afd"
SCHEMA_IMAGE = "ait1/rdp-database:latest-dev"
STREAM = "geosphere.forecasts.nwp.WIEN-HOHE_WARTE"
ADMIN = ("postgres", "smk-" + uuid.uuid4().hex[:10])
SOURCE = ("smokesource", "smk-" + uuid.uuid4().hex[:10])
VIS = ("smokevis", "smk-" + uuid.uuid4().hex[:10])
PUBVIS = ("smokepub", "smk-" + uuid.uuid4().hex[:10])
REDIS_PASSWORD = "smk-" + uuid.uuid4().hex[:10]
N = 6
RUN = uuid.uuid4().hex[:8]
DB, REDIS, SYNC = (f"smoke-rs-{x}-{RUN}" for x in ("db", "redis", "sync"))
created = {"containers": [], "networks": [], "images": []}


def docker(*args, check=True, **kw):
    return subprocess.run([*DOCKER, *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)


def start(name, *args):
    """docker run -d; remember the container only if this invocation created it."""
    r = docker("run", "-d", "--name", name, *args, check=False)
    if r.returncode != 0:
        print(r.stdout)
        raise SystemExit(f"could not start {name}")
    created["containers"].append(name)


def cleanup():
    for c in reversed(created["containers"]):
        docker("rm", "-fv", c, check=False)  # -v: also the anonymous data volume
    for n in created["networks"]:
        docker("network", "rm", n, check=False)
    for i in created["images"]:
        docker("rmi", "-f", i, check=False)


def message():
    hours = [f"2026-06-01T{h:02d}:00:00+00:00" for h in range(N)]
    return {
        "longitude": "16.362", "latitude": "48.255", "altitude": "null",
        "observation_time": json.dumps(hours),
        "forecast_time": '"2026-06-01T00:00+00:00"',
        "station": '"SMOKE"', "data_provider": '"SMOKE.NWP"', "device_name": "null",
        "air_temperature_2m": json.dumps([10.0 + h for h in range(N)]),
    }


def psql(sql):
    return docker("exec", "-e", f"PGPASSWORD={ADMIN[1]}", DB, "psql", "-U", ADMIN[0], "-d", "rdp_db", "-tAc", sql, check=False).stdout.strip()


def main():
    net = f"smoke-rs-{RUN}"
    tag = f"smoke/redsql:{RUN}"
    try:
        print("== redsql: building (clean, --no-cache)")
        b = docker("build", "--no-cache", "-q", "-t", tag, str(ROOT / "images" / "redsql"), check=False)
        if b.returncode != 0:
            print(b.stdout)
            raise SystemExit("redsql: build failed (includes `uv pip check` on the venv)")
        created["images"].append(tag)
        r = docker("network", "create", net, check=False)
        if r.returncode != 0:
            raise SystemExit(f"could not create network {net}: {r.stdout}")
        created["networks"].append(net)
        start(REDIS, "--network", net, "--network-alias", "redis", REDIS_IMAGE, "redis-server", "--requirepass", REDIS_PASSWORD)
        start(DB, "--network", net, "--network-alias", "timescale", "-e", f"POSTGRES_USER={ADMIN[0]}",
              "-e", f"POSTGRES_PASSWORD={ADMIN[1]}", "-e", "TIMESCALEDB_TELEMETRY=off", TIMESCALE_IMAGE)
        for _ in range(60):
            if docker("exec", DB, "pg_isready", "-U", ADMIN[0], check=False).returncode == 0:
                time.sleep(5)
                break
            time.sleep(2)
        s = docker("run", "--rm", "--network", net, "-e", f"POSTGRES_USER={ADMIN[0]}", "-e", f"POSTGRES_PASSWORD={ADMIN[1]}",
                   "-e", f"POSTGRES_DATA_SOURCE_USER={SOURCE[0]}", "-e", f"POSTGRES_DATA_SOURCE_PASSWORD={SOURCE[1]}",
                   "-e", f"POSTGRES_DATA_VIS_USER={VIS[0]}", "-e", f"POSTGRES_DATA_VIS_PASSWORD={VIS[1]}",
                   "-e", f"POSTGRES_DATA_PUB_VIS_USER={PUBVIS[0]}", "-e", f"POSTGRES_DATA_PUB_VIS_PASSWORD={PUBVIS[1]}",
                   "-e", "RDP_POSTGRES_HOST=timescale", SCHEMA_IMAGE, check=False)
        if s.returncode != 0:
            print(s.stdout[-2000:])
            raise SystemExit("schema image failed")
        start(SYNC, "--network", net, "-e", f"POSTGRES_USER={SOURCE[0]}", "-e", f"POSTGRES_PASSWORD={SOURCE[1]}",
              "-e", f"REDIS_PASSWORD={REDIS_PASSWORD}",
              "-v", f"{ROOT / 'data-sync-service' / 'config.yml'}:/etc/redsql/config.yml:ro", tag)
        time.sleep(8)
        args = ["XADD", STREAM, "*"] + [x for kv in message().items() for x in kv]
        docker("run", "--rm", "--network", net, REDIS_IMAGE, "redis-cli", "-h", "redis", "-a", REDIS_PASSWORD, "--no-auth-warning", *args)
        rows = "0"
        for _ in range(30):
            rows = psql("SELECT count(*) FROM forecasts")
            if rows.isdigit() and int(rows) >= N:
                break
            time.sleep(2)
        state = docker("inspect", "-f", "{{.State.Status}}", SYNC).stdout.strip()
        if not (rows.isdigit() and int(rows) >= N) or state != "running":
            print(docker("logs", SYNC).stdout[-3000:])
            raise SystemExit(f"redsql: expected >= {N} rows in forecasts and a running service, got rows={rows!r} state={state}")
        sample = psql("SELECT dp.name FROM forecasts f JOIN data_points dp ON dp.id = f.dp_id LIMIT 1")
        print(f"   OK: {rows} rows in forecasts; running; data point: {sample or 'n/a'}")
        print("redsql image smoke: PASSED")
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
