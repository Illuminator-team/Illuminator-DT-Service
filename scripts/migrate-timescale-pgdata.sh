#!/usr/bin/env bash
# Move an EXISTING Timescale database out of the container's writable layer into
# the timescale-data volume (the compose change in this branch). See
# docs/rdp-deployment-runbook.md, "Moving An Existing Timescale Database".
#
#   migrate-timescale-pgdata.sh prepare  -p PROJECT -f OLD_COMPOSE [-f ...] -b BACKUP_DIR
#   migrate-timescale-pgdata.sh verify   -p PROJECT -f NEW_COMPOSE [-f ...] -b BACKUP_DIR
#   migrate-timescale-pgdata.sh rollback -p PROJECT -f OLD_COMPOSE [-f ...] -b BACKUP_DIR
#
# prepare : with the OLD compose files, validate everything, record the project, image id
#           and per-table row counts, stop Timescale, write an independent tar of PGDATA
#           (with its sha256) into BACKUP_DIR and copy it into the empty volume.
# verify  : with the NEW compose files, compare row counts with the ones from prepare.
# rollback: with the OLD compose files, restore the old layout from BACKUP_DIR. All
#           checks (project, old mount layout, exact image, archive integrity) run
#           BEFORE anything is stopped, recreated or copied.
#
# The services that write to the database must be stopped first. No passwords are
# read or printed; psql uses the container's own POSTGRES_USER over the local socket.
set -euo pipefail

usage() { sed -n 2,19p "$0"; exit 64; }
cmd=${1:-}; shift || true
project=; backup=; files=()
while getopts "p:f:b:" opt; do
  case $opt in p) project=$OPTARG;; f) files+=(-f "$OPTARG");; b) backup=$OPTARG;; *) usage;; esac
done
[ -n "$cmd" ] && [ -n "$project" ] && [ -n "$backup" ] && [ ${#files[@]} -gt 0 ] || usage
DC=(docker compose -p "$project" "${files[@]}")
SERVICE=timescale
DATA=/home/postgres/pgdata
VOLUME=${project}_timescale-data

refuse() { echo "REFUSE: $*" >&2; exit 1; }

# Print "image=<ref>" and one "mount=<target>" line per mount of the service, as rendered by Compose.
rendered() {
  "${DC[@]}" config --format json | python3 -c '
import json, sys
svc = json.load(sys.stdin)["services"]["'$SERVICE'"]
print("image=" + svc.get("image", ""))
for v in svc.get("volumes", []):
    print("mount=" + v.get("target", ""))'
}

# Print "<db> <table> <count>" for every user table, or fail. Never reports a partial list.
counts() {
  docker exec -i "$1" sh -s <<'EOS'
set -eu
dbs=$(psql -U "$POSTGRES_USER" -d postgres -Atc "select datname from pg_database where not datistemplate and datname <> 'postgres' order by 1")
for db in $dbs; do
  tables=$(psql -U "$POSTGRES_USER" -d "$db" -Atc "select schemaname||'.'||relname from pg_stat_user_tables where schemaname not like '\\_timescaledb%' order by 1")
  for t in $tables; do
    n=$(psql -U "$POSTGRES_USER" -d "$db" -Atc "select count(*) from $t")
    case $n in ''|*[!0-9]*) echo "bad count for $db $t" >&2; exit 1;; esac
    echo "$db $t $n"
  done
done
EOS
}

# Count into a temp file and only publish it when the whole enumeration succeeded.
write_counts() { # cid target
  local tmp; tmp=$(mktemp "$backup/.counts.XXXXXX")
  if counts "$1" > "$tmp" && [ -s "$tmp" ]; then mv "$tmp" "$2"; else rm -f "$tmp"; return 1; fi
}

case $cmd in
prepare)
  cid=$("${DC[@]}" ps -q $SERVICE)
  [ -n "$cid" ] || refuse "$SERVICE is not running in project $project"
  if docker inspect -f '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' "$cid" | grep -qx "$DATA"; then
    refuse "$DATA is already a mount; this install is already migrated"
  fi
  rendered | grep -qx "mount=$DATA" && refuse "these Compose files already mount $DATA; pass the OLD Compose files to prepare"
  image=$(docker inspect -f '{{.Image}}' "$cid")
  if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    n=$(docker run --rm --entrypoint sh -v "$VOLUME":/v "$image" -c 'ls -A /v | wc -l')
    [ "$n" = 0 ] || refuse "volume $VOLUME is not empty ($n entries)"
  fi
  mkdir -p "$backup"; chmod 700 "$backup"
  [ -z "$(ls -A "$backup")" ] || refuse "$backup is not empty"
  echo "$project" > "$backup/project"; echo "$image" > "$backup/image-id"
  echo "image: $image"
  write_counts "$cid" "$backup/counts-before.txt" || { rm -f "$backup/project" "$backup/image-id"; refuse "could not count every user table (database not ready, a query failed, or nothing to migrate)"; }
  echo "counted $(wc -l < "$backup/counts-before.txt") tables"
  "${DC[@]}" stop -t 120 $SERVICE
  docker cp "$cid:$DATA" - > "$backup/pgdata.tar"; chmod 600 "$backup/pgdata.tar"
  tar -tf "$backup/pgdata.tar" >/dev/null
  (cd "$backup" && sha256sum pgdata.tar > pgdata.tar.sha256)
  docker volume create "$VOLUME" >/dev/null
  docker run -i --rm --user root --entrypoint tar -v "$VOLUME":"$DATA" "$image" -x -C /home/postgres < "$backup/pgdata.tar"
  echo "OK: backup in $backup/pgdata.tar, data copied into volume $VOLUME."
  echo "Next: switch to the NEW compose files, run 'docker compose up -d $SERVICE', then:"
  echo "  $0 verify -p $project -f NEW_COMPOSE -b $backup"
  ;;
verify)
  [ -s "$backup/counts-before.txt" ] || refuse "no counts-before.txt in $backup"
  cid=$("${DC[@]}" ps -q $SERVICE)
  [ -n "$cid" ] || refuse "$SERVICE is not running"
  docker inspect -f '{{range .Mounts}}{{.Destination}} <- {{.Name}}{{"\n"}}{{end}}' "$cid" | grep -qx "$DATA <- $VOLUME" || refuse "$DATA is not mounted from $VOLUME"
  write_counts "$cid" "$backup/counts-after.txt" || refuse "could not count every user table after the migration"
  diff "$backup/counts-before.txt" "$backup/counts-after.txt" && echo "OK: all $(wc -l < "$backup/counts-after.txt") table counts identical"
  ;;
rollback)
  # ---- validate everything first; nothing is stopped, recreated or copied until all pass ----
  for f in pgdata.tar pgdata.tar.sha256 image-id project; do [ -s "$backup/$f" ] || refuse "missing $backup/$f"; done
  [ "$(cat "$backup/project")" = "$project" ] || refuse "backup was made for project $(cat "$backup/project"), not $project"
  (cd "$backup" && sha256sum -c --status pgdata.tar.sha256) || refuse "backup archive failed its sha256 check"
  tar -tf "$backup/pgdata.tar" >/dev/null 2>&1 || refuse "backup archive is not a readable tar"
  [ "$(tar -tf "$backup/pgdata.tar" | head -1 | cut -d/ -f1)" = pgdata ] || refuse "backup archive does not hold a pgdata directory"
  info=$(rendered)
  printf '%s\n' "$info" | grep -qx "mount=$DATA" && refuse "these Compose files mount $DATA (the NEW layout); pass the OLD Compose files to rollback"
  ref=$(printf '%s\n' "$info" | sed -n 's/^image=//p')
  [ "$(docker image inspect -f '{{.Id}}' "$ref" 2>/dev/null)" = "$(cat "$backup/image-id")" ] || refuse "image $ref is not the backed-up image $(cat "$backup/image-id")"
  # ---- recreate in the old layout, restore, start ----
  "${DC[@]}" up --no-start --force-recreate $SERVICE
  cid=$("${DC[@]}" ps -aq $SERVICE)
  docker cp - "$cid:/home/postgres" < "$backup/pgdata.tar"
  "${DC[@]}" start $SERVICE
  echo "OK: old layout restored from $backup/pgdata.tar"
  ;;
*) usage;;
esac
