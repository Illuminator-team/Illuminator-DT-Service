# RDP with WFS Geoserver API

A proof of concept WFS API implementation of the Rapid Deployment Platform.

## About

This repository is based on the step-by-step tutorial for the [Rapid Deployment Platform](https://ait-rdp.github.io/).

## Prerequisites

You need to have [Docker](https://docs.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed.

The pinned PV and Liander Grid model images are private GitHub Container Registry packages. Before
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

The first start pulls the PV and Grid models by their verified immutable GHCR
digests. PV runs its one-shot public-source initializer, which can download
substantial source data and take more than ten minutes; the `pv-raw-cache`
volume is reused on later starts. The local override initializes Grid from the
checked-in 22-line/1-transformer Alkmaar acceptance fixture. The production
Compose path instead runs the model-owned `north-holland-towns` source
initializer and persists its result in `grid-model-data`.

Local endpoints:

- dashboard: https://localhost/dashboard/
- GeoServer: https://localhost/geoserver/web/
- PV model API: https://localhost/models/pv/docs
- Grid model API: https://localhost/models/grid/docs
- Grafana: https://localhost/grafana/
- Redis Insight: http://localhost:5540/
- Traefik dashboard: http://localhost:8080/dashboard/

The browser may require one-time acceptance of a self-signed development
certificate. The dashboard loads `rdp:policy_tool_pc6_energy` from GeoServer
WFS and automatically falls back to the checked-in GeoJSON if WFS is
temporarily unavailable. The independent `rdp:pv_capacity` layer is loaded
from GeoServer WFS without substituting consumption data when it is unavailable.
The independent `rdp:grid_lines` and `rdp:grid_transformers` layers are likewise
loaded from GeoServer WFS. Selecting either Grid layer changes the map and
feature details while leaving the congestion scenario controls available.

Run the PC6, PV, and Grid publication contracts and frontend layer-adapter tests:

```shell
python -m unittest discover -s tests -p "test_*.py"
node --check policy-tool-frontend/script.js
node --test tests/map-data.test.js
```

With the stack running, execute the integrated smoke test:

```shell
python tests/smoke_stack.py --base-url https://localhost
```

## Documentation

- [Future model integration plan](docs/model-integration-plan.md)
- [Model developer integration guide](docs/model-developer-integration-guide.md)
- [PV integration lessons learned](docs/pv-integration-lessons-learned.md)
