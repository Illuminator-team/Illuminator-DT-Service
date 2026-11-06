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
#   5. Requires identical counts and checksums before the writers are started again. On any
#      failure the PG14 deployment is restored (nothing has been written to PG17 yet).
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
set -uo pipefail

DOCKER=${DOCKER:-docker}
WRITERS=${WRITERS:-"data-sync-service layer-publisher grafana"}
TABLES="data_points raw_bitemporal_double raw_unitemporal_double"
DB=rdp_db

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
sums() { local t; for t in $TABLES; do echo "$t $(pq "select count(*)||' '||md5(string_agg(x::text,'|' order by x::text)) from $t x")"; done; }
copy_out_sql() { if [ "$1" = data_points ]; then echo "COPY $1 TO STDOUT (FORMAT binary)"; else echo "COPY (SELECT * FROM $1 ORDER BY 1,2,3) TO STDOUT (FORMAT binary)"; fi; }
export_tables() { # export_tables DIR  (a plain COPY of a hypertable copies nothing, hence the SELECT)
  local t; mkdir -p "$1"; for t in $TABLES; do $DOCKER exec "$(cid)" psql -U "$ADMIN" -d "$DB" -qc "$(copy_out_sql "$t")" > "$1/$t.bin" || return 1; done
}
stop_writers() { dc "$NEWC" stop $WRITERS; }
start_writers() { dc "$1" up -d --no-deps $WRITERS; }

umask 077; mkdir -p "$BK"; chmod 700 "$BK"
ADMIN=$($DOCKER exec "$(cid)" printenv POSTGRES_USER) && [ -n "$ADMIN" ] || die "cannot find the running timescale container or its admin user"

restore_old() { # PG14 deployment back, nothing written to PG17 yet
  echo "!!!! restoring the PostgreSQL 14 deployment: $1"
  dc "$OLDC" up -d --no-deps --force-recreate timescale
  ready || echo "the PostgreSQL 14 database did not become ready" >&2
  start_writers "$OLDC"
  exit 2
}

if [ "$cmd" = cutover ]; then
  echo "=== 0. pre-checks"
  [ "$(pq 'show server_version_num' | head -n 1 | cut -c1-2)" = 14 ] || die "the running database is not PostgreSQL 14"
  echo "=== 1. backup"
  $DOCKER exec "$(cid)" pg_dumpall -U "$ADMIN" > "$BK/pg14-dumpall-before-pg17-cutover.sql" || die "pg_dumpall failed"
  echo "=== 2. stop the writers"
  stop_writers || die "could not stop the writers"
  echo "=== 3. baseline and export from the same snapshot (writers are stopped)"
  sums > "$BK/cutover-baseline.txt" || die "baseline failed"
  export_tables "$BK/pg14-at-cutover" || die "export failed"
  echo "$(pq 'select last_value from data_points_id_seq')" > "$BK/data_points_id_seq.txt"
  sums > "$BK/cutover-baseline-after-export.txt"
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
  sums > "$BK/pg17-after-load.txt"
  diff "$BK/cutover-baseline.txt" "$BK/pg17-after-load.txt" || restore_old "counts or checksums differ after the load"
  echo "identical: $(tr '\n' ';' < "$BK/pg17-after-load.txt")"
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
export_tables "$RB" || die "export of the PostgreSQL 17 tables failed; nothing was changed, the writers are still stopped"
sums > "$RB/sums.txt"
echo "rows at the cutover vs now (the difference is the recovery point):"
paste -d' ' "$BK/cutover-baseline.txt" "$RB/sums.txt" | awk '{print "  "$1": "$2" -> "$5}'
echo "=== 3. restore PostgreSQL 14 (old volume, untouched since the cutover)"
dc "$OLDC" up -d --no-deps --force-recreate timescale || die "could not start PostgreSQL 14; the PostgreSQL 17 volume and export are intact, the writers are stopped"
ready || die "PostgreSQL 14 did not become ready; the writers stay stopped"
sums > "$RB/pg14-after-restore.txt"
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
  sums > "$RB/pg14-after-replay.txt"
  echo "replayed; every PostgreSQL 17 row is present. PostgreSQL 14 now: $(tr '\n' ';' < "$RB/pg14-after-replay.txt")"
else
  echo "=== 4. --discard-post-cutover-writes: the rows written since the cutover are kept only in $RB and the PostgreSQL 17 volume"
fi
echo "=== 5. start the writers on PostgreSQL 14"
start_writers "$OLDC" || die "could not start the writers"
echo "=== ROLLBACK DONE ($MODE); PostgreSQL 17 volume and export kept in $RB"
