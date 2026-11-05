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
docker compose pull --ignore-buildable
docker compose build --pull
docker compose up -d --build
```

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
4. Keep named volumes; never add `--volumes` to rollback commands.
5. Restore `rdp_db` and the GeoServer configuration only when the release made
   an incompatible data change and the previous services cannot use the current
   state.
6. Repeat the public-route and legacy `/simulate` checks after rollback.

Do not continue forward with fixture data, unpinned images, missing provenance,
or partially initialized caches to make the deployment appear healthy.
