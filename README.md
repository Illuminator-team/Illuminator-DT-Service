# RDP with WFS Geoserver API

A proof of concept WFS API implementation of the Rapid Deployment Platform.

## About

This repository is based on the step-by-step tutorial for the [Rapid Deployment Platform](https://ait-rdp.github.io/).

## Prerequisites

You need to have [Docker](https://docs.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed.

The pinned PV, Liander Grid, Wind, and Heat model images are private GitHub Container Registry packages. Before
a local first start, authenticate Docker with a separately managed GitHub token
limited to `read:packages`; do not store that token in this repository:

```shell
echo "$GHCR_TOKEN" | docker login ghcr.io --username <github-user> --password-stdin
```

The integration workflow reads the equivalent pull-only credential from the
encrypted `JORT_PRIVATE_DOCKER_IMAGES` GitHub Actions repository secret.
The same secret is the shared pull credential for future private model images
that the `JortGroen` account can read; one GHCR login can authenticate all such
pulls in the Illuminator workflow. The secret is scoped to this repository and
does not publish images from the individual model repositories.

## Usage

Create a local `.env` from `.env.example`, replace every `change-me` value, and
set `PATH_TO_CERT_FILE` and `PATH_TO_KEY_FILE` to a TLS certificate and key.
The files are ignored by Git.

Start the local stack with isolated GeoServer and Illuminator output volumes:

```shell
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

The first start pulls the PV, Grid, Wind, and Heat models by their verified immutable GHCR
digests. PV runs its one-shot public-source initializer, which can download
substantial source data and take more than ten minutes; the `pv-raw-cache`
volume is reused on later starts. Grid runs the same model-owned
`north-holland-towns` source initializer used by the production Compose path,
covering the network from Alkmaar through Schagen, and persists its prepared
cache in `grid-model-data`. The first full initialization can take multiple
hours. Compatible real-source caches are reused on later starts before any
source download; use the model initializer's explicit `--force` option when a
fresh Liander source rebuild is intended.

The local override initializes Wind from the model-owned four-turbine Alkmaar
fixture and all six Heat evidence layers from the Heat model's explicit fixture
lane. Production uses each model's bounded real-source initializer and persists
their results in `wind-model-data` and `heat-model-data`.

To attach an existing verified real-source cache instead of initializing a new
one, select its Docker volume explicitly:

```powershell
$env:GRID_MODEL_DATA_VOLUME = "grid_grid-model-data-v202"
docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.full-grid.yml up -d --build
```

`docker-compose.local.yml` never enables fixture mode. The acceptance fixture
is isolated in `docker-compose.ci.yml` and must only be added deliberately for
CI or contract testing; using that override replaces the active Grid view with
the small deterministic test area.

CI adds `docker-compose.ci.yml` to replace only the Grid initializer and
publisher selection with the checked-in deterministic acceptance fixture:

```shell
docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.ci.yml up -d --build
```

The CI smoke check must likewise declare fixture mode explicitly:

```shell
python tests/smoke_stack.py --base-url http://127.0.0.1 --expected-grid-data-mode fixture
```

Local endpoints:

- dashboard: http://illuminator.localhost/dashboard/
- GeoServer: http://illuminator.localhost/geoserver/web/
- PV model API: http://illuminator.localhost/models/pv/docs
- Grid model API: http://illuminator.localhost/models/grid/docs
- Wind model API: http://illuminator.localhost/models/wind/docs
- Heat model API: http://illuminator.localhost/models/heat/docs
- Grafana: http://illuminator.localhost/grafana/
- Redis Insight: http://localhost:5540/
- Traefik dashboard: http://localhost:8080/dashboard/

The local override uses HTTP so development does not depend on trusting a
self-signed certificate. `localhost` and `127.0.0.1` are also accepted, but
`illuminator.localhost` avoids previously cached HTTPS redirects. The dashboard
loads `rdp:policy_tool_pc6_energy` from GeoServer
WFS and automatically falls back to the checked-in GeoJSON if WFS is
temporarily unavailable. The independent `rdp:pv_capacity` layer is loaded
from GeoServer WFS without substituting consumption data when it is unavailable.
The Grid view loads `rdp:grid_lines`, `rdp:grid_transformers`,
`rdp:grid_lv_mv_transformer_reach`, and
`rdp:grid_mv_hv_transformer_reach` from GeoServer WFS. Its checkboxes
independently control every voltage tier, both transformer types, and both
PC6 share maps. Selecting a grid feature changes only the details panel, so
the congestion scenario controls remain available.

Normal local initialization passes
`policy-tool-frontend/data/alkmaar_energy_map.geojson` to the grid model with
`--pc6-geojson`. The reach layers therefore cover those Alkmaar PC6 polygons
while the grid components themselves extend through Schagen. A future,
wider consumption-model PC6 export can replace this input without changing
the layer or API contracts. Accepted PC6 identifiers are `pc6_id`,
`postcode6`, or `postcode`; geometry must be Polygon or MultiPolygon.

After the full local initializer and publisher have completed, verify that the
published topology extends through Schagen and that both reach layers preserve
matching PC6 coverage and valid transformer shares:

```shell
python tests/check_full_grid.py --base-url http://127.0.0.1
```

The check requires real-source mode, all three voltage levels, seven named
MV/HV roots, northern grid geometry, and consistent LV/MV and MV/HV PC6 shares.

The independent `rdp:public_wind_turbines` point layer exposes published nameplate
capacity, provisional generation summaries, and model-owned
`datacompleetheid`; selecting it also leaves the scenario controls in place.
The Heat evidence selector exposes six separate GeoServer layers for reported
neighbourhood consumers, inferred PC6 consumers, registered developments,
documented actual sources, documented large consumers, and potential sources.
These evidence classes stay separate and selecting any of them leaves the
scenario controls in place.

Run the PC6, PV, Grid, Wind, and Heat publication contracts and frontend layer-adapter tests:

```shell
python -m unittest discover -s tests -p "test_*.py"
node --check policy-tool-frontend/script.js
node --test tests/map-data.test.js
```

With the stack running, execute the integrated smoke test:

```shell
python tests/smoke_stack.py --base-url http://127.0.0.1
```

## Documentation

- [Future model integration plan](docs/model-integration-plan.md)
- [Model developer integration guide](docs/model-developer-integration-guide.md)
- [PV integration lessons learned](docs/pv-integration-lessons-learned.md)
- [Wind turbine integration](docs/wind-integration.md)
- [Heat network integration](docs/heat-integration.md)
