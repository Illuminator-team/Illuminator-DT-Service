#!/usr/bin/env bash
# Deployment preflight for the PostgreSQL 14 -> 17 move. Run it before every
# `docker compose up -d --build`:
#
#   scripts/preflight-timescale.sh -p <project> -f docker-compose.yml [-f docker-compose.ports.yml]
#
# The `timescale-guard` Compose service already refuses an empty PostgreSQL 17 volume next
# to a PostgreSQL 14 volume. What it cannot see is an install from before the
# `timescale-data` mount fix, where the database lives in the Timescale container's
# writable layer (the volume is empty). This script catches that case: an existing
# `timescale` container that does not run the PostgreSQL 17 image is refused until the
# PostgreSQL 17 volume carries the migration-complete marker written by
# scripts/upgrade-timescale-pg17.sh (data/PG_VERSION = 17 alone is not proof: a failed copy
# leaves an initialised, empty cluster).
#
# Exit 0: fresh install, already on PostgreSQL 17, or a verified PG17 copy exists.
# Exit 1: refuse; nothing was changed. No credentials are read or printed.
# TIMESCALE_ALLOW_EMPTY_PG17=yes overrides the refusal.
set -euo pipefail
DOCKER=${DOCKER:-docker}
project=""; files=()
while getopts "p:f:" opt; do
  case $opt in
    p) project=$OPTARG ;;
    f) files+=(-f "$OPTARG") ;;
    *) echo "usage: $0 -p <project> -f <compose-file> [-f <compose-file>]" >&2; exit 64 ;;
  esac
done
[ -n "$project" ] && [ ${#files[@]} -gt 0 ] || { echo "usage: $0 -p <project> -f <compose-file> [-f <compose-file>]" >&2; exit 64; }

target=$($DOCKER compose -p "$project" "${files[@]}" config --images | grep 'timescaledb-ha' | sort -u | head -n 1)
[ -n "$target" ] || { echo "preflight: cannot find the timescaledb-ha image in the Compose configuration" >&2; exit 1; }

ids=$($DOCKER ps -a -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=timescale")
if [ -z "$ids" ]; then
  echo "preflight: no existing timescale container (fresh install); the compose guard checks the volumes"
  exit 0
fi

for id in $ids; do
  image=$($DOCKER inspect -f '{{.Config.Image}}' "$id")
  if [ "$image" = "$target" ]; then
    echo "preflight: the existing timescale container already runs the PostgreSQL 17 image"
    continue
  fi
  version=$($DOCKER run --rm --entrypoint sh -v "${project}_timescale-pg17-data:/new:ro" "$target" \
              -c 'v=$(cat /new/data/PG_VERSION 2>/dev/null); if [ -s /new/.illuminator-pg17-migration-complete ]; then echo "$v"; fi' 2>/dev/null || true)
  if [ "$version" = "17" ]; then
    echo "preflight: existing timescale container ($image) and a verified PostgreSQL 17 volume: ok"
    continue
  fi
  if [ "${TIMESCALE_ALLOW_EMPTY_PG17:-}" = "yes" ]; then
    echo "preflight: WARNING: existing timescale container ($image) ignored (TIMESCALE_ALLOW_EMPTY_PG17=yes)" >&2
    continue
  fi
  {
    echo "preflight: REFUSING to deploy."
    echo "  An existing timescale container runs $image, and the PostgreSQL 17 volume has no migration-complete marker."
    echo "  Deploying now would start an empty PostgreSQL 17 database and leave the history behind."
    echo "  Migrate first (docs/rdp-deployment-runbook.md, \"Upgrading The Database To PostgreSQL 17\"; installs from"
    echo "  before the mount fix also need \"Moving An Existing Timescale Database\"), or set TIMESCALE_ALLOW_EMPTY_PG17=yes."
  } >&2
  exit 1
done
exit 0
