# RDP with WFS Geoserver API

A proof of concept WFS API implementation of the Rapid Deployment Platform.
## About

This repository is based on the step-by-step tutorial for the [Rapid Deployment Platform](https://ait-rdp.github.io/). 

## Prerequisites

You need to have [Docker](https://docs.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed.

## Usage

Build the services and deploy the setup:
``` shell
docker compose build
docker compose up
```

View the geoserver dashboard in your browser via: https://localhost/geoserver
