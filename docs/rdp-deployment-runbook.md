# RDP Deployment Runbook

## Scope

This runbook promotes a reviewed `dev` commit to the TU Delft RDP deployment at
`reformers01.ewi.tudelft.nl`. Deployment is always a separate owner-approved
action. Merging a feature PR into `dev` does not deploy or merge anything into
`main`.

The current milestone publishes the Consumption, PV, Grid, Wind, Heat, and EV
layers and exposes provisional Consumption and PV transformer-profile
aggregation. It does not yet combine Consumption and PV calendars, include EV
in transformer aggregation, compare profiles with transformer capacity, or
classify congestion. User-facing transformer output must remain labelled as
provisional aggregation rather than a congestion result.

## Release Gate

Before approving `dev` to `main`, require all of the following for the exact
`dev` commit:

- the `Integration and release gate` workflow is green;
- `docker compose -f docker-compose.yml config --format json` passes
  `scripts/check_release_compose.py`;
- every private model image is retrievable by immutable digest with the
  deployment's read-only GHCR credential;
- sufficient free disk is available for the existing volumes plus PV and Grid
  initialization; do not run Docker pruning as part of deployment;
- the current database and GeoServer configuration are backed up;
- certificate paths and all non-placeholder `.env` secrets are present;
- the previous deployed Git commit and image inventory are recorded; and
- the owner has explicitly approved both the merge to `main` and deployment.

The CI lane uses deterministic Grid fixtures to keep pull requests bounded.
The server acceptance below must use the production Compose file without
`docker-compose.ci.yml` and must report `real_source` Grid mode.

## Server Preflight

Run these commands from the existing server checkout before changing it:

```bash
git status --short --branch
git rev-parse HEAD
docker compose ps --all
docker compose images
docker system df
df -h
```

Stop if the checkout contains unexplained changes, the current commit is not
known, or disk headroom is insufficient. Record the output in the deployment
notes.

Authenticate without writing a token into the repository or shell history:

```bash
read -s GHCR_TOKEN
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username JortGroen --password-stdin
unset GHCR_TOKEN
```

The token needs only `read:packages` and repository access for the private model
packages. Confirm `.env` contains unique production values for every password
and valid absolute TLS certificate paths. Keep `.env` readable only by the
deployment account.

Render and validate the exact production configuration:

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --format json \
  | python3 scripts/check_release_compose.py
```

This check fails when a test fixture enters the production configuration, a
model image loses its immutable digest, Grid is not in `real_source` mode, or a
diagnostic port is exposed beyond loopback.

## Backup

Create a timestamped backup directory outside the Git checkout. At minimum,
back up the `rdp_db` database, the `geo` configuration directory, and an
encrypted copy of `.env` using the server's established secret-backup method.

Example database and GeoServer backups:

```bash
backup_dir="../rdp-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$backup_dir"
set -a
. ./.env
set +a
docker compose exec -T timescale \
  pg_dump -U "$POSTGRES_ADMIN_USER" -d rdp_db -Fc \
  > "$backup_dir/rdp_db.dump"
tar -czf "$backup_dir/geoserver-config.tar.gz" geo
unset POSTGRES_ADMIN_PASSWORD POSTGRES_DATA_SOURCE_PASSWORD \
  POSTGRES_DATA_VIS_PASSWORD POSTGRES_DATA_PUB_VIS_PASSWORD \
  REDIS_PASSWORD GRAFANA_ADMIN_PASSWORD GEOSERVER_ADMIN_PASSWORD
```

Verify that both backup files are non-empty before continuing. Existing named
model caches should remain in place; this deployment must never use
`docker compose down --volumes`.

## Moving An Existing Timescale Database (one-time, before the mount fix)

Installs created before the `timescale-data` mount fix keep the database in the
Timescale container's writable layer (the volume is mounted where the image does
not store its data). `docker compose up` with the corrected mount creates a
**new, empty** cluster and does not carry that data over, and a same-project
Compose recreation does not preserve the old container for rollback. Do **not**
run `docker compose up -d --build` on such an install until you have done this:

1. Stop everything that writes to the database (all services except Timescale).
2. With the **old** Compose files, run
   `scripts/migrate-timescale-pgdata.sh prepare -p <project> -f <old-compose> -b <empty-backup-dir>`.
   It refuses an already-migrated install, a non-empty volume or backup
   directory, and a database with no tables. It records the image id and per-table
   row counts, stops Timescale, writes an independent tar of PGDATA to the backup
   directory and copies it into the empty `<project>_timescale-data` volume.
3. Switch to the **new** Compose files and run `docker compose up -d timescale`.
4. Run `scripts/migrate-timescale-pgdata.sh verify -p <project> -f <new-compose> -b <backup-dir>`.
   It checks the mount and compares row counts with the counts from step 2.
   Only then start the other services.
5. Rollback: switch back to the **old** Compose files and run
   `scripts/migrate-timescale-pgdata.sh rollback -p <project> -f <old-compose> -b <backup-dir>`.
   It recreates the old layout, checks the image id and restores PGDATA from the tar.

Keep the backup directory until the migrated database has run correctly for a
while. It contains the full database (including role password hashes): keep it
mode 700 and off shared storage. This procedure was rehearsed under the same
Compose project on a copy of a real database (27 user tables, 263,181-row
hypertable): counts identical after cutover and after rollback.

## Promote And Start

After the owner merges the reviewed `dev` to `main`, deploy only the resulting
merge commit:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
scripts/preflight-timescale.sh -p <project> -f docker-compose.yml
docker compose pull --ignore-buildable
docker compose build --pull
docker compose up -d --build
```

The preflight refuses (exit 1, nothing changed) when an existing PostgreSQL 14
database has not been migrated to PostgreSQL 17 yet; see "Upgrading The Database To
PostgreSQL 17". Even without it, `docker compose up` cannot start an empty PostgreSQL 17
database next to PostgreSQL 14 data: the `timescale-guard` service fails first and
`timescale` is never started.

Record the deployed commit. Do not add the local or CI override files. PV can
take more than ten minutes on a cold cache, and a clean Grid initialization can
take several hours. Follow progress without restarting healthy initializers:

```bash
docker compose ps --all
docker compose logs --tail 200 pv-init grid-init wind-init heat-init
docker compose logs --tail 200 layer-publisher policy-tool-backend congestion-backend
```

## Acceptance

Run the cumulative smoke test and the full real-source Grid check from the
deployed checkout:

```bash
python3 tests/smoke_stack.py \
  --base-url https://reformers01.ewi.tudelft.nl \
  --expected-grid-data-mode real_source
python3 tests/check_full_grid.py \
  --base-url https://reformers01.ewi.tudelft.nl
```

Also verify the primary public surfaces:

```bash
curl --fail --silent --show-error https://reformers01.ewi.tudelft.nl/dashboard/ > /dev/null
curl --fail --silent --show-error https://reformers01.ewi.tudelft.nl/policy-api/layers > /dev/null
curl --fail --silent --show-error https://reformers01.ewi.tudelft.nl/models/pv/metadata > /dev/null
curl --fail --silent --show-error \
  'https://reformers01.ewi.tudelft.nl/geoserver/ows?service=WMS&version=1.3.0&request=GetCapabilities' \
  > /dev/null
```

Check the known positive transformer paths separately:

```bash
curl --fail --silent --show-error --request POST \
  --header 'Content-Type: application/json' \
  --data '{"start":"2022-12-31T23:00:00Z","end":"2023-01-01T00:00:00Z"}' \
  https://reformers01.ewi.tudelft.nl/policy-api/transformer-profiles/pc6/1483AA
curl --fail --silent --show-error --request POST \
  --header 'Content-Type: application/json' \
  --data '{"start":"2024-06-01T12:00:00Z","end":"2024-06-01T13:00:00Z"}' \
  https://reformers01.ewi.tudelft.nl/policy-api/transformer-profiles/pv/cbs-buurt/BU03610709
```

Finally, run the publisher once and inspect its output. An unchanged second run
must report zero changed and zero deleted features for every integrated layer:

```bash
docker compose run --rm --no-deps -e PUBLISH_ONCE=true layer-publisher
```

Record acceptance results and timestamps. A failed real-source check is a
failed deployment even when the deterministic CI fixture passed.

## Rollback

Rollback when a required service remains unhealthy, publication fails, the
dashboard loses an existing workflow, or either acceptance script fails.

1. Preserve failing-service logs and record the failed commit.
2. Check out the previously recorded release commit without rewriting Git
   history.
3. Re-render its Compose configuration and run `docker compose up -d --build`.
   If the release you are leaving is the PostgreSQL 17 database move, do **not** do this
   with plain Compose: use `scripts/upgrade-timescale-pg17.sh rollback` so that the rows
   written to PostgreSQL 17 since the cutover are kept (see "Upgrading The Database To
   PostgreSQL 17").
4. Keep named volumes; never add `--volumes` to rollback commands.
5. Restore `rdp_db` and the GeoServer configuration only when the release made
   an incompatible data change and the previous services cannot use the current
   state.
6. Repeat the public-route and legacy `/simulate` checks after rollback.

Do not continue forward with fixture data, unpinned images, missing provenance,
or partially initialized caches to make the deployment appear healthy.

## Upgrading The Database To PostgreSQL 17 (TimescaleDB 2.31)

The `timescale/timescaledb-ha:pg14-latest` tag was last built in April 2023 and
carries well over a thousand scanner findings. Compose now pins
`timescale/timescaledb-ha` (PostgreSQL 17, TimescaleDB 2.31, PostGIS 3.6) by digest
and keeps the data in a new `timescale-pg17-data` volume. A TimescaleDB 2.10 dump
cannot be restored into 2.31 and the images contain only one PostgreSQL major, so
the move is a logical copy into a fresh cluster. The old `timescale-data` volume is
never modified.

The measurement data is small (three tables: `data_points`, `raw_bitemporal_double`,
`raw_unitemporal_double`). The schema comes from `db-scheme` (same Alembic head) and the
layer publisher re-creates the PostGIS layers.

### Guards against an accidental empty database

* `timescale-guard` (Compose) runs before `timescale` and fails when the PostgreSQL 14
  volume holds data and the PostgreSQL 17 volume does not carry the **migration-complete
  marker** (`.illuminator-pg17-migration-complete` in the volume root). An initialised
  PostgreSQL 17 cluster (`data/PG_VERSION` = 17) is *not* proof of a migration: PostgreSQL 17
  initialises before the data is copied, so a failed or interrupted copy leaves an empty or
  partial cluster that a routine deploy would otherwise start. A new volume is not
  literally empty (Docker copies the image's empty `backup/` and `data/` directories
  into it), so "empty" means "no regular files".
* The marker is written by the cutover script only after the counts and checksums of the
  three data tables are identical, and the rollback script removes it again. A failed
  cutover never writes it. If you migrated by hand, write it yourself only after you
  have compared the counts and checksums:
  `docker exec -i <timescale> sh -c 'cat > /home/postgres/pgdata/.illuminator-pg17-migration-complete' < <checksums-file>`.
* `scripts/preflight-timescale.sh` (run before every deploy) also catches installs from
  before the mount fix, where the database lives in the container's writable layer; it
  requires the same marker.
* `TIMESCALE_ALLOW_EMPTY_PG17=yes` overrides both on purpose (an empty database). The
  cutover script sets it only for its own `up timescale` call.

### Cutover

```bash
scripts/upgrade-timescale-pg17.sh cutover -p <project> -o <old-compose.yml> -n <new-compose.yml> \
    -b ../rdp-pg17-cutover-$(date -u +%Y%m%dT%H%M%SZ) [-x docker-compose.ports.yml]
```

No password is read or printed; the admin user name comes from the running container.
The script:

1. takes a `pg_dumpall` of the running PostgreSQL 14 database;
2. **stops the writers** (`data-sync-service`, `layer-publisher`, `grafana`; override with `WRITERS`);
3. **then** records `count(*)` and an md5 checksum of the three tables, exports them, and
   records the checksums again after the export. The baseline and the export therefore
   come from the same snapshot, and a change during the export aborts the cutover;
4. starts PostgreSQL 17 on the new volume, runs `db-scheme`, creates `postgis`;
5. loads the tables (`COPY ... FROM STDIN (FORMAT binary)`; for the hypertables the export
   uses `COPY (SELECT * FROM t ORDER BY 1,2,3)`, because a plain `COPY t` of a hypertable
   silently copies nothing) and sets `data_points_id_seq`;
6. requires identical counts and checksums **before the writers are started again**, and
   only then writes the migration-complete marker. Otherwise it restores the PostgreSQL 14
   deployment (nothing was written to PostgreSQL 17 yet, so nothing is lost), writes no
   marker and exits 2.

A counts-and-checksums report only counts when every query succeeded and every table has a
line `<table> <row count> <md5>` (an empty table reports `0 empty`). A failed query, or an
answer in any other shape, fails the step instead of producing a report that happens to
compare equal, and a failure while the baseline or the loaded copy is being summed restores
PostgreSQL 14 like any other failure.

The automatic restore starts the writers again only when PostgreSQL 14 was recreated, is
the database that answers (`show server_version_num` starts with 14) and is ready. If not,
the writers **stay stopped** and the script exits 3 with the command to recover by hand; the
old volume is untouched. The rollback script makes the same check before it believes it is
talking to PostgreSQL 14.

A failed attempt leaves an initialised PostgreSQL 17 volume without a marker. The guard
refuses to start it, and a second `cutover` refuses to load on top of it ("already holds a
cluster", nothing is changed): inspect the volume and, if it is only a leftover, remove
that one volume yourself (`docker volume rm <project>_timescale-pg17-data`; the script never
deletes a volume) before you run the cutover again.

Afterwards check the routes, that nothing is unhealthy, that the layer-publisher log is
clean and that `data-sync-service` inserts rows. `<backup-dir>/cutover-baseline.txt` is the
recovery point used by a rollback.

### Rollback after the cutover

Once the writers run against PostgreSQL 17, the rows they write exist only there, so
switching back to the PostgreSQL 14 volume with plain Compose loses them. Use:

```bash
scripts/upgrade-timescale-pg17.sh rollback -p <project> -o <old-compose.yml> -n <new-compose.yml> \
    -b <the cutover backup dir> (--replay | --discard-post-cutover-writes)
```

The choice is mandatory (the script exits 64 without it) and is the approval of the
recovery point. In both modes the script first stops the writers, **exports the
PostgreSQL 17 tables to `<backup-dir>/pg17-at-rollback`** and prints the row counts at the
cutover and now, removes the marker, then starts PostgreSQL 14 from the old volume and
requires it to equal `cutover-baseline.txt`. The PostgreSQL 17 volume is kept.

The export is written once. It is built in `pg17-at-rollback.partial` and becomes
`pg17-at-rollback` (with an `EXPORT_COMPLETE` file and its `sums.txt`) only when every table
is exported, and only a database that answers as PostgreSQL 17 is exported. If a rollback
fails after PostgreSQL 14 has started (for example a failed replay) and you run it again, the
script reuses that completed export and never exports PostgreSQL 14 data over it. With no
completed export and PostgreSQL 14 already running it refuses and tells you to start the
PostgreSQL 17 deployment again first. If PostgreSQL 17 is running again and has changed
since the export, it refuses until you move the old export aside (keep it).

* `--replay` inserts the PostgreSQL 17 rows into PostgreSQL 14 through a staging schema
  (`INSERT ... ON CONFLICT DO NOTHING` on the primary keys; `data_points` first, then
  the sequence), verifies that every staged row is present (a count of staged rows with
  no match must be 0) and only then starts the writers. It is safe to repeat.
  Limits: PostgreSQL 14 / TimescaleDB 2.10 cannot insert into a *compressed* chunk, so a
  replayed row that falls into an already compressed chunk makes the replay fail and the
  writers stay stopped (decompress that chunk and run the rollback again); and rows that
  were *updated in place* in PostgreSQL 17 are not overwritten (the bitemporal table
  stores changes as new rows, so this does not occur for forecasts).
* `--discard-post-cutover-writes` restores PostgreSQL 14 as it was at the cutover. The
  rows written since then remain only in the export and in the PostgreSQL 17 volume.

After a few days without problems, and once a fresh backup exists, the old volume can be
removed (`docker volume rm <project>_timescale-data`). Do that only after the rollback
option is no longer wanted.

### Tested

`tests/test_timescale_upgrade_guards.py` (guard against real directories, preflight against
a fake `docker`; refuses an existing PostgreSQL 14 install and an initialised PostgreSQL 17
cluster without the marker, allows a fresh and a migrated one),
`tests/test_upgrade_timescale_pg17_script.py` (order of the calls with a fake `docker`:
writers stopped before baseline and export, comparison before the writers start, marker
only after the comparison, a failing or malformed checksum query never approves, a failed
restore of PostgreSQL 14 keeps the writers stopped, export before PostgreSQL 14 starts, a rollback retry keeps the
PostgreSQL 17 export byte for byte, replay verified before the writers start) and a rehearsal on
throwaway databases: after a replay the PostgreSQL 14 copy had the same counts and
checksums as the PostgreSQL 17 state, including a new `data_points` row, and replaying twice
changed nothing.
