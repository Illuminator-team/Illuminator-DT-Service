"""policy-tool-backend and transformer-profile-init must run the same image.

transformer-profile-init once built ./policy-tool-backend into its own image name,
which was never rebuilt with the backend, so a deploy ran weeks-old baseline code.
Both now name the same image, after the Compose project, so two projects on one
Docker host never share a tag.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class SharedBackendImageTest(unittest.TestCase):
    def test_backend_and_profile_init_share_a_project_named_image(self):
        services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
        backend = services["policy-tool-backend"]
        init = services["transformer-profile-init"]
        self.assertEqual(backend["image"], init["image"])
        self.assertEqual(backend["image"], "${COMPOSE_PROJECT_NAME}-policy-tool-backend")
        self.assertEqual(backend["build"], init["build"])


if __name__ == "__main__":
    unittest.main()
