"""Clean-build smoke for the two data-crawler images (weather-data-service, frequency-data-service).

Builds each image with --no-cache, checks that pip is gone and the venv is consistent,
starts the crawler against a throwaway Redis and waits for it to write a record to its
output stream.

The weather crawler is checked against the live Geosphere API and must write a record.
The frequency crawler depends on api.energy-charts.info, which currently answers 404 to
the crawler's request (this is the same with the previous image), so for it the check is
that it starts, imports everything and talks to Redis without an import or Redis error;
a record is reported but not required.

Usage: DOCKER="sudo -n docker" python tests/smoke_crawler_images.py
"""

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
PASSWORD = "smoke-" + uuid.uuid4().hex[:12]

SERVICES = {
    "weather-data-service": {"stream": "geosphere.forecasts.nwp.WIEN-HOHE_WARTE", "record_required": True},
    "frequency-data-service": {"stream": "energy-charts.frequency", "record_required": False},
}
BAD_LOG = ("ModuleNotFoundError", "ImportError", "NOAUTH", "WRONGPASS", "ConnectionRefused", "Temporary failure in name resolution")


def docker(*args, check=True, **kw):
    return subprocess.run([*DOCKER, *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)


def redis_cli(net, *args):
    return docker("run", "--rm", "--network", net, REDIS_IMAGE, "redis-cli", "-h", "smoke-redis",
                  "-a", PASSWORD, "--no-auth-warning", *args).stdout


def run(name, spec, net, workdir):
    tag = f"smoke/{name}:{uuid.uuid4().hex[:8]}"
    print(f"== {name}: building (clean, --no-cache)")
    b = docker("build", "--no-cache", "-q", "-t", tag, str(ROOT / name), check=False)
    if b.returncode != 0:
        print(b.stdout)
        raise SystemExit(f"{name}: build failed (this includes `pip check` on the venv)")
    r = docker("run", "--rm", "--network", "none", "--entrypoint", "/usr/local/bin/python3", tag, "-c",
               "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))", check=False)
    if r.returncode != 0:
        raise SystemExit(f"{name}: package manager still importable in the system interpreter")
    v = docker("run", "--rm", "--network", "none", "--entrypoint", "/app/.venv/bin/python", tag, "-c",
               "import importlib.metadata as m; v={p:m.version(p) for p in ('certifi','urllib3','filelock','msgpack')}; print(v);"
               "assert v=={'certifi':'2026.10.23','urllib3':'2.8.0','filelock':'4.2.9','msgpack':'1.2.4'}", check=False)
    print("   no pip in the system interpreter;", v.stdout.strip().splitlines()[0] if v.returncode == 0 else v.stdout)
    if v.returncode != 0:
        raise SystemExit(f"{name}: unexpected dependency versions")

    cfg = Path(workdir) / f"{name}.yml"
    cfg.write_text((ROOT / name / "config.yml").read_text().replace("host: redis", "host: smoke-redis"))
    target = "/etc/data_crawler/config.yml"
    docker("run", "-d", "--name", f"smoke-{name}", "--network", net, "-e", f"REDIS_PASSWORD={PASSWORD}",
           "-v", f"{cfg}:{target}:ro", tag)
    try:
        deadline = time.time() + 100
        got = False
        while time.time() < deadline:
            if redis_cli(net, "XLEN", spec["stream"]).strip() not in ("0", ""):
                got = True
                break
            time.sleep(4)
        logs = docker("logs", f"smoke-{name}").stdout
        bad = [m for m in BAD_LOG if m in logs]
        if bad:
            print(logs[-2500:])
            raise SystemExit(f"{name}: errors in the log: {bad}")
        state = docker("inspect", "-f", "{{.State.Status}}", f"smoke-{name}").stdout.strip()
        if state != "running":
            print(logs[-2500:])
            raise SystemExit(f"{name}: container is {state}")
        if spec["record_required"] and not got:
            print(logs[-2500:])
            raise SystemExit(f"{name}: no record on {spec['stream']} within 100 s")
        print(f"   OK: running, no errors; record on {spec['stream']}: {'yes' if got else 'no (upstream API)'}")
    finally:
        docker("rm", "-f", f"smoke-{name}", check=False)
        docker("rmi", "-f", tag, check=False)


def main():
    net = f"smoke-crawl-{uuid.uuid4().hex[:8]}"
    workdir = tempfile.mkdtemp(prefix="smoke-crawl-")
    docker("network", "create", net)
    docker("run", "-d", "--name", "smoke-redis", "--network", net, REDIS_IMAGE, "redis-server", "--requirepass", PASSWORD)
    try:
        time.sleep(2)
        for name, spec in SERVICES.items():
            run(name, spec, net, workdir)
        print("crawler image smoke: PASSED")
    finally:
        docker("rm", "-f", "smoke-redis", check=False)
        docker("network", "rm", net, check=False)


if __name__ == "__main__":
    sys.exit(main())
