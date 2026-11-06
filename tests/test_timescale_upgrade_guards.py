"""Tests for the PostgreSQL 17 upgrade guards.

* scripts/timescale-upgrade-guard.sh runs against real temporary directories.
* scripts/preflight-timescale.sh runs against a fake `docker` that logs every call.

Both must refuse an existing PostgreSQL 14 install and allow a fresh install and a
migrated one.
"""
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "timescale-upgrade-guard.sh"
PREFLIGHT = ROOT / "scripts" / "preflight-timescale.sh"
SH = shutil.which("sh")
BASH = shutil.which("bash")
PYTHON = shutil.which("python3") or shutil.which("python")
TARGET = "timescale/timescaledb-ha@sha256:" + "3" * 64

POSIX = sys.platform != "win32" and SH and BASH


def run_guard(old, new, **env):
    e = {k: v for k, v in os.environ.items() if k != "TIMESCALE_ALLOW_EMPTY_PG17"}
    e.update(OLD_DIR=str(old), NEW_DIR=str(new), **env)
    return subprocess.run([SH, str(GUARD)], env=e, capture_output=True, text=True)


MARKER = ".illuminator-pg17-migration-complete"


def make_cluster(volume, version):
    (volume / "data").mkdir(parents=True)
    (volume / "data" / "PG_VERSION").write_text(version + "\n")


def mark_migrated(volume):
    """What scripts/upgrade-timescale-pg17.sh writes after the counts and checksums matched."""
    (volume / MARKER).write_text("data_points 31 aaaa\n")


@unittest.skipUnless(POSIX, "needs a POSIX shell")
class GuardScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.old, self.new = self.tmp / "old", self.tmp / "new"
        self.old.mkdir(); self.new.mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_fresh_install_is_allowed(self):
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fresh install", r.stdout)

    def skeleton(self):
        """What Docker puts into a new volume: the image's empty backup/ and data/ directories."""
        for d in ("backup", "data"):
            (self.new / d).mkdir()

    def test_fresh_install_with_the_docker_created_directory_skeleton_is_allowed(self):
        self.skeleton()
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fresh install", r.stdout)

    def test_existing_pg14_install_with_a_skeleton_only_pg17_volume_is_refused_as_unmigrated(self):
        self.skeleton()
        make_cluster(self.old, "14")
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Migrate first", r.stderr)
        self.assertNotIn("not empty", r.stderr)

    def test_existing_pg14_install_with_empty_pg17_volume_is_refused(self):
        make_cluster(self.old, "14")
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSING", r.stderr)
        self.assertIn("Migrate first", r.stderr)

    def test_migrated_install_is_allowed(self):
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        mark_migrated(self.new)
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("migration-complete marker", r.stdout)

    def test_initialised_pg17_cluster_without_the_marker_is_refused_next_to_pg14_data(self):
        # What a failed or interrupted copy leaves behind: PG17 initialises before the data is copied.
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no migration-complete marker", r.stderr)

    def test_failed_copy_followed_by_a_normal_deploy_does_not_start_the_partial_database(self):
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        (self.new / "data" / "base").write_text("half the rows")
        self.assertEqual(run_guard(self.old, self.new).returncode, 1)

    def test_a_marker_without_a_pg17_cluster_does_not_count(self):
        make_cluster(self.old, "14")
        mark_migrated(self.new)
        self.assertEqual(run_guard(self.old, self.new).returncode, 1)

    def test_an_empty_marker_does_not_count(self):
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        (self.new / MARKER).write_text("")
        self.assertEqual(run_guard(self.old, self.new).returncode, 1)

    def test_removing_the_marker_at_rollback_makes_the_guard_refuse_again(self):
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        mark_migrated(self.new)
        self.assertEqual(run_guard(self.old, self.new).returncode, 0)
        (self.new / MARKER).unlink()
        self.assertEqual(run_guard(self.old, self.new).returncode, 1)

    def test_running_pg17_install_without_an_old_volume_is_allowed(self):
        make_cluster(self.new, "17")
        self.assertEqual(run_guard(self.old, self.new).returncode, 0)

    def test_pg17_volume_with_another_version_is_refused(self):
        make_cluster(self.new, "16")
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 1)
        self.assertIn("PostgreSQL 16", r.stderr)

    def test_non_empty_pg17_volume_without_pg_version_is_refused(self):
        (self.new / "data").mkdir()
        (self.new / "data" / "base").write_text("half initialised")
        r = run_guard(self.old, self.new)
        self.assertEqual(r.returncode, 1)
        self.assertIn("PG_VERSION", r.stderr)

    def test_explicit_override_allows_an_empty_start_next_to_an_old_database(self):
        make_cluster(self.old, "14")
        r = run_guard(self.old, self.new, TIMESCALE_ALLOW_EMPTY_PG17="yes")
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARNING", r.stderr)
        self.assertTrue((self.old / "data" / "PG_VERSION").exists())  # never touched

    def test_explicit_override_also_covers_an_unmarked_pg17_cluster(self):
        make_cluster(self.old, "14")
        make_cluster(self.new, "17")
        self.assertEqual(run_guard(self.old, self.new, TIMESCALE_ALLOW_EMPTY_PG17="yes").returncode, 0)


FAKE_DOCKER = r'''#!__PYTHON__
import os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
e = os.environ
if args[0] == "compose":
    print(e["FAKE_TARGET"]); sys.exit(0)
if args[0] == "ps":
    print(e.get("FAKE_IDS", "")); sys.exit(0)
if args[0] == "inspect":
    print(e["FAKE_IMAGE"]); sys.exit(0)
if args[0] == "run":
    # Run the shell snippet the script passes against a temporary directory standing in for the volume.
    import subprocess
    cmd = args[args.index("-c") + 1].replace("/new", e["FAKE_NEW_DIR"])
    sys.exit(subprocess.run(["sh", "-c", cmd]).returncode)
sys.stderr.write("unexpected docker call: %s\n" % " ".join(args)); sys.exit(99)
'''


@unittest.skipUnless(POSIX, "needs bash and a POSIX shell")
class PreflightScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(FAKE_DOCKER.replace("__PYTHON__", PYTHON))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.log = self.tmp / "calls.log"
        self.log.write_text("")
        self.newdir = self.tmp / "pg17-volume"
        self.newdir.mkdir()
        self.base_env = {k: v for k, v in os.environ.items() if k != "TIMESCALE_ALLOW_EMPTY_PG17"}
        self.base_env.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(self.log),
                             FAKE_TARGET=TARGET, FAKE_NEW_DIR=str(self.newdir))

    def run_script(self, **env):
        e = dict(self.base_env, **env)
        return subprocess.run([BASH, str(PREFLIGHT), "-p", "proj", "-f", "docker-compose.yml"],
                              env=e, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text().splitlines()

    def pg17_volume(self, version=None, marker=False):
        if version:
            make_cluster(self.newdir, version)
        if marker:
            mark_migrated(self.newdir)

    def test_fresh_install_without_a_timescale_container_is_allowed(self):
        r = self.run_script(FAKE_IDS="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fresh install", r.stdout)

    def test_existing_pg14_container_in_the_writable_layer_layout_is_refused(self):
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSING", r.stderr)
        self.assertIn("pg14-latest", r.stderr)

    def test_nothing_is_stopped_created_or_removed_when_refusing(self):
        self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest")
        verbs = {c.split()[0] for c in self.calls()}
        self.assertTrue(verbs <= {"compose", "ps", "inspect", "run"}, verbs)
        self.assertFalse([c for c in self.calls() if c.startswith("compose") and " up" in c])
        self.assertFalse([c for c in self.calls() if " rm " in f" {c} " or c.startswith("stop") or "volume" in c.split()[:1]])
        self.assertTrue([c for c in self.calls() if c.startswith("run") and ":/new:ro" in c])  # volume mounted read-only

    def test_migrated_install_with_a_verified_pg17_volume_is_allowed(self):
        self.pg17_volume("17", marker=True)
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verified PostgreSQL 17 volume", r.stdout)

    def test_a_pg17_volume_that_is_not_version_17_does_not_count_as_verified(self):
        self.pg17_volume("16", marker=True)
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest")
        self.assertEqual(r.returncode, 1)

    def test_an_initialised_pg17_cluster_without_the_marker_is_not_a_completed_migration(self):
        self.pg17_volume("17")  # PG_VERSION=17 only: what a failed copy leaves behind
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("migration-complete marker", r.stderr)

    def test_container_already_running_the_pg17_image_is_allowed(self):
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE=TARGET)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already runs the PostgreSQL 17 image", r.stdout)

    def test_explicit_override_is_allowed_with_a_warning(self):
        r = self.run_script(FAKE_IDS="abc123", FAKE_IMAGE="timescale/timescaledb-ha:pg14-latest",
                            TIMESCALE_ALLOW_EMPTY_PG17="yes")
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARNING", r.stderr)

    def test_missing_arguments_are_a_usage_error(self):
        r = subprocess.run([BASH, str(PREFLIGHT)], env=self.base_env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 64)


if __name__ == "__main__":
    unittest.main()
