#!/bin/sh
# Refuses to start PostgreSQL 17 on an empty volume when a PostgreSQL 14 database exists.
#
# Run by the `timescale-guard` Compose service before `timescale` (and by
# scripts/preflight-timescale.sh). It only looks at the two volumes:
#   $OLD_DIR  the PostgreSQL 14 volume (timescale-data), mounted read-only
#   $NEW_DIR  the PostgreSQL 17 volume (timescale-pg17-data), mounted read-only
# A volume counts as empty when it holds no regular files (see has_files below).
#
#   exit 0  safe: this is a fresh install with no PG14 data, or the PG17 volume carries the
#           completion marker (see below)
#   exit 1  refuse: a PG14 database exists and no verified PG17 copy of it is present
#
# "Verified" means the marker file $NEW_DIR/.illuminator-pg17-migration-complete. A PG17 cluster
# alone (data/PG_VERSION) proves nothing: PostgreSQL 17 initialises before the data is copied,
# so a failed or interrupted copy leaves an initialised but empty or partial cluster.
# scripts/upgrade-timescale-pg17.sh writes the marker only after the row counts and checksums of
# the three data tables are identical, and removes it again at rollback.
#
# TIMESCALE_ALLOW_EMPTY_PG17=yes overrides the refusal for an operator who really wants
# an empty database next to an old one; the old volume is not touched either way.
old=${OLD_DIR:-/old}
new=${NEW_DIR:-/new}
marker="$new/.illuminator-pg17-migration-complete"

# "Empty" means: no regular files. Docker copies the image's empty backup/ and data/
# directories into a new named volume when the container is created, so a fresh volume
# is never literally empty.
has_files() { [ -n "$(find "$1" -type f 2>/dev/null | head -n 1)" ]; }

if [ -f "$new/data/PG_VERSION" ]; then
    version=$(cat "$new/data/PG_VERSION")
    if [ "$version" != "17" ]; then
        echo "timescale-guard: REFUSING: the PostgreSQL 17 volume holds PostgreSQL $version data" >&2
        exit 1
    fi
elif has_files "$new"; then
    echo "timescale-guard: REFUSING: the PostgreSQL 17 volume is not empty but has no data/PG_VERSION" >&2
    echo "  (an interrupted initialisation or foreign content); inspect it before starting the database" >&2
    exit 1
fi

if ! has_files "$old"; then
    if [ -f "$new/data/PG_VERSION" ]; then
        echo "timescale-guard: the PostgreSQL 17 volume holds a v17 cluster and there is no PostgreSQL 14 data"
    else
        echo "timescale-guard: fresh install, no PostgreSQL 14 data found"
    fi
    exit 0
fi

# A PostgreSQL 14 database exists: only a completed migration may start PostgreSQL 17.
if [ -s "$marker" ] && [ -f "$new/data/PG_VERSION" ]; then
    echo "timescale-guard: the PostgreSQL 17 volume carries the migration-complete marker"
    exit 0
fi
if [ "${TIMESCALE_ALLOW_EMPTY_PG17:-}" = "yes" ]; then
    echo "timescale-guard: WARNING: an existing PostgreSQL 14 volume is ignored (TIMESCALE_ALLOW_EMPTY_PG17=yes)" >&2
    exit 0
fi
if [ -f "$new/data/PG_VERSION" ]; then
    echo "timescale-guard: REFUSING: the PostgreSQL 17 volume holds a cluster but no migration-complete marker." >&2
    echo "  A migration that failed or was interrupted leaves an initialised but empty or partial database." >&2
    echo "  Do not start it. Inspect the volume; the PostgreSQL 14 data is untouched." >&2
else
    echo "timescale-guard: REFUSING to start an empty PostgreSQL 17 database next to existing PostgreSQL 14 data." >&2
fi
echo "  Migrate first (docs/rdp-deployment-runbook.md, \"Upgrading The Database To PostgreSQL 17\")," >&2
echo "  or set TIMESCALE_ALLOW_EMPTY_PG17=yes to start empty on purpose." >&2
exit 1
