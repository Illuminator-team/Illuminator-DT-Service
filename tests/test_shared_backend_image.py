"""policy-tool-backend and transformer-profile-init must run the same image.

transformer-profile-init once built ./policy-tool-backend into its own image name,
which was never rebuilt with the backend, so a deploy ran weeks-old baseline code.
Both now name the same image, after the Compose project, so two projects on one
Docker host never share a tag.

Reads the compose text directly: the CI test step installs no YAML parser.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED_IMAGE = "${COMPOSE_PROJECT_NAME}-policy-tool-backend"


def service_block(compose: str, service: str) -> str:
    start = re.search(rf"^  {re.escape(service)}:\n", compose, re.MULTILINE)
    if start is None:
        raise AssertionError(f"service {service} is missing")
    rest = compose[start.end():]
    end = re.search(r"^  \S", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def service_key(block: str, key: str) -> str:
    match = re.search(rf"^\s+{key}:\s*(\S+)\s*$", block, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{key} is missing")
    return match.group(1)


class SharedBackendImageTest(unittest.TestCase):
    def test_backend_and_profile_init_share_a_project_named_image(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        backend = service_block(compose, "policy-tool-backend")
        init = service_block(compose, "transformer-profile-init")
        self.assertEqual(service_key(backend, "image"), SHARED_IMAGE)
        self.assertEqual(service_key(init, "image"), SHARED_IMAGE)
        self.assertEqual(service_key(backend, "build"), service_key(init, "build"))


if __name__ == "__main__":
    unittest.main()
