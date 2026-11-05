"""Negative-path tests for scripts/migrate-timescale-pgdata.sh using a fake `docker`.

The fake records every call, so the tests can assert that nothing is stopped,
recreated or copied when a check fails.
"""
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate-timescale-pgdata.sh"
BASH = shutil.which("bash")
PYTHON = shutil.which("python3") or shutil.which("python")

FAKE_DOCKER = r'''#!__PYTHON__
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
env = os.environ
j = " ".join(args)
def out(text=""):
    sys.stdout.write(text if text.endswith("\n") or not text else text + "\n")
if args[0] == "compose":
    if "config" in args:
        out(env["FAKE_CONFIG_JSON"])
    elif "ps" in args:
        out("cid123")
    sys.exit(0)
if args[0] == "inspect":
    out(env["FAKE_MOUNTS"] if "Mounts" in j else env["FAKE_IMAGE"])
elif args[:2] == ["volume", "inspect"]:
    sys.exit(0 if env.get("FAKE_VOLUME_EXISTS") == "1" else 1)
elif args[:2] == ["image", "inspect"]:
    out(env["FAKE_REF_IMAGE_ID"])
elif args[:2] == ["volume", "create"]:
    pass
elif args[0] == "run":
    if "ls -A" in j:
        out(env.get("FAKE_VOLUME_ENTRIES", "0"))
    else:
        sys.stdin.buffer.read()
elif args[0] == "exec":
    sys.stdin.read()
    if env.get("FAKE_COUNT_FAIL") == "1":
        sys.stderr.write("psql failed\n"); sys.exit(1)
    out(env.get("FAKE_COUNTS", "rdp_db public.t 5\n"))
elif args[0] == "cp":
    if args[1] == "-":
        sys.stdin.buffer.read()
    else:
        sys.stdout.buffer.write(open(env["FAKE_TAR"], "rb").read())
sys.exit(0)
'''

OLD = {"services": {"timescale": {"image": "timescale/timescaledb-ha:pg14-latest",
                                  "volumes": [{"target": "/var/lib/postgresql/data"}]}}}
NEW = {"services": {"timescale": {"image": "timescale/timescaledb-ha:pg14-latest",
                                  "volumes": [{"target": "/home/postgres/pgdata"}]}}}
IMG = "sha256:" + "a" * 64
MUTATING = ("compose -p proj -f c.yml stop", "up --no-start", "start timescale",
            "volume create", "cp -", "tar")


@unittest.skipUnless(BASH and PYTHON, "needs bash and python3")
class MigrationScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(FAKE_DOCKER.replace("__PYTHON__", PYTHON))
        fake.chmod(0o755)
        self.log = self.tmp / "calls.log"
        self.log.write_text("")
        self.tar = self.tmp / "good.tar"
        with tarfile.open(self.tar, "w") as tf:
            data = b"15"
            info = tarfile.TarInfo("pgdata/data/PG_VERSION")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        self.bindir = bindir
        self.backup = self.tmp / "backup"

    def run_script(self, cmd, config=OLD, **env):
        base = {
            **os.environ, "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "FAKE_LOG": str(self.log), "FAKE_TAR": str(self.tar),
            "FAKE_CONFIG_JSON": json.dumps(config), "FAKE_IMAGE": IMG,
            "FAKE_REF_IMAGE_ID": IMG, "FAKE_MOUNTS": "/var/lib/postgresql/data\n",
        }
        base.update(env)
        return subprocess.run(
            [BASH, str(SCRIPT), cmd, "-p", "proj", "-f", "c.yml", "-b", str(self.backup)],
            env=base, capture_output=True, text=True,
        )

    def calls(self):
        return self.log.read_text()

    def assertNothingMutated(self):
        calls = self.calls()
        for needle in ("stop", "up --no-start", " start ", "volume create", "cp -", "--entrypoint tar"):
            self.assertNotIn(needle, calls, f"{needle!r} ran:\n{calls}")

    def make_backup(self, project="proj", image=IMG, tar=None):
        self.backup.mkdir(exist_ok=True)
        data = pathlib.Path(tar or self.tar).read_bytes()
        (self.backup / "pgdata.tar").write_bytes(data)
        (self.backup / "pgdata.tar.sha256").write_text(
            hashlib.sha256(data).hexdigest() + "  pgdata.tar\n")
        (self.backup / "image-id").write_text(image + "\n")
        (self.backup / "project").write_text(project + "\n")

    # ---- rollback: everything is validated before anything is changed ----
    def test_rollback_happy_path(self):
        self.make_backup()
        result = self.run_script("rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("up --no-start --force-recreate", self.calls())

    def test_rollback_wrong_image_changes_nothing(self):
        self.make_backup()
        result = self.run_script("rollback", FAKE_REF_IMAGE_ID="sha256:" + "b" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REFUSE", result.stderr)
        self.assertNothingMutated()

    def test_rollback_new_layout_changes_nothing(self):
        self.make_backup()
        result = self.run_script("rollback", config=NEW)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEW layout", result.stderr)
        self.assertNothingMutated()

    def test_rollback_wrong_project_changes_nothing(self):
        self.make_backup(project="other")
        self.assertNotEqual(self.run_script("rollback").returncode, 0)
        self.assertNothingMutated()

    def test_rollback_corrupt_archive_changes_nothing(self):
        self.make_backup()
        (self.backup / "pgdata.tar").write_bytes(b"not a tar")
        result = self.run_script("rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256", result.stderr)
        self.assertNothingMutated()

    def test_rollback_archive_without_pgdata_changes_nothing(self):
        wrong = self.tmp / "wrong.tar"
        with tarfile.open(wrong, "w") as tf:
            info = tarfile.TarInfo("other/file")
            info.size = 0
            tf.addfile(info, io.BytesIO(b""))
        self.make_backup(tar=wrong)
        result = self.run_script("rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pgdata", result.stderr)
        self.assertNothingMutated()

    # ---- prepare ----
    def test_prepare_happy_path_writes_backup_and_counts(self):
        result = self.run_script("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.backup / "counts-before.txt").read_text(), "rdp_db public.t 5\n")
        self.assertTrue((self.backup / "pgdata.tar.sha256").exists())

    def test_prepare_failed_count_stops_before_stop(self):
        result = self.run_script("prepare", FAKE_COUNT_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNothingMutated()
        self.assertFalse((self.backup / "counts-before.txt").exists())

    def test_prepare_refuses_new_compose_files(self):
        result = self.run_script("prepare", config=NEW)
        self.assertNotEqual(result.returncode, 0)
        self.assertNothingMutated()

    def test_prepare_refuses_already_migrated_container(self):
        result = self.run_script("prepare", FAKE_MOUNTS="/home/postgres/pgdata\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNothingMutated()

    def test_prepare_refuses_nonempty_volume(self):
        result = self.run_script("prepare", FAKE_VOLUME_EXISTS="1", FAKE_VOLUME_ENTRIES="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertNothingMutated()

    # ---- verify ----
    def test_verify_failed_count_is_not_success(self):
        self.backup.mkdir()
        (self.backup / "counts-before.txt").write_text("rdp_db public.t 5\n")
        result = self.run_script(
            "verify", FAKE_COUNT_FAIL="1",
            FAKE_MOUNTS="/home/postgres/pgdata <- proj_timescale-data\n",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("OK", result.stdout)
        self.assertFalse((self.backup / "counts-after.txt").exists())

    def test_verify_detects_a_changed_count(self):
        self.backup.mkdir()
        (self.backup / "counts-before.txt").write_text("rdp_db public.t 5\n")
        result = self.run_script(
            "verify", FAKE_COUNTS="rdp_db public.t 4\n",
            FAKE_MOUNTS="/home/postgres/pgdata <- proj_timescale-data\n",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_verify_identical_counts_pass(self):
        self.backup.mkdir()
        (self.backup / "counts-before.txt").write_text("rdp_db public.t 5\n")
        result = self.run_script(
            "verify", FAKE_MOUNTS="/home/postgres/pgdata <- proj_timescale-data\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
