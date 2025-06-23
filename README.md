# RDP Tutorial

Trying to integrate an API through traeffik for RDP with the Illuminator.

## About

This repository provides the source code for a step-by-step tutorial for the [Rapid Deployment Platform](https://ait-rdp.github.io/).

+ **Step 1**:
  Setup of the [Redis](https://redis.io/) stream and [Redis Insight](https://redis.io/insight/) for debugging.
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-1).
+ **Step 2**:
  Add an [RDP Data Crawler](https://ait-rdp.github.io/rdp-data-crawler) for retrieving weather data.
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-2).
+ **Step 3**:
  Add an [RDP Database](https://ait-rdp.github.io/rdp-database) and an [RedSQL Data Sync](https://ait-rdp.github.io/rdp-redsql) for long-time storage of the weather data.
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-3).
+ **Step 4**:
  Add a [Grafana](https://grafana.com/oss/grafana/) dashboard for visualizing the weather data.
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-4).
+ **Step 5**:
  Integrate a new micro-service for forecasting the power output of a PV module based on the weather data.
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-5).
+ **Step 6**:
  Integrate a custom data crawler for retrieving the power grid frequency from the public [Energy-Charts API](https://api.energy-charts.info/).
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-6).
+ **Step 7**:
  Configure a reverse proxy for securing access to the dashboard via TLS (using a self-signed certificate).
  The code is available [here](https://github.com/AIT-RDP/rdp-tutorial/tree/step-7).

## Prerequisites

You need to have [Docker](https://docs.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed.

## Usage

Generate a private key (`server.key`) and certificate (`server.crt`) in sub-directory `certs`:
``` bash
docker pull alpine/openssl
docker run --rm -v $PWD/certs:/certs alpine/openssl genrsa -out certs/server.key 2048
docker run --rm -v $PWD/certs:/certs alpine/openssl req -new -x509 -sha256 -key certs/server.key -out certs/server.crt -config certs/certs.cfg
```

All secrets and variables are managed via environment variables.
For this simple example, it is recommended to define them via an `.env` file.
You may have a look at the example file [`.env.example`](.env.example) for a list of expected variables.

Build the services and deploy the setup:
``` shell
docker compose build
docker compose up
```

View the dashboard in your browser via: https://localhost/grafana
