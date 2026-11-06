"""Clean-build smoke for the two simulator images (illuminator-service, pv-sim-service).

Builds each image from its Dockerfile, starts it against a throwaway Redis on a private
Docker network, feeds one weather forecast into its input stream and waits for the
forecast on its output stream. This is the one thing the Compose gate does not cover:
that the rebuilt image (copied venv, new entrypoint, no pip) still turns a forecast
into a simulation result.

Usage: python tests/smoke_simulator_images.py [--keep-images]
"""

import argparse
import json
import math
import os
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
PASSWORD = "smoke-" + uuid.uuid4().hex[:12]
INPUT_STREAM = "smoke.forecasts.nwp.TEST"

SERVICES = {
    "illuminator-service": {
        "module": "illuminator_pv",
        "config_key": "illuminator_sim",
        "output_stream": "smoke.illuminator.forecasts.TEST",
        "mounts": "output",
    },
    "pv-sim-service": {
        "module": "pv_sim",
        "config_key": "pv_sim",
        "output_stream": "smoke.pvsim.forecasts.TEST",
        "mounts": None,
    },
}


def docker(*args, check=True, capture=True, **kwargs):
    return subprocess.run(
        [*DOCKER, *args], check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None, **kwargs,
    )


def forecast():
    """One day of hourly values in the shape the crawler writes (stringified lists)."""
    hours = [f"2026-06-01T{h:02d}:00:00+00:00" for h in range(24)]
    ghi = [max(0.0, 800.0 * math.sin(math.pi * (h - 5) / 14)) if 5 <= h <= 19 else 0.0 for h in range(24)]
    return {
        "station": "TEST",
        "forecast_time": "2026-06-01T00:00:00+00:00",
        "observation_time": json.dumps(hours),
        "air_pressure": json.dumps([101300.0] * 24),
        "air_temperature_2m": json.dumps([15.0 + 0.5 * h / 3 for h in range(24)]),
        "wind_speed_10m": json.dumps([3.0] * 24),
        "global_horizontal_irradiation": json.dumps([round(v, 2) for v in ghi]),
        "latitude": "48.255",
        "longitude": "16.362",
    }


def redis_cli(net, *args, stdin=None):
    return docker("run", "--rm", "-i", "--network", net, REDIS_IMAGE,
                  "redis-cli", "-h", "smoke-redis", "-a", PASSWORD, "--no-auth-warning", *args,
                  input=stdin)


def run_service(name, spec, net, workdir, keep):
    tag = f"smoke/{name}:{uuid.uuid4().hex[:8]}"
    print(f"== {name}: building (clean, --no-cache)")
    build = docker("build", "--no-cache", "-q", "-t", tag, str(ROOT / name), check=False)
    if build.returncode != 0:
        print(build.stdout)
        raise SystemExit(f"{name}: build failed")

    # Neither interpreter may still have a package manager.
    for py in ("python", "/opt/app/.venv/bin/python"):
        r = docker("run", "--rm", "--network", "none", "--entrypoint", py, tag, "-c",
                   "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))",
                   check=False)
        if r.returncode != 0:
            print(r.stdout)
            raise SystemExit(f"{name}: package manager still importable in {py}")
    print(f"   no pip/setuptools/wheel in system or venv interpreter")

    cfg = Path(workdir) / f"{name}.yml"
    out_stream = spec["output_stream"]
    cfg.write_text(
        "version: 1\n"
        f"{spec['config_key']}:\n"
        f'  input_stream: "{INPUT_STREAM}"\n'
        f'  output_stream: "{out_stream}"\n'
        '  location: "TEST"\n'
        "redis:\n"
        '  host: "smoke-redis"\n  port: 6379\n  db: 0\n  password: ${REDIS_PASSWORD}\n'
        "logging:\n  loggers:\n    " + spec["config_key"] + ":\n"
        '      level: "INFO"\n      handlers: ["console"]\n'
    )
    run = ["run", "-d", "--name", f"smoke-{name}", "--network", net,
           "-e", f"REDIS_PASSWORD={PASSWORD}", "-v", f"{cfg}:/app/config.yml:ro"]
    if spec["mounts"] == "output":
        out = Path(workdir) / "output"
        out.mkdir()
        shutil.copy(ROOT / "illuminator-output" / "pv.yaml", out / "pv.yaml")
        os.chmod(out, 0o777)
        run += ["-v", f"{out}:/app/output"]
    docker(*run, tag)
    try:
        time.sleep(8)  # the service blocks on XREAD from "$": it must be waiting before we publish
        state = docker("inspect", "-f", "{{.State.Status}}", f"smoke-{name}").stdout.strip()
        if state != "running":
            print(docker("logs", f"smoke-{name}").stdout[-2000:])
            raise SystemExit(f"{name}: not running before the forecast ({state})")
        payload = forecast()
        args = ["XADD", INPUT_STREAM, "*"] + [x for kv in payload.items() for x in kv]
        redis_cli(net, *args)
        deadline = time.time() + 120
        entries = ""
        while time.time() < deadline:
            entries = redis_cli(net, "XRANGE", out_stream, "-", "+").stdout
            if "p_forecast" in entries:
                break
            time.sleep(3)
        else:
            print(docker("logs", f"smoke-{name}").stdout[-3000:])
            raise SystemExit(f"{name}: no forecast on {out_stream} within 120 s")
        lines = [l.strip() for l in entries.splitlines()]
        fields = dict(zip(lines[1::2], lines[2::2]))
        values = json.loads(fields["p_forecast"])
        stamps = json.loads(fields["ts_forecast"])
        assert len(values) == len(stamps) > 0, "empty or mismatched forecast"
        assert all(isinstance(v, (int, float)) for v in values), "non-numeric forecast values"
        assert max(values) > 0, "a sunny day must produce some power"
        assert fields["location"] == "TEST", fields["location"]
        print(f"   OK: {len(values)} values on {out_stream}, peak {max(values):.2f}")
    finally:
        docker("rm", "-f", f"smoke-{name}", check=False)
        if spec["mounts"] == "output":  # files written by root inside the container
            docker("run", "--rm", "--entrypoint", "rm", "-v", f"{Path(workdir) / 'output'}:/o", tag,
                   "-rf", "/o/pv.yaml", "/o/weather_data.csv", "/o/weather_data_raw.jsonl",
                   "/o/solar_data_illuminator.csv", "/o/illuminator_output.csv", check=False)
        if not keep:
            docker("rmi", "-f", tag, check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-images", action="store_true")
    keep = ap.parse_args().keep_images
    net = f"smoke-sim-{uuid.uuid4().hex[:8]}"
    workdir = tempfile.mkdtemp(prefix="smoke-sim-")
    docker("network", "create", net)
    docker("run", "-d", "--name", "smoke-redis", "--network", net, REDIS_IMAGE,
           "redis-server", "--requirepass", PASSWORD)
    try:
        time.sleep(2)
        for name, spec in SERVICES.items():
            run_service(name, spec, net, workdir, keep)
        print("simulator image smoke: PASSED")
    finally:
        docker("rm", "-f", "smoke-redis", check=False)
        docker("network", "rm", net, check=False)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
