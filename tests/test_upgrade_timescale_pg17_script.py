"""Order and safety tests for scripts/upgrade-timescale-pg17.sh with a fake `docker`.

The fake keeps a "phase" (which database answers: pg14 or pg17) that flips when Compose is
told to start `timescale` with the old or the new Compose file, logs every call with its
stdin size, and returns canned psql answers. The tests assert the order of the calls.
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
SCRIPT = ROOT / "scripts" / "upgrade-timescale-pg17.sh"
BASH = shutil.which("bash")
PYTHON = shutil.which("python3") or shutil.which("python")

FAKE = r'''#!__PYTHON__
import os, sys
a = sys.argv[1:]
state = os.environ["FAKE_STATE"]
def phase():
    return open(state + "/phase").read().strip()
def setphase(p):
    open(state + "/phase", "w").write(p)
def log(line):
    open(state + "/calls.log", "a").write(line + "\n")
def out(s=""):
    sys.stdout.write(s + ("\n" if s and not s.endswith("\n") else ""))
if a[0] == "compose":
    fs = [a[i + 1] for i, x in enumerate(a) if x == "-f"]
    f = os.path.basename(fs[0])
    rest = a[a.index(fs[-1]) + 1:]
    log("compose[%s] %s ALLOW=%s" % (f, " ".join(rest), os.environ.get("TIMESCALE_ALLOW_EMPTY_PG17", "")))
    if rest[:2] == ["ps", "-q"] or rest[:2] == ["ps", "-aq"]:
        out("cid-" + rest[-1])
    if rest[:2] == ["config", "--images"]:
        out("timescale/timescaledb-ha@sha256:" + "3" * 64)
    if "up" in rest and "timescale" in rest:
        mode = os.environ.get("FAKE_PG14_UP", "") if f == "old.yml" else ""
        if mode == "fail":
            sys.stderr.write("cannot recreate\n"); sys.exit(1)
        if mode != "noop":                      # noop: exits 0 but the old container is not what answers
            setphase("pg17" if f == "new.yml" else "pg14")
    sys.exit(0)
if a[0] == "inspect":
    out("0"); sys.exit(0)
if a[0] == "run":
    log("run %s" % " ".join(a[1:]))
    sys.exit(0 if os.environ.get("FAKE_PG17_CLUSTER") == "1" else 1)
if a[0] == "exec":
    if "printenv" in a:
        out("postgres"); sys.exit(0)
    if "pg_isready" in a:
        sys.exit(0)
    if "pg_dumpall" in a:
        log("pg_dumpall"); out("-- dump"); sys.exit(0)
    if "rm" in a and "-f" in a:
        log("marker-remove[%s]" % phase()); sys.exit(0)
    if "sh" in a and any("migration-complete" in x for x in a):
        log("marker-write stdin=%d" % len(sys.stdin.buffer.read())); sys.exit(0)
    sql = a[a.index("-c") + 1] if "-c" in a else (a[a.index("-qc") + 1] if "-qc" in a else "")
    stdin = ""
    if "-i" in a:
        stdin = str(len(sys.stdin.buffer.read()))
    short = " ".join(sql.split())[:90]
    log("psql[%s] %s%s" % (phase(), short, (" stdin=" + stdin) if stdin else ""))
    if "show server_version_num" in sql:
        out(os.environ.get("FAKE_VERSION", "170011" if phase() == "pg17" else "140007")); sys.exit(0)
    if "COPY replay." in sql and os.environ.get("FAKE_FAIL_REPLAY_ONCE") == "1" and not os.path.exists(state + "/failed"):
        open(state + "/failed", "w").write("x"); sys.stderr.write("staging load failed\n"); sys.exit(1)
    if "TO STDOUT" in sql:
        sys.stdout.write("BINARY-" + phase()); sys.exit(0)
    if "md5(string_agg" in sql:
        t = sql.split(" from ")[1].split()[0]
        n = {"data_points": 31, "raw_bitemporal_double": 1000, "raw_unitemporal_double": 50}[t]
        if phase() in os.environ.get("FAKE_SUMS_FAIL", "").split(","):
            sys.exit(1)                          # psql fails; the script must not treat the empty answer as a report
        if os.environ.get("FAKE_SUMS_GARBAGE") == "1":
            sys.exit(0)
        h = "a" * 32
        if phase() == "pg17" and os.environ.get("FAKE_PG17_EXTRA") == "1":
            n += 7; h = "b" * 32
        if phase() == "pg17" and os.environ.get("FAKE_MISMATCH") == "1":
            h = "c" * 32
        if phase() == "pg14" and os.environ.get("FAKE_PG14_DIFF") == "1":
            h = "d" * 32
        if os.environ.get("FAKE_EMPTY_TABLE") == t:
            n, h = 0, "empty"
        out("%d %s" % (n, h)); sys.exit(0)
    if "last_value from data_points_id_seq" in sql:
        out("31"); sys.exit(0)
    if "not exists" in sql:
        out(os.environ.get("FAKE_MISSING", "0")); sys.exit(0)
    sys.exit(0)
sys.stderr.write("unexpected docker call: %s\n" % " ".join(a)); sys.exit(99)
'''


def sums_file(n=(31, 1000, 50), h="a" * 32):
    return "".join("%s %d %s\n" % (t, c, h) for t, c in zip(("data_points", "raw_bitemporal_double", "raw_unitemporal_double"), n))


@unittest.skipIf(sys.platform == "win32" or not BASH, "needs bash")
class UpgradeScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"; self.state.mkdir()
        (self.state / "calls.log").write_text("")
        bindir = self.tmp / "bin"; bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(FAKE.replace("__PYTHON__", PYTHON)); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.bk = self.tmp / "backup"
        self.env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_STATE=str(self.state),
                        DOCKER="docker", WRITERS="data-sync-service layer-publisher grafana")

    def phase(self, p): (self.state / "phase").write_text(p)

    def run_script(self, cmd, *extra, **env):
        e = dict(self.env, **env)
        return subprocess.run([BASH, str(SCRIPT), cmd, "-p", "proj", "-o", "old.yml", "-n", "new.yml", "-b", str(self.bk), *extra],
                              env=e, capture_output=True, text=True)

    def calls(self): return (self.state / "calls.log").read_text().splitlines()

    def idx(self, needle, start=0, last=False):
        hits = [i for i, c in enumerate(self.calls()) if needle in c and i >= start]
        self.assertTrue(hits, f"no call containing {needle!r}:\n" + "\n".join(self.calls()))
        return hits[-1] if last else hits[0]

    # ---------------------------------------------------------------- cutover
    def test_cutover_takes_baseline_and_export_only_after_the_writers_are_stopped(self):
        self.phase("pg14")
        r = self.run_script("cutover")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stop = self.idx("stop data-sync-service layer-publisher grafana")
        self.assertLess(self.idx("pg_dumpall"), stop)                      # the backup may run while they write
        self.assertGreater(self.idx("md5(string_agg"), stop)               # baseline: after the stop
        self.assertGreater(self.idx("TO STDOUT"), stop)                    # export: after the stop
        self.assertGreater(self.idx("md5(string_agg"), stop)
        self.assertGreater(self.idx("up -d --no-deps timescale"), self.idx("TO STDOUT", last=True))
        up = self.idx("up -d --no-deps timescale")
        self.assertIn("ALLOW=yes", self.calls()[up])                       # guard override only for this call
        self.assertGreater(self.idx("FROM STDIN", start=up), up)

    def test_cutover_starts_the_writers_only_after_the_comparison_and_on_the_new_database(self):
        self.phase("pg14")
        r = self.run_script("cutover")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        start = self.idx("compose[new.yml] up -d --no-deps data-sync-service")
        self.assertGreater(start, self.idx("FROM STDIN", last=True))
        self.assertGreater(start, self.idx("md5(string_agg", start=self.idx("FROM STDIN", last=True)))
        self.assertTrue((self.bk / "cutover-baseline.txt").exists())
        self.assertEqual(oct(self.bk.stat().st_mode & 0o777), "0o700")

    def test_cutover_with_different_checksums_restores_postgres_14_and_never_starts_writers_on_pg17(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_MISMATCH="1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse([c for c in self.calls() if "compose[new.yml] up -d --no-deps data-sync-service" in c])
        restore = self.idx("compose[old.yml] up -d --no-deps --force-recreate timescale")
        self.assertGreater(self.idx("compose[old.yml] up -d --no-deps data-sync-service"), restore)

    def test_cutover_writes_the_completion_marker_only_after_the_comparison_and_before_the_writers(self):
        self.phase("pg14")
        r = self.run_script("cutover")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        check = self.idx("md5(string_agg", start=self.idx("FROM STDIN", last=True))
        marker = self.idx("marker-write")
        self.assertGreater(marker, check)
        self.assertLess(marker, self.idx("compose[new.yml] up -d --no-deps data-sync-service"))
        self.assertNotIn("stdin=0", self.calls()[marker])                  # it carries the verified checksums

    def test_a_failed_cutover_never_writes_the_marker(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_MISMATCH="1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse([c for c in self.calls() if "marker-write" in c])

    def test_cutover_refuses_to_run_on_top_of_a_leftover_pg17_cluster(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_PG17_CLUSTER="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already holds a cluster", r.stderr)
        run = [c for c in self.calls() if c.startswith("run ")]
        self.assertEqual(len(run), 1); self.assertIn(":/new:ro", run[0])    # looked at read-only
        self.assertFalse([c for c in self.calls() if c.startswith("pg_dumpall") or "stop" in c or "FROM STDIN" in c or "marker" in c])

    # A failed checksum query used to leave only the table names in the report; the comparison
    # then passed and the marker was written (review of 5609d4d).
    def no_approval(self):
        calls = self.calls()
        self.assertFalse([c for c in calls if "marker-write" in c], "marker written")
        self.assertFalse([c for c in calls if "compose[new.yml] up -d --no-deps data-sync-service" in c], "writers started on PG17")

    def test_failing_checksum_queries_on_both_databases_never_approve_the_migration(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_SUMS_FAIL="pg14,pg17")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.no_approval()

    def test_a_failing_checksum_query_after_the_load_never_approves_the_migration(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_SUMS_FAIL="pg17")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.no_approval()
        self.assertGreater(self.idx("compose[old.yml] up -d --no-deps data-sync-service"), self.idx("compose[old.yml] up -d --no-deps --force-recreate timescale"))

    def test_an_answer_without_count_and_checksum_never_approves_the_migration(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_SUMS_GARBAGE="1")
        self.assertNotEqual(r.returncode, 0)
        self.no_approval()

    def test_an_empty_table_has_a_defined_checksum_and_the_migration_goes_through(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_EMPTY_TABLE="raw_unitemporal_double")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("raw_unitemporal_double 0 empty", (self.bk / "cutover-baseline.txt").read_text())
        self.assertTrue([c for c in self.calls() if "marker-write" in c])

    # A failed automatic recovery must not start the writers on the partial PG17 database.
    def test_failed_recreation_of_postgres_14_keeps_the_writers_stopped(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_MISMATCH="1", FAKE_PG14_UP="fail")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("STAY STOPPED", r.stderr)
        self.assertFalse([c for c in self.calls() if "up -d --no-deps data-sync-service" in c])
        self.no_approval()

    def test_recreation_that_leaves_postgres_17_answering_keeps_the_writers_stopped(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_MISMATCH="1", FAKE_PG14_UP="noop")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("not PostgreSQL 14", r.stderr)
        self.assertFalse([c for c in self.calls() if "up -d --no-deps data-sync-service" in c])

    def test_successful_recovery_still_starts_the_writers_on_postgres_14(self):
        self.phase("pg14")
        r = self.run_script("cutover", FAKE_MISMATCH="1")
        self.assertEqual(r.returncode, 2)
        self.assertTrue([c for c in self.calls() if "compose[old.yml] up -d --no-deps data-sync-service" in c])

    def test_rollback_with_postgres_17_still_answering_never_starts_the_writers(self):
        # PG17 unchanged since the cutover has the same checksums as the baseline: only the version tells them apart.
        self.prepare_rollback()
        r = self.run_script("rollback", "--replay", FAKE_PG14_UP="noop")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not PostgreSQL 14", r.stderr)
        self.assertFalse([c for c in self.calls() if "up -d --no-deps data-sync-service" in c or "COPY replay." in c])

    def test_cutover_refuses_when_the_running_database_is_not_postgres_14(self):
        self.phase("pg17")
        r = self.run_script("cutover", FAKE_VERSION="170011")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("pg_dumpall") or "stop" in c])

    # ---------------------------------------------------------------- rollback
    def prepare_rollback(self):
        self.phase("pg17")
        self.bk.mkdir(); (self.bk / "cutover-baseline.txt").write_text(sums_file())

    def test_rollback_without_a_choice_changes_nothing(self):
        self.prepare_rollback()
        r = self.run_script("rollback")
        self.assertEqual(r.returncode, 64)
        self.assertEqual(self.calls(), [])

    def test_discard_exports_the_pg17_state_before_starting_postgres_14(self):
        self.prepare_rollback()
        r = self.run_script("rollback", "--discard-post-cutover-writes", FAKE_PG17_EXTRA="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stop = self.idx("stop data-sync-service")
        export = self.idx("TO STDOUT")
        restore = self.idx("compose[old.yml] up -d --no-deps --force-recreate timescale")
        self.assertLess(stop, export); self.assertLess(export, restore)
        self.assertIn("BINARY-pg17", (self.bk / "pg17-at-rollback" / "raw_bitemporal_double.bin").read_text())
        self.assertFalse([c for c in self.calls() if "FROM STDIN" in c])
        self.assertGreater(self.idx("compose[old.yml] up -d --no-deps data-sync-service"), restore)
        self.assertIn("1000 -> 1007", r.stdout)                            # the recovery point is shown

    def test_replay_inserts_the_pg17_rows_into_pg14_and_verifies_them_before_the_writers_start(self):
        self.prepare_rollback()
        r = self.run_script("rollback", "--replay", FAKE_PG17_EXTRA="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        restore = self.idx("compose[old.yml] up -d --no-deps --force-recreate timescale")
        staging = self.idx("COPY replay.", start=restore)
        insert = self.idx("insert into data_points", start=staging)
        check = self.idx("not exists", start=insert)
        start = self.idx("compose[old.yml] up -d --no-deps data-sync-service")
        self.assertLess(restore, staging); self.assertLess(staging, insert); self.assertLess(insert, check); self.assertLess(check, start)
        self.assertEqual(len([c for c in self.calls() if "COPY replay." in c]), 3)

    def test_replay_with_rows_missing_afterwards_keeps_the_writers_stopped(self):
        self.prepare_rollback()
        r = self.run_script("rollback", "--replay", FAKE_PG17_EXTRA="1", FAKE_MISSING="3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("3 replayed rows are missing", r.stderr)
        self.assertFalse([c for c in self.calls() if "compose[old.yml] up -d --no-deps data-sync-service" in c])

    def test_rollback_stops_when_postgres_14_does_not_match_the_cutover_baseline(self):
        self.prepare_rollback()
        r = self.run_script("rollback", "--replay", FAKE_PG14_DIFF="1")
        self.assertEqual(r.returncode, 1)
        self.assertFalse([c for c in self.calls() if "COPY replay." in c or "data-sync-service" in c and "up" in c])

    def test_rollback_removes_the_marker_after_the_export_and_before_postgres_14_starts(self):
        self.prepare_rollback()
        r = self.run_script("rollback", "--discard-post-cutover-writes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        remove = self.idx("marker-remove[pg17]")
        self.assertGreater(remove, self.idx("TO STDOUT", last=True))
        self.assertLess(remove, self.idx("compose[old.yml] up -d --no-deps --force-recreate timescale"))
        self.assertTrue((self.bk / "pg17-at-rollback" / "EXPORT_COMPLETE").exists())

    def export_bytes(self):
        d = self.bk / "pg17-at-rollback"
        return {f.name: f.read_bytes() for f in sorted(d.iterdir()) if f.suffix == ".bin"}

    def test_a_replay_retry_on_postgres_14_keeps_the_pg17_export_byte_for_byte(self):
        self.prepare_rollback()
        first = self.run_script("rollback", "--replay", FAKE_PG17_EXTRA="1", FAKE_FAIL_REPLAY_ONCE="1")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        self.assertEqual((self.state / "phase").read_text().strip(), "pg14")  # failed after the switch
        original = self.export_bytes()
        self.assertEqual(set(original), {"data_points.bin", "raw_bitemporal_double.bin", "raw_unitemporal_double.bin"})
        self.assertTrue(all(v == b"BINARY-pg17" for v in original.values()))
        sums = (self.bk / "pg17-at-rollback" / "sums.txt").read_bytes()
        before = len(self.calls())
        second = self.run_script("rollback", "--replay", FAKE_PG17_EXTRA="1", FAKE_FAIL_REPLAY_ONCE="1")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.export_bytes(), original)                       # byte for byte
        self.assertEqual((self.bk / "pg17-at-rollback" / "sums.txt").read_bytes(), sums)
        self.assertFalse([c for c in self.calls()[before:] if "TO STDOUT" in c])  # nothing was exported again
        self.assertIn("reusing the completed PostgreSQL 17 export", second.stdout)
        self.assertGreater(len([c for c in self.calls() if "insert into data_points" in c]), 0)

    def test_a_rollback_on_postgres_14_without_a_completed_pg17_export_refuses_and_exports_nothing(self):
        self.prepare_rollback(); self.phase("pg14")
        r = self.run_script("rollback", "--replay")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no completed PostgreSQL 17 export", r.stderr)
        self.assertFalse([c for c in self.calls() if "TO STDOUT" in c or "FROM STDIN" in c or "up -d" in c])
        self.assertFalse((self.bk / "pg17-at-rollback").exists())

    def test_an_interrupted_pg17_export_is_never_promoted_to_the_recovery_export(self):
        self.prepare_rollback(); self.phase("pg14")
        part = self.bk / "pg17-at-rollback.partial"; part.mkdir(); (part / "data_points.bin").write_bytes(b"half")
        r = self.run_script("rollback", "--discard-post-cutover-writes")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.bk / "pg17-at-rollback").exists())

    def test_a_completed_export_is_not_replaced_when_pg17_has_changed_since(self):
        self.prepare_rollback()
        done = self.bk / "pg17-at-rollback"; done.mkdir()
        (done / "data_points.bin").write_bytes(b"original"); (done / "EXPORT_COMPLETE").write_text("")
        (done / "sums.txt").write_text(sums_file())
        r = self.run_script("rollback", "--discard-post-cutover-writes", FAKE_PG17_EXTRA="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("has changed since", r.stderr)
        self.assertEqual((done / "data_points.bin").read_bytes(), b"original")
        self.assertFalse([c for c in self.calls() if "TO STDOUT" in c or "up -d" in c])

    def test_rollback_requires_the_backup_directory_of_a_cutover(self):
        self.phase("pg17"); self.bk.mkdir()
        r = self.run_script("rollback", "--replay")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse([c for c in self.calls() if "stop" in c])


if __name__ == "__main__":
    unittest.main()
