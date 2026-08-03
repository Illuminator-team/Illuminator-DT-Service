# RDP with WFS Geoserver API

A proof of concept WFS API implementation of the Rapid Deployment Platform.

## About

This repository is based on the step-by-step tutorial for the [Rapid Deployment Platform](https://ait-rdp.github.io/).

## Prerequisites

You need to have [Docker](https://docs.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed.

## Usage

Create a local `.env` from `.env.example`, replace every `change-me` value, and
set `PATH_TO_CERT_FILE` and `PATH_TO_KEY_FILE` to a TLS certificate and key.
The files are ignored by Git.

Start the local stack with isolated GeoServer and Illuminator output volumes:

```shell
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Local endpoints:

- dashboard: https://localhost/dashboard/
- GeoServer: https://localhost/geoserver/web/
- Grafana: https://localhost/grafana/
- Redis Insight: http://localhost:5540/
- Traefik dashboard: http://localhost:8080/dashboard/

The browser may require one-time acceptance of a self-signed development
certificate. The dashboard loads `rdp:policy_tool_pc6_energy` from GeoServer
WFS and automatically falls back to the checked-in GeoJSON if WFS is
temporarily unavailable.

Run the source-contract and frontend fallback tests:

```shell
python -m unittest discover -s tests -p "test_*.py"
node --test tests/map-data.test.js
```

With the stack running, execute the integrated smoke test:

```shell
python tests/smoke_stack.py --base-url https://localhost
```
