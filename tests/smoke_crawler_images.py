"""Clean-build smoke for the two data-crawler images (weather-data-service, frequency-data-service).

Builds each image with --no-cache, checks that pip is gone and the venv has the tested
dependency versions, starts the crawler against a throwaway Redis and requires that it
writes a record to its output stream.

* weather-data-service is checked against the live Geosphere API.
* frequency-data-service is pointed (source parameter `base_url`) at a small local HTTP
  server that returns a controlled successful response, so the publish path is tested
  without depending on api.energy-charts.info (which currently answers 404 to the
  crawler's request for the previous image too).

Every container, network and temporary file belongs to this invocation (unique names);
only what this run created is removed.

Usage: DOCKER="sudo -n docker" python tests/smoke_crawler_images.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = os.environ.get("DOCKER", "docker").split()
REDIS_IMAGE = "redis:7.2.17-alpine"
FAKE_API_IMAGE = "python:3.12-slim"
PASSWORD = "smoke-" + uuid.uuid4().hex[:12]
RUN = uuid.uuid4().hex[:8]
REDIS_ERROR = re.compile(r"^\(?(error\)?|ERR|WRONGTYPE|NOAUTH|WRONGPASS|NOPERM|LOADING|BUSY)\b", re.I)
BAD_LOG = ("ModuleNotFoundError", "ImportError", "NOAUTH", "WRONGPASS", "ConnectionRefused", "Temporary failure in name resolution")
EXPECTED_VERSIONS = "{'certifi':'2026.10.23','urllib3':'2.8.0','filelock':'4.2.9','msgpack':'1.2.4'}"

FAKE_API = (
    "import json,http.server\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        b=json.dumps({'unix_seconds':[1780272000],'data':[50.012]}).encode()\n"
    "        self.send_response(200); self.send_header('Content-Type','application/json')\n"
    "        self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)\n"
    "    def log_message(self,*a): pass\n"
    "http.server.HTTPServer(('0.0.0.0',8080),H).serve_forever()\n"
)

SERVICES = {
    "weather-data-service": {"stream": "geosphere.forecasts.nwp.WIEN-HOHE_WARTE", "fake_api": False,
                             "fields": ("observation_time", "air_temperature_2m")},
    "frequency-data-service": {"stream": "energy-charts.frequency", "fake_api": True,
                               "fields": ("measurement_time", "frequency")},
}

created = {"containers": [], "networks": [], "images": [], "dirs": []}


def docker(*args, check=True, **kw):
    return subprocess.run([*DOCKER, *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)


def start(name, *args):
    """docker run -d; remember the container only if this invocation created it."""
    r = docker("run", "-d", "--name", name, *args, check=False)
    if r.returncode != 0:
        print(r.stdout)
        raise SystemExit(f"could not start {name}")
    created["containers"].append(name)


def redis_cli(net, redis_name, *args):
    r = docker("run", "--rm", "--network", net, REDIS_IMAGE, "redis-cli", "-h", redis_name,
               "-a", PASSWORD, "--no-auth-warning", *args, check=False)
    out = r.stdout.strip()
    if r.returncode != 0 or REDIS_ERROR.match(out):
        raise SystemExit(f"redis-cli {' '.join(args[:2])} failed: {out[:200]}")
    return out


def stream_length(net, redis_name, stream):
    out = redis_cli(net, redis_name, "XLEN", stream)
    if not re.fullmatch(r"\d+", out):
        raise SystemExit(f"XLEN {stream} did not return an integer: {out[:200]!r}")
    return int(out)


def run(name, spec, net, redis_name, workdir):
    tag = f"smoke/{name}:{RUN}"
    print(f"== {name}: building (clean, --no-cache)")
    b = docker("build", "--no-cache", "-q", "-t", tag, str(ROOT / name), check=False)
    if b.returncode != 0:
        print(b.stdout)
        raise SystemExit(f"{name}: build failed (this includes `pip check` on the venv)")
    created["images"].append(tag)
    r = docker("run", "--rm", "--network", "none", "--entrypoint", "/usr/local/bin/python3", tag, "-c",
               "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))", check=False)
    if r.returncode != 0:
        raise SystemExit(f"{name}: package manager still importable in the system interpreter")
    v = docker("run", "--rm", "--network", "none", "--entrypoint", "/app/.venv/bin/python", tag, "-c",
               "import importlib.metadata as m; v={p:m.version(p) for p in ('certifi','urllib3','filelock','msgpack')};"
               f"print(v); assert v=={EXPECTED_VERSIONS}", check=False)
    if v.returncode != 0:
        raise SystemExit(f"{name}: unexpected dependency versions: {v.stdout[-300:]}")
    print("   no pip in the system interpreter;", v.stdout.strip().splitlines()[0])

    text = (ROOT / name / "config.yml").read_text().replace("host: redis", f"host: {redis_name}")
    if spec["fake_api"]:
        api = f"smoke-fakeapi-{RUN}"
        start(api, "--network", net, "-d", FAKE_API_IMAGE, "python", "-c", FAKE_API)
        marker = "<< : *freq_default_source_parameters"
        assert text.count(marker) == 1
        text = text.replace(marker, marker + f"\n      base_url: \"http://{api}:8080\"")
    cfg = Path(workdir) / f"{name}.yml"
    cfg.write_text(text)
    cname = f"smoke-{name}-{RUN}"
    start(cname, "--network", net, "-e", f"REDIS_PASSWORD={PASSWORD}", "-v", f"{cfg}:/etc/data_crawler/config.yml:ro", tag)

    deadline = time.time() + 120
    while time.time() < deadline and stream_length(net, redis_name, spec["stream"]) == 0:
        time.sleep(4)
    logs = docker("logs", cname).stdout
    bad = [m for m in BAD_LOG if m in logs]
    if bad:
        print(logs[-2500:])
        raise SystemExit(f"{name}: errors in the log: {bad}")
    if docker("inspect", "-f", "{{.State.Status}}", cname).stdout.strip() != "running":
        print(logs[-2500:])
        raise SystemExit(f"{name}: container is not running")
    n = stream_length(net, redis_name, spec["stream"])
    if n < 1:
        print(logs[-2500:])
        raise SystemExit(f"{name}: no record on {spec['stream']} within 120 s")
    entry = redis_cli(net, redis_name, "XRANGE", spec["stream"], "-", "+", "COUNT", "1")
    missing = [f for f in spec["fields"] if f not in entry.split("\n")]
    if missing:
        raise SystemExit(f"{name}: record on {spec['stream']} lacks fields {missing}: {entry[:300]!r}")
    print(f"   OK: {n} record(s) on {spec['stream']} with fields {', '.join(spec['fields'])}")


def cleanup():
    for c in reversed(created["containers"]):
        docker("rm", "-f", c, check=False)
    for n in created["networks"]:
        docker("network", "rm", n, check=False)
    for i in created["images"]:
        docker("rmi", "-f", i, check=False)
    for d in created["dirs"]:
        shutil.rmtree(d, ignore_errors=True)


def main():
    net = f"smoke-crawl-{RUN}"
    redis_name = f"smoke-redis-{RUN}"
    try:
        workdir = tempfile.mkdtemp(prefix="smoke-crawl-")
        created["dirs"].append(workdir)
        r = docker("network", "create", net, check=False)
        if r.returncode != 0:
            raise SystemExit(f"could not create network {net}: {r.stdout}")
        created["networks"].append(net)
        start(redis_name, "--network", net, REDIS_IMAGE, "redis-server", "--requirepass", PASSWORD)
        time.sleep(2)
        for name, spec in SERVICES.items():
            run(name, spec, net, redis_name, workdir)
        print("crawler image smoke: PASSED")
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
