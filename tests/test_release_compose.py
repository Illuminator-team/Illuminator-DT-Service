import copy
import unittest

from scripts.check_release_compose import (
    LOOPBACK_PORTS,
    PINNED_MODEL_SERVICES,
    REQUIRED_SERVICES,
    validate_release_compose,
)


PINNED_IMAGE = "ghcr.io/example/model@sha256:" + ("a" * 64)


def valid_release_config() -> dict:
    services = {service: {} for service in REQUIRED_SERVICES}
    for service in PINNED_MODEL_SERVICES:
        services[service]["image"] = PINNED_IMAGE
    services["layer-publisher"]["environment"] = {
        "GRID_EXPECTED_DATA_MODE": "real_source"
    }
    for service, ports in LOOPBACK_PORTS.items():
        services.setdefault(service, {})["ports"] = [
            {"published": port, "target": port, "host_ip": "127.0.0.1"}
            for port in sorted(ports)
        ]
    return {"services": services}


class ReleaseComposeContractTests(unittest.TestCase):
    def test_valid_release_contract_passes(self):
        self.assertEqual(validate_release_compose(valid_release_config()), [])

    def test_fixture_command_fails(self):
        config = valid_release_config()
        config["services"]["grid-init"]["command"] = ["initialize", "--fixture"]
        errors = validate_release_compose(config)
        self.assertTrue(any("fixture marker" in error for error in errors))

    def test_mutable_model_image_fails(self):
        config = valid_release_config()
        config["services"]["pv-api"]["image"] = "ghcr.io/example/model:latest"
        errors = validate_release_compose(config)
        self.assertTrue(any("pv-api" in error for error in errors))

    def test_public_diagnostic_port_fails(self):
        config = copy.deepcopy(valid_release_config())
        config["services"]["timescale"]["ports"][0].pop("host_ip")
        errors = validate_release_compose(config)
        self.assertTrue(any("port 5432" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
