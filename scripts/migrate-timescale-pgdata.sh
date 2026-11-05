#!/usr/bin/env bash
# Move an EXISTING Timescale database out of the container's writable layer into
# the timescale-data volume (the compose change in this branch). See
# docs/rdp-deployment-runbook.md, "Moving an existing Timescale database".
#
#   migrate-timescale-pgdata.sh prepare  -p PROJECT -f OLD_COMPOSE [-f ...] -b BACKUP_DIR
#   migrate-timescale-pgdata.sh rollback -p PROJECT -f OLD_COMPOSE [-f ...] -b BACKUP_DIR
#
# prepare : with the OLD compose files, record the image, count rows, stop Timescale,
#           write an independent tar of PGDATA into BACKUP_DIR and copy it into the
#           (empty) volume. It refuses an already-migrated install and a non-empty volume.
#           Afterwards: switch to the NEW compose files and run
#           `docker compose up -d timescale`, then compare the counts.
# rollback: with the OLD compose files, recreate the old layout from BACKUP_DIR.
#
# The services that write to the database must be stopped first. No passwords are
# read or printed; psql uses the container's own POSTGRES_USER over the local socket.
set -euo pipefail

cmd=${1:-}; shift || true
project=; backup=; files=()
while getopts "p:f:b:" opt; do
  case $opt in p) project=$OPTARG;; f) files+=(-f "$OPTARG");; b) backup=$OPTARG;; *) exit 64;; esac
done
[ -n "$cmd" ] && [ -n "$project" ] && [ -n "$backup" ] && [ ${#files[@]} -gt 0 ] || { sed -n 2,19p "$0"; exit 64; }
DC=(docker compose -p "$project" "${files[@]}")
SERVICE=timescale
DATA=/home/postgres/pgdata
VOLUME=${project}_timescale-data

counts() { # exact row count of every user table in every non-template database
  local cid=$1
  docker exec -i "$cid" sh -s <<'EOS'
for db in $(psql -U "$POSTGRES_USER" -d postgres -Atc "select datname from pg_database where not datistemplate and datname <> 'postgres' order by 1"); do
  for t in $(psql -U "$POSTGRES_USER" -d "$db" -Atc "select schemaname||'.'||relname from pg_stat_user_tables where schemaname not like '\_timescaledb%' order by 1"); do
    echo "$db $t $(psql -U "$POSTGRES_USER" -d "$db" -Atc "select count(*) from $t")"
  done
done
EOS
}

case $cmd in
prepare)
  cid=$("${DC[@]}" ps -q $SERVICE)
  [ -n "$cid" ] || { echo "REFUSE: $SERVICE is not running in project $project"; exit 1; }
  if docker inspect -f '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' "$cid" | grep -qx "$DATA"; then
    echo "REFUSE: $DATA is already a mount; this install is already migrated"; exit 1
  fi
  if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    n=$(docker run --rm --entrypoint sh -v "$VOLUME":/v "$(docker inspect -f '{{.Image}}' "$cid")" -c 'ls -A /v | wc -l')
    [ "$n" = 0 ] || { echo "REFUSE: volume $VOLUME is not empty ($n entries)"; exit 1; }
  fi
  mkdir -p "$backup"; chmod 700 "$backup"
  [ -z "$(ls -A "$backup")" ] || { echo "REFUSE: $backup is not empty"; exit 1; }
  image=$(docker inspect -f '{{.Image}}' "$cid"); echo "$image" > "$backup/image-id"
  echo "image: $image"
  counts "$cid" > "$backup/counts-before.txt"
  [ -s "$backup/counts-before.txt" ] || { echo "REFUSE: no user tables were counted (database not ready, or nothing to migrate)"; exit 1; }
  echo "counted $(wc -l < "$backup/counts-before.txt") tables"
  "${DC[@]}" stop -t 120 $SERVICE
  docker cp "$cid:$DATA" - > "$backup/pgdata.tar"; chmod 600 "$backup/pgdata.tar"
  tar -tf "$backup/pgdata.tar" >/dev/null
  docker volume create "$VOLUME" >/dev/null
  docker run -i --rm --user root --entrypoint tar -v "$VOLUME":"$DATA" "$image" -x -C /home/postgres < "$backup/pgdata.tar"
  echo "OK: backup in $backup/pgdata.tar, data copied into volume $VOLUME."
  echo "Next: switch to the NEW compose files, run 'docker compose up -d $SERVICE', then:"
  echo "  $0 verify -p $project -f NEW_COMPOSE -b $backup"
  ;;
verify)
  cid=$("${DC[@]}" ps -q $SERVICE)
  [ -n "$cid" ] || { echo "FAIL: $SERVICE is not running"; exit 1; }
  docker inspect -f '{{range .Mounts}}{{.Destination}} <- {{.Name}}{{"\n"}}{{end}}' "$cid" | grep -q "^$DATA <- $VOLUME$" || { echo "FAIL: $DATA is not mounted from $VOLUME"; exit 1; }
  counts "$cid" > "$backup/counts-after.txt"
  diff "$backup/counts-before.txt" "$backup/counts-after.txt" && echo "OK: all $(wc -l < "$backup/counts-after.txt") table counts identical"
  ;;
rollback)
  [ -s "$backup/pgdata.tar" ] || { echo "REFUSE: no backup tar in $backup"; exit 1; }
  # Recreate the service in the OLD layout (fresh writable layer), put the saved
  # PGDATA back into it, then start it. The old image id is checked first.
  "${DC[@]}" up --no-start --force-recreate $SERVICE
  cid=$("${DC[@]}" ps -aq $SERVICE)
  [ "$(docker inspect -f '{{.Image}}' "$cid")" = "$(cat "$backup/image-id")" ] || { echo "REFUSE: image differs from the backed-up one"; exit 1; }
  docker cp - "$cid:/home/postgres" < "$backup/pgdata.tar"
  "${DC[@]}" start $SERVICE
  echo "OK: old layout restored from $backup/pgdata.tar"
  ;;
*) sed -n 2,19p "$0"; exit 64;;
esac
