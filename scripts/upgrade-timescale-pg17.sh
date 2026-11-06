#!/usr/bin/env bash
# PostgreSQL 14 / TimescaleDB 2.10 -> PostgreSQL 17 / TimescaleDB 2.31 for the Timescale service.
#
#   upgrade-timescale-pg17.sh cutover  -p PROJECT -o OLD_COMPOSE -n NEW_COMPOSE -b BACKUP_DIR [-x EXTRA_COMPOSE]
#   upgrade-timescale-pg17.sh rollback -p PROJECT -o OLD_COMPOSE -n NEW_COMPOSE -b BACKUP_DIR [-x EXTRA_COMPOSE] \
#                                      (--replay | --discard-post-cutover-writes)
#
# OLD_COMPOSE is the Compose file of the PostgreSQL 14 deployment, NEW_COMPOSE the one with
# the PostgreSQL 17 image and the timescale-pg17-data volume. EXTRA_COMPOSE is an optional
# override file (for example docker-compose.ports.yml). No password is read, passed or printed:
# the admin user name comes from the running container's environment and psql runs inside it.
#
# cutover
#   1. pg_dumpall of the running PG14 database into BACKUP_DIR (mode 700).
#   2. Stops the writers (WRITERS, default: data-sync-service layer-publisher grafana).
#   3. ONLY THEN records count(*) and an md5 checksum of the three data tables and exports them,
#      so the baseline and the export come from the same snapshot (checked again after the export).
#   4. Starts PostgreSQL 17 on the new volume (the compose guard is overridden for this one call
#      only), runs db-scheme, creates the postgis extension, loads the tables.
#   5. Requires identical counts and checksums before the writers are started again, and only then
#      writes the completion marker into the PG17 volume (the compose guard and the deploy
#      preflight accept PG17 next to PG14 data only with that marker). On any failure the PG14
#      deployment is restored (nothing has been written to PG17 yet) and no marker exists.
#   A failed attempt leaves an initialised but unmarked PG17 volume. A second cutover refuses to
#   run on top of it: inspect and remove it by hand first (the script never deletes a volume).
#   The old volume is never modified.
#
# rollback  (after the writers have written to PG17, those rows exist only there)
#   You must choose what happens to the rows written since the cutover:
#     --replay                         export them from PG17 first, restore PG14, then insert them
#                                      into PG14 (ON CONFLICT DO NOTHING on the primary keys) and
#                                      verify that every one is present.
#     --discard-post-cutover-writes    restore PG14 as it was at the cutover; the rows written since
#                                      then stay only in the PG17 export and the PG17 volume.
#   Either way the PG17 volume is kept and the PG17 tables are exported to BACKUP_DIR/pg17-at-rollback
#   before PG14 is started, and the writers stay stopped until the chosen step is done.
#   The completion marker is removed from the PG17 volume at rollback.
#   The PG17 export is written once: into a partial directory that only becomes pg17-at-rollback
#   (with an EXPORT_COMPLETE file) after every table is exported. Only a database that answers
#   as PostgreSQL 17 is exported. A retry after a failure (for example a failed replay on PG14)
#   reuses the completed export, or refuses with an instruction; it never exports PG14 data over it.
set -uo pipefail

DOCKER=${DOCKER:-docker}
WRITERS=${WRITERS:-"data-sync-service layer-publisher grafana"}
TABLES="data_points raw_bitemporal_double raw_unitemporal_double"
DB=rdp_db
MARKER=/home/postgres/pgdata/.illuminator-pg17-migration-complete

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 64; }
die() { echo "upgrade-timescale-pg17: $*" >&2; exit 1; }

cmd=${1:-}; [ -n "$cmd" ] || usage; shift
PROJECT=""; OLDC=""; NEWC=""; BK=""; EXTRA=""; MODE=""
while [ $# -gt 0 ]; do
  case $1 in
    -p) PROJECT=$2; shift 2 ;;
    -o) OLDC=$2; shift 2 ;;
    -n) NEWC=$2; shift 2 ;;
    -b) BK=$2; shift 2 ;;
    -x) EXTRA=$2; shift 2 ;;
    --replay) MODE=replay; shift ;;
    --discard-post-cutover-writes) MODE=discard; shift ;;
    *) usage ;;
  esac
done
[ -n "$PROJECT" ] && [ -n "$OLDC" ] && [ -n "$NEWC" ] && [ -n "$BK" ] || usage
case $cmd in
  cutover) ;;
  rollback) [ -n "$MODE" ] || { echo "rollback needs --replay or --discard-post-cutover-writes (the rows written to PostgreSQL 17 since the cutover would otherwise be lost silently)" >&2; exit 64; } ;;
  *) usage ;;
esac

dc() { local f=$1; shift; if [ -n "$EXTRA" ]; then $DOCKER compose -p "$PROJECT" -f "$f" -f "$EXTRA" "$@"; else $DOCKER compose -p "$PROJECT" -f "$f" "$@"; fi; }
cid() { dc "$NEWC" ps -q timescale; }
pq() { $DOCKER exec "$(cid)" psql -U "$ADMIN" -d "$DB" -tAF'|' -c "$1"; }
ready() { local i; for i in $(seq 1 60); do $DOCKER exec "$(cid)" pg_isready -U "$ADMIN" >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
# One line per table: "<table> <row count> <md5>" ("empty" stands in for the md5 of an empty table).
# Any failed query, or an answer that is not exactly that shape, fails the whole report.
sums() {
  local t r
  for t in $TABLES; do
    r=$(pq "select count(*)||' '||coalesce(md5(string_agg(x::text,'|' order by x::text)),'empty') from $t x") || return 1
    [[ $r =~ ^[0-9]+\ ([0-9a-f]{32}|empty)$ ]] || { echo "upgrade-timescale-pg17: no usable count/checksum for $t: '$r'" >&2; return 1; }
    echo "$t $r"
  done
}
active_major() { pq 'show server_version_num' | head -n 1 | cut -c1-2; }
copy_out_sql() { if [ "$1" = data_points ]; then echo "COPY $1 TO STDOUT (FORMAT binary)"; else echo "COPY (SELECT * FROM $1 ORDER BY 1,2,3) TO STDOUT (FORMAT binary)"; fi; }
export_tables() { # export_tables DIR  (a plain COPY of a hypertable copies nothing, hence the SELECT)
  local t; mkdir -p "$1"; for t in $TABLES; do $DOCKER exec "$(cid)" psql -U "$ADMIN" -d "$DB" -qc "$(copy_out_sql "$t")" > "$1/$t.bin" || return 1; done
}
pg17_volume_has_cluster() { # read-only look at the PG17 volume, with the PG17 image from the new Compose file
  local image; image=$(dc "$NEWC" config --images | grep timescaledb-ha | sort -u | head -n 1)
  [ -n "$image" ] || die "cannot find the timescaledb-ha image in $NEWC"
  $DOCKER run --rm --entrypoint sh -v "${PROJECT}_timescale-pg17-data:/new:ro" "$image" -c 'test -f /new/data/PG_VERSION'
}
stop_writers() { dc "$NEWC" stop $WRITERS; }
start_writers() { dc "$1" up -d --no-deps $WRITERS; }

umask 077; mkdir -p "$BK"; chmod 700 "$BK"
ADMIN=$($DOCKER exec "$(cid)" printenv POSTGRES_USER) && [ -n "$ADMIN" ] || die "cannot find the running timescale container or its admin user"

restore_old() { # PG14 deployment back, nothing written to PG17 yet
  echo "!!!! restoring the PostgreSQL 14 deployment: $1"
  stop_writers >/dev/null 2>&1 || true
  # The writers only start again when PostgreSQL 14 was recreated, is the database that answers, and is ready.
  if ! dc "$OLDC" up -d --no-deps --force-recreate timescale; then
    echo "!!!! could not recreate PostgreSQL 14; the writers STAY STOPPED. The old volume is untouched; recover by hand with: docker compose -p $PROJECT -f $OLDC up -d timescale" >&2; exit 3
  fi
  if ! ready; then
    echo "!!!! the PostgreSQL 14 database did not become ready; the writers STAY STOPPED" >&2; exit 3
  fi
  if [ "$(active_major)" != 14 ]; then
    echo "!!!! the database that answers is not PostgreSQL 14 (the PostgreSQL 17 container is still running); the writers STAY STOPPED" >&2; exit 3
  fi
  start_writers "$OLDC"
  exit 2
}

if [ "$cmd" = cutover ]; then
  echo "=== 0. pre-checks"
  [ "$(active_major)" = 14 ] || die "the running database is not PostgreSQL 14"
  if pg17_volume_has_cluster; then
    die "the PostgreSQL 17 volume (${PROJECT}_timescale-pg17-data) already holds a cluster, for example from a failed earlier attempt, and the load would run into it. Inspect it; if it is only a leftover, remove that volume yourself and run the cutover again. Nothing was changed."
  fi
  echo "=== 1. backup"
  $DOCKER exec "$(cid)" pg_dumpall -U "$ADMIN" > "$BK/pg14-dumpall-before-pg17-cutover.sql" || die "pg_dumpall failed"
  echo "=== 2. stop the writers"
  stop_writers || die "could not stop the writers"
  echo "=== 3. baseline and export from the same snapshot (writers are stopped)"
  sums > "$BK/cutover-baseline.txt" || restore_old "the baseline counts and checksums could not be computed"
  export_tables "$BK/pg14-at-cutover" || die "export failed"
  seq=$(pq 'select last_value from data_points_id_seq') && [[ $seq =~ ^[0-9]+$ ]] || restore_old "cannot read data_points_id_seq"
  echo "$seq" > "$BK/data_points_id_seq.txt"
  sums > "$BK/cutover-baseline-after-export.txt" || restore_old "the checksums after the export could not be computed"
  diff -q "$BK/cutover-baseline.txt" "$BK/cutover-baseline-after-export.txt" >/dev/null || restore_old "the data changed while it was being exported"
  cat "$BK/cutover-baseline.txt"
  echo "=== 4. start PostgreSQL 17 on the new volume"
  TIMESCALE_ALLOW_EMPTY_PG17=yes dc "$NEWC" up -d --no-deps timescale || restore_old "PostgreSQL 17 did not start"
  ready || restore_old "PostgreSQL 17 did not become ready"
  dc "$NEWC" up --no-deps db-scheme
  [ "$($DOCKER inspect -f '{{.State.ExitCode}}' "$(dc "$NEWC" ps -aq db-scheme)")" = 0 ] || restore_old "db-scheme failed"
  pq "create extension if not exists postgis" >/dev/null || restore_old "postgis extension"
  echo "=== 5. load, then require identical counts and checksums before the writers start"
  for t in $TABLES; do
    $DOCKER exec -i "$(cid)" psql -U "$ADMIN" -d "$DB" -v ON_ERROR_STOP=1 -qc "COPY $t FROM STDIN (FORMAT binary)" < "$BK/pg14-at-cutover/$t.bin" || restore_old "load of $t failed"
  done
  pq "select setval('data_points_id_seq', $(cat "$BK/data_points_id_seq.txt"), true)" >/dev/null || restore_old "sequence"
  sums > "$BK/pg17-after-load.txt" || restore_old "the counts and checksums of the loaded PostgreSQL 17 tables could not be computed"
  diff "$BK/cutover-baseline.txt" "$BK/pg17-after-load.txt" || restore_old "counts or checksums differ after the load"
  echo "identical: $(tr '\n' ';' < "$BK/pg17-after-load.txt")"
  $DOCKER exec -i "$(cid)" sh -c "cat > $MARKER" < "$BK/pg17-after-load.txt" || restore_old "could not write the migration-complete marker"
  echo "=== 6. start the writers"
  start_writers "$NEWC" || die "could not start the writers (PostgreSQL 17 holds the verified data)"
  echo "=== CUTOVER DONE; baseline in $BK/cutover-baseline.txt"
  exit 0
fi

# ---------------------------------------------------------------- rollback
[ -f "$BK/cutover-baseline.txt" ] || die "no $BK/cutover-baseline.txt: this is not the backup directory of a cutover"
echo "=== 1. stop the writers (the PostgreSQL 17 state must stop changing)"
stop_writers || die "could not stop the writers"
echo "=== 2. keep the PostgreSQL 17 state: export it before PostgreSQL 14 is started"
RB="$BK/pg17-at-rollback"
active=$(active_major) || die "cannot ask the running database for its version; nothing was changed, the writers are stopped"
if [ -f "$RB/EXPORT_COMPLETE" ]; then
  # A completed export exists (this is a retry). Never replace it.
  if [ "$active" = 17 ]; then
    sums > "$BK/pg17-now.txt" || die "cannot checksum the running PostgreSQL 17 tables; the writers are stopped"
    cmp -s "$BK/pg17-now.txt" "$RB/sums.txt" || die "a completed PostgreSQL 17 export exists in $RB, but PostgreSQL 17 has changed since. Move that export aside (keep it) and run the rollback again; nothing was changed, the writers are stopped"
  fi
  echo "reusing the completed PostgreSQL 17 export from the earlier attempt ($RB)"
else
  [ "$active" = 17 ] || die "the running database is PostgreSQL $active and there is no completed PostgreSQL 17 export in $RB. Start the PostgreSQL 17 deployment ($NEWC) again, then repeat the rollback; PostgreSQL $active data is never exported as the PostgreSQL 17 state. Nothing was changed, the writers are stopped"
  rm -rf "$RB.partial"
  export_tables "$RB.partial" || die "export of the PostgreSQL 17 tables failed; nothing was changed, the writers are still stopped"
  sums > "$RB.partial/sums.txt" || die "checksums of the PostgreSQL 17 tables failed; the writers are still stopped"
  touch "$RB.partial/EXPORT_COMPLETE"
  [ ! -e "$RB" ] || die "$RB exists without a completed export; move it aside and repeat the rollback (the new export is in $RB.partial); the writers are stopped"
  mv "$RB.partial" "$RB" || die "cannot move the export into place; it is in $RB.partial; the writers are stopped"
fi
if [ "$active" = 17 ]; then # PG14 becomes the live database again: the PG17 copy no longer counts as migrated
  $DOCKER exec "$(cid)" rm -f "$MARKER" || die "cannot remove the migration-complete marker; the writers are stopped"
fi
echo "rows at the cutover vs now (the difference is the recovery point):"
paste -d' ' "$BK/cutover-baseline.txt" "$RB/sums.txt" | awk '{print "  "$1": "$2" -> "$5}'
echo "=== 3. restore PostgreSQL 14 (old volume, untouched since the cutover)"
dc "$OLDC" up -d --no-deps --force-recreate timescale || die "could not start PostgreSQL 14; the PostgreSQL 17 volume and export are intact, the writers are stopped"
ready || die "PostgreSQL 14 did not become ready; the writers stay stopped"
[ "$(active_major)" = 14 ] || die "the database that answers is not PostgreSQL 14 (is the PostgreSQL 17 container still running?); the writers stay stopped"
sums > "$RB/pg14-after-restore.txt" || die "cannot checksum PostgreSQL 14; the writers stay stopped"
diff -q "$BK/cutover-baseline.txt" "$RB/pg14-after-restore.txt" >/dev/null || die "PostgreSQL 14 does not match the cutover baseline; writers stay stopped"
echo "PostgreSQL 14 matches the cutover baseline"
if [ "$MODE" = replay ]; then
  echo "=== 4. replay the rows written to PostgreSQL 17 since the cutover"
  pq "drop schema if exists replay cascade; create schema replay;
      create table replay.data_points (like public.data_points including defaults);
      create table replay.raw_bitemporal_double (like public.raw_bitemporal_double);
      create table replay.raw_unitemporal_double (like public.raw_unitemporal_double)" >/dev/null || die "cannot create the staging schema"
  for t in $TABLES; do
    $DOCKER exec -i "$(cid)" psql -U "$ADMIN" -d "$DB" -v ON_ERROR_STOP=1 -qc "COPY replay.$t FROM STDIN (FORMAT binary)" < "$RB/$t.bin" || die "staging load of $t failed; the writers stay stopped"
  done
  pq "begin;
      insert into data_points select * from replay.data_points on conflict (id) do nothing;
      insert into raw_bitemporal_double select * from replay.raw_bitemporal_double on conflict do nothing;
      insert into raw_unitemporal_double select * from replay.raw_unitemporal_double on conflict do nothing;
      select setval('data_points_id_seq', greatest((select last_value from data_points_id_seq), (select coalesce(max(id),1) from data_points)), true);
      commit" >/dev/null || die "replay failed; the writers stay stopped"
  missing=$(pq "select (select count(*) from replay.data_points r where not exists (select 1 from data_points t where t.id=r.id))
       + (select count(*) from replay.raw_bitemporal_double r where not exists (select 1 from raw_bitemporal_double t where t.dp_id=r.dp_id and t.valid_time=r.valid_time and t.transaction_time=r.transaction_time))
       + (select count(*) from replay.raw_unitemporal_double r where not exists (select 1 from raw_unitemporal_double t where t.dp_id=r.dp_id and t.valid_time=r.valid_time))")
  [ "$missing" = 0 ] || die "$missing replayed rows are missing from PostgreSQL 14; the writers stay stopped"
  pq "drop schema replay cascade" >/dev/null
  sums > "$RB/pg14-after-replay.txt" || die "cannot checksum PostgreSQL 14 after the replay; the writers stay stopped"
  echo "replayed; every PostgreSQL 17 row is present. PostgreSQL 14 now: $(tr '\n' ';' < "$RB/pg14-after-replay.txt")"
else
  echo "=== 4. --discard-post-cutover-writes: the rows written since the cutover are kept only in $RB and the PostgreSQL 17 volume"
fi
echo "=== 5. start the writers on PostgreSQL 14"
start_writers "$OLDC" || die "could not start the writers"
echo "=== ROLLBACK DONE ($MODE); PostgreSQL 17 volume and export kept in $RB"
