"""Fail closed when the rendered production Compose contract is unsafe."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


REQUIRED_SERVICES = {
    "policy-tool-frontend",
    "policy-tool-backend",
    "pv-init",
    "pv-api",
    "grid-crosswalk-init",
    "grid-init",
    "grid-api",
    "wind-init",
    "wind-api",
    "heat-init",
    "heat-api",
    "ev-api",
    "consumption-source-cache-init",
    "consumption-runtime-init",
    "consumption-api",
    "congestion-backend",
    "timescale",
    "geo",
    "layer-publisher",
    "reverse-proxy",
}

PINNED_MODEL_SERVICES = {
    "pv-init",
    "pv-api",
    "grid-crosswalk-init",
    "grid-init",
    "grid-api",
    "wind-init",
    "wind-api",
    "heat-init",
    "heat-api",
    "ev-api",
    "consumption-source-cache-init",
    "consumption-runtime-init",
    "consumption-api",
    "congestion-backend",
}

LOOPBACK_PORTS = {
    "timescale": {5432},
    "reverse-proxy": {8080},
    "redis-insight": {5540},
}

IMAGE_DIGEST = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
FIXTURE_MARKERS = ("--fixture", "--allow-fixture", "tests/fixtures")


def _published_port(port: dict[str, Any]) -> int | None:
    value = port.get("published")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_release_compose(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    services = config.get("services")
    if not isinstance(services, dict):
        return ["Rendered Compose configuration has no services object"]

    missing = sorted(REQUIRED_SERVICES - services.keys())
    if missing:
        errors.append(f"Required production services are missing: {', '.join(missing)}")

    for service_name in sorted(PINNED_MODEL_SERVICES & services.keys()):
        image = services[service_name].get("image", "")
        if not isinstance(image, str) or not IMAGE_DIGEST.fullmatch(image):
            errors.append(
                f"{service_name} must use an immutable image@sha256 digest, got {image!r}"
            )

    publisher = services.get("layer-publisher", {})
    publisher_environment = publisher.get("environment", {})
    if publisher_environment.get("GRID_EXPECTED_DATA_MODE") != "real_source":
        errors.append("layer-publisher must require GRID_EXPECTED_DATA_MODE=real_source")

    rendered = json.dumps(config, sort_keys=True).lower()
    for marker in FIXTURE_MARKERS:
        if marker in rendered:
            errors.append(f"Production Compose configuration contains fixture marker {marker!r}")

    for service_name, protected_ports in LOOPBACK_PORTS.items():
        service = services.get(service_name, {})
        for port in service.get("ports", []):
            published = _published_port(port)
            if published not in protected_ports:
                continue
            host_ip = str(port.get("host_ip", ""))
            if host_ip not in {"127.0.0.1", "::1"}:
                errors.append(
                    f"{service_name} diagnostic port {published} must bind to loopback"
                )

    return errors


def main() -> int:
    try:
        config = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Invalid Compose JSON: {exc}", file=sys.stderr)
        return 2

    errors = validate_release_compose(config)
    if errors:
        for error in errors:
            print(f"release-compose error: {error}", file=sys.stderr)
        return 1

    print(
        "Production Compose contract passed: real-source Grid, immutable model "
        "images, no fixtures, and loopback-only diagnostic ports."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
