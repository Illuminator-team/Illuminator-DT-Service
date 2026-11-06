"""Clean-build smoke for the redsql image: Redis stream in, TimescaleDB rows out.

Builds images/redsql with --no-cache, starts a throwaway Timescale database with the
real schema image (ait1/rdp-database), a throwaway Redis, and the repository's own
data-sync-service/config.yml; publishes one weather forecast to the configured stream
and checks that rows land in the `forecasts` table.

Usage: DOCKER="sudo -n docker" python tests/smoke_redsql_image.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = os.environ.get("DOCKER", "docker").split()
REDIS_IMAGE = "redis:7.2.17-alpine"
TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg14-latest"
SCHEMA_IMAGE = "ait1/rdp-database:latest-dev"
STREAM = "geosphere.forecasts.nwp.WIEN-HOHE_WARTE"
ADMIN = ("postgres", "smk-" + uuid.uuid4().hex[:10])
SOURCE = ("smokesource", "smk-" + uuid.uuid4().hex[:10])
VIS = ("smokevis", "smk-" + uuid.uuid4().hex[:10])
PUBVIS = ("smokepub", "smk-" + uuid.uuid4().hex[:10])
REDIS_PASSWORD = "smk-" + uuid.uuid4().hex[:10]
N = 6


def docker(*args, check=True, **kw):
    return subprocess.run([*DOCKER, *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)


def message():
    hours = [f"2026-06-01T{h:02d}:00:00+00:00" for h in range(N)]
    return {
        "longitude": "16.362", "latitude": "48.255", "altitude": "null",
        "observation_time": json.dumps(hours),
        "forecast_time": '"2026-06-01T00:00+00:00"',
        "station": '"SMOKE"', "data_provider": '"SMOKE.NWP"', "device_name": "null",
        "air_temperature_2m": json.dumps([10.0 + h for h in range(N)]),
    }


def psql(net, sql):
    return docker("exec", "-e", f"PGPASSWORD={ADMIN[1]}", "smoke-rs-db", "psql", "-U", ADMIN[0], "-d", "rdp_db", "-tAc", sql, check=False).stdout.strip()


def main():
    net = f"smoke-rs-{uuid.uuid4().hex[:8]}"
    tag = f"smoke/redsql:{uuid.uuid4().hex[:8]}"
    print("== redsql: building (clean, --no-cache)")
    b = docker("build", "--no-cache", "-q", "-t", tag, str(ROOT / "images" / "redsql"), check=False)
    if b.returncode != 0:
        print(b.stdout)
        raise SystemExit("redsql: build failed (includes `uv pip check` on the venv)")
    docker("network", "create", net)
    work = tempfile.mkdtemp(prefix="smoke-rs-")
    cfg = Path(work) / "config.yml"
    text = (ROOT / "data-sync-service" / "config.yml").read_text()
    cfg.write_text(text.replace("@timescale/rdp_db", "@smoke-rs-db/rdp_db").replace("host: redis", "host: smoke-rs-redis"))
    os.chmod(work, 0o755)
    os.chmod(cfg, 0o644)
    try:
        docker("run", "-d", "--name", "smoke-rs-redis", "--network", net, REDIS_IMAGE, "redis-server", "--requirepass", REDIS_PASSWORD)
        docker("run", "-d", "--name", "smoke-rs-db", "--network", net, "-e", f"POSTGRES_USER={ADMIN[0]}",
               "-e", f"POSTGRES_PASSWORD={ADMIN[1]}", "-e", "TIMESCALEDB_TELEMETRY=off", TIMESCALE_IMAGE)
        for _ in range(60):
            if docker("exec", "smoke-rs-db", "pg_isready", "-U", ADMIN[0], check=False).returncode == 0:
                time.sleep(5)
                break
            time.sleep(2)
        s = docker("run", "--rm", "--network", net, "-e", f"POSTGRES_USER={ADMIN[0]}", "-e", f"POSTGRES_PASSWORD={ADMIN[1]}",
                   "-e", f"POSTGRES_DATA_SOURCE_USER={SOURCE[0]}", "-e", f"POSTGRES_DATA_SOURCE_PASSWORD={SOURCE[1]}",
                   "-e", f"POSTGRES_DATA_VIS_USER={VIS[0]}", "-e", f"POSTGRES_DATA_VIS_PASSWORD={VIS[1]}",
                   "-e", f"POSTGRES_DATA_PUB_VIS_USER={PUBVIS[0]}", "-e", f"POSTGRES_DATA_PUB_VIS_PASSWORD={PUBVIS[1]}",
                   "-e", "RDP_POSTGRES_HOST=smoke-rs-db", SCHEMA_IMAGE, check=False)
        if s.returncode != 0:
            print(s.stdout[-2000:])
            raise SystemExit("schema image failed")
        docker("run", "-d", "--name", "smoke-rs-sync", "--network", net,
               "-e", f"POSTGRES_USER={SOURCE[0]}", "-e", f"POSTGRES_PASSWORD={SOURCE[1]}",
               "-e", f"REDIS_PASSWORD={REDIS_PASSWORD}", "-v", f"{cfg}:/etc/redsql/config.yml:ro", tag)
        time.sleep(8)
        args = ["XADD", STREAM, "*"] + [x for kv in message().items() for x in kv]
        docker("run", "--rm", "--network", net, REDIS_IMAGE, "redis-cli", "-h", "smoke-rs-redis", "-a", REDIS_PASSWORD, "--no-auth-warning", *args)
        rows = "0"
        for _ in range(30):
            rows = psql(net, "SELECT count(*) FROM forecasts")
            if rows.isdigit() and int(rows) >= N:
                break
            time.sleep(2)
        state = docker("inspect", "-f", "{{.State.Status}}", "smoke-rs-sync").stdout.strip()
        if not (rows.isdigit() and int(rows) >= N) or state != "running":
            print(docker("logs", "smoke-rs-sync").stdout[-3000:])
            raise SystemExit(f"redsql: expected >= {N} rows in forecasts and a running service, got rows={rows!r} state={state}")
        sample = psql(net, "SELECT dp.name FROM forecasts f JOIN data_points dp ON dp.id = f.dp_id LIMIT 1")
        print(f"   OK: {rows} rows in forecasts; running; data point: {sample or 'n/a'}")
        print("redsql image smoke: PASSED")
    finally:
        for c in ("smoke-rs-sync", "smoke-rs-db", "smoke-rs-redis"):
            docker("rm", "-f", c, check=False)
        docker("network", "rm", net, check=False)
        docker("rmi", "-f", tag, check=False)


if __name__ == "__main__":
    sys.exit(main())
