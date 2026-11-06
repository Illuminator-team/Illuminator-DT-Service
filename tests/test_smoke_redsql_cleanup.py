"""The redsql smoke must only remove what its own invocation created (no real Docker needed)."""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_redsql_image as smoke  # noqa: E402


class FakeDocker:
    def __init__(self, fail_run_of=None):
        self.calls = []
        self.fail_run_of = fail_run_of

    def __call__(self, *args, check=True, **kw):
        self.calls.append(args)
        if args[0] == "run" and "--name" in args and args[args.index("--name") + 1].startswith(self.fail_run_of or "\0"):
            return subprocess.CompletedProcess(args, 125, stdout="name already in use")
        return subprocess.CompletedProcess(args, 0, stdout="")

    def removed(self):
        return [a[-1] for a in self.calls if a[0] == "rm"]


class SmokeCleanupTests(unittest.TestCase):
    def setUp(self):
        self._docker = smoke.docker
        smoke.created.update(containers=[], networks=[], images=[])

    def tearDown(self):
        smoke.docker = self._docker
        smoke.created.update(containers=[], networks=[], images=[])

    def test_name_collision_on_first_container_removes_nothing(self):
        fake = smoke.docker = FakeDocker(fail_run_of=smoke.REDIS)
        with self.assertRaises(SystemExit):
            smoke.main()
        self.assertEqual(fake.removed(), [])  # the colliding container is not ours

    def test_failure_on_second_container_removes_only_the_first_with_its_volume(self):
        fake = smoke.docker = FakeDocker(fail_run_of=smoke.DB)
        with self.assertRaises(SystemExit):
            smoke.main()
        self.assertEqual(fake.removed(), [smoke.REDIS])
        self.assertTrue(all(a[:2] == ("rm", "-fv") for a in fake.calls if a[0] == "rm"))

    def test_names_are_unique_per_invocation(self):
        for name in (smoke.DB, smoke.REDIS, smoke.SYNC):
            self.assertIn(smoke.RUN, name)


if __name__ == "__main__":
    unittest.main()
