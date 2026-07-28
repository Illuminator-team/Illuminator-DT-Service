# Future Model Integration Plan

## Purpose

This document sketches how the current policy-tool stack can grow into a set of independent RDP model services that feed shared frontend layers and can later interact through scenario models.

The current `policy-tool-backend` should be treated as the first model service: a residential load map. The next expected model services are a PV map and a grid map. Each model should be able to run standalone during development, while still having a clear path into the RDP deployment.

## Current Starting Point

- `policy-tool-frontend` serves the dashboard at `/dashboard`.
- `policy-tool-backend` serves the API at `/policy-api`.
- The backend currently exposes `GET /simulate/{pc6}` and writes `pc6_profile_<PC6>.csv` into a shared processed-data volume.
- The frontend fetches the simulation endpoint, then reads the generated CSV from `/dashboard/processed`.
- The current backend mixes model execution, local file ingestion, and some direct external data fetching. That is acceptable for the prototype, but should become more explicit as new models are added.

## Epic 1 Decisions: Shared Data And Layer Contract

The first implementation should be standards-aware but not standards-heavy. The priority is to keep a working end-to-end map and scenario flow, then upgrade the metadata and API surfaces toward the Geonovum/NLDT direction as the model contracts stabilize.

Decisions made so far:

- Scenario calculations use a 15-minute time step, expressed as `PT15M` in metadata.
- Layers may keep their native spatial resolution. Consumption can use PC6 or CBS buurt areas, public EV chargers can use point locations, PV can use CBS buurt areas, and grid assets can use exact grid geometries where available.
- Every map feature may have one or more profiles. In standards-aligned terms, a profile is a time series or observation collection linked to a geo-object.
- GeoServer is the first publication target for spatial layers. The design should keep a path toward OGC API Features and OGC API Tiles later.
- Identifiers should be URI-style from the start, using `https://reformers01.ewi.tudelft.nl/id/` as the initial TU Delft base URI.
- Model, layer, profile, scenario, and run metadata starts as lightweight JSON metadata records, not as full formal catalogue infrastructure.
- Profile storage follows a maturity path: simple CSV/file outputs for standalone development first, shared Timescale/PostGIS storage for integrated RDP deployment next, and standards-facing observation APIs later.
- Each metadata record should be designed so it can later map to DCAT-AP-NL, ISO 19115/19119, OGC API Records, and SensorThings concepts.
- Data completeness, confidence, provenance, and freshness should be available for every layer, feature, profile, and scenario result where possible.

Geonovum/NLDT interpretation:

- Use NEN 3610/MIM-style thinking for geo-object concepts and relationships.
- Use OGC services for spatial publication. WMS/WFS are acceptable during the transition, while OGC API Features/Tiles are the intended modern direction.
- Use ISO 19115/19119 and DCAT-AP-NL concepts for dataset and service metadata, but do not require full catalogue publication in the first prototype.
- Use observation/time-series language for profiles so the system can later align with SensorThings-style APIs.
- Keep spatial features and observation/time-series data conceptually separate, even when the prototype stores them in simple files. This leaves room for SensorThings and OGC API Joins later without blocking the first working version.
- Treat early JSON records as a pragmatic bridge toward standards, not as a private replacement for standards.

## Target Shape

Model services should follow this pattern:

```text
input adapter -> model core -> output adapter
```

The model core should be independent from RDP infrastructure. Input and output adapters decide whether the model reads local files, direct API/cache data, Redis streams, Timescale/PostGIS tables, or writes file outputs, API responses, and GeoServer/PostGIS layers.

Planned services:

- `residential-load-map-service`: current policy-tool backend, generating PC6 residential demand and heat/electrification profiles.
- `pv-map-service`: generates PV potential/generation layers and time series.
- `grid-map-service`: generates grid topology, asset, capacity, and headroom layers.
- `scenario-interaction-service`: later service that consumes outputs from the independent models and computes interactions, for example PV impact on net demand or grid congestion.

## Standalone And RDP Modes

Each model should support both local development and RDP deployment.

Recommended environment/config switches:

```text
RUN_MODE=standalone|rdp
INPUT_BACKEND=local|rdp
OUTPUT_BACKEND=file|postgis|geoserver
```

Standalone mode should prioritize fast development:

- read sample CSV/GeoJSON/Parquet files from the service directory;
- optionally read from a local cache of external API responses;
- write outputs to `data/processed` or another ignored local output directory;
- expose the same HTTP API shape as the deployed service where practical.

RDP mode should prioritize integration:

- read from RDP-managed Redis streams, Timescale tables, or PostGIS tables;
- use data generated by crawler/ingestion services instead of each model calling external APIs directly;
- publish model outputs through shared RDP data stores and layer publication paths.

## Profile Storage Maturity Path

Profiles should be easy to generate during standalone model development and easy to share once models are integrated.

MVP behavior:

- models may write profile outputs as CSV files, matching the current residential load dashboard flow;
- each CSV should be accompanied by a small JSON metadata record that identifies the feature, model run, metric, unit, time resolution, data quality, and provenance;
- GeoServer remains responsible for map layers, while profile files are fetched separately by the frontend or model-specific endpoint.

Integrated RDP behavior:

- model services write profiles into shared Timescale/Postgres tables;
- PostGIS stores or references the geo-objects that the profiles belong to;
- output metadata links GeoServer feature identifiers to the profile rows or profile collection;
- the frontend stops depending on model-specific filenames and instead reads metadata records.

Professional target:

- metadata records can be published through catalogue-style interfaces aligned with DCAT-AP-NL, ISO 19115/19119, and OGC API Records;
- time-series/observation access can move toward a SensorThings-style API where that gives real interoperability value;
- table-to-geo-object linking can align with OGC API Joins where profile or scenario data needs to be connected to existing spatial objects without duplicating geometries.

This means early versions stay quick and working, while every output still carries enough identity and metadata to be upgraded later.

## Data Ownership

External API connections should move toward crawler/ingestion services rather than living inside every model.

Preferred flow:

```text
external source -> RDP crawler/ingestion -> Redis/Timescale/PostGIS -> model service -> layer publisher/GeoServer/API -> frontend
```

Temporary standalone exceptions are allowed for development, but any direct API call in a model should be isolated behind an input adapter so it can be replaced by an RDP data source later.

## Common Model API

Each model service should eventually expose a small common API surface:

```text
GET  /
GET  /metadata
GET  /layers
POST /runs
GET  /runs/{run_id}
GET  /outputs/{output_id}
```

The existing residential load service can keep `GET /simulate/{pc6}` during transition, but new code should move toward run IDs and output metadata records. That will make it easier for the frontend and future interaction services to consume multiple model outputs consistently.

## Layer Metadata Record

Each model output intended for the map should include a lightweight layer metadata record. This is the MVP form of metadata: simple enough for the frontend to consume now, but structured so it can later be mapped to formal catalogue and geo metadata standards.

```json
{
  "id": "https://reformers01.ewi.tudelft.nl/id/layer/consumption/residential-pc6",
  "local_id": "layer:consumption:residential-pc6",
  "title": "Residential Load by PC6",
  "model": {
    "id": "https://reformers01.ewi.tudelft.nl/id/model/residential-load-map",
    "local_id": "model:residential-load-map"
  },
  "run": {
    "id": "https://reformers01.ewi.tudelft.nl/id/run/local-dev-001",
    "local_id": "run:local-dev-001"
  },
  "geoserver_layer": "rdp:residential_pc6",
  "feature_id_property": "uri",
  "geometry_type": "polygon",
  "spatial_level": "pc6",
  "time_series": [
    {
      "id": "https://reformers01.ewi.tudelft.nl/id/time-series/pc6/1842EM/electricity-demand/base",
      "local_id": "profile:pc6:1842EM:electricity-demand:base",
      "observed_property": "electricity_demand",
      "unit": "kWh",
      "time_resolution": "PT15M"
    }
  ],
  "data_quality": {
    "completeness": 0.82,
    "confidence": "medium",
    "estimated_values": true,
    "last_updated": "2026-07-28T00:00:00Z"
  }
}
```

The exact schema can evolve, but every layer should identify:

- model and run identity;
- geometry type and spatial level;
- available metrics and units;
- time handling;
- data source location;
- data quality and provenance;
- optional style hints for the frontend.

This record is deliberately smaller than DCAT-AP-NL or ISO 19115/19119 metadata. Those standards should influence names, identifiers, provenance, quality, and service links, but the first implementation only needs the fields required to make the dashboard work and remain upgradeable.

## Frontend Direction

The frontend should evolve from hardcoded layer radio buttons into a layer registry:

- load available model layers from static metadata records or model APIs;
- group layers by model: residential load, PV, grid, scenarios;
- allow multiple overlays when they make sense;
- request model runs through a common run API;
- render output metadata records rather than assuming every model writes one specific CSV filename.

This keeps the dashboard usable while avoiding a future pileup of model-specific JavaScript branches.

## Near-Term Steps

1. Keep the current policy-tool backend name in code for now, but document it as the residential load map model.
2. Add a shared model output metadata record shape and generate it alongside the current CSV output.
3. Introduce explicit standalone/RDP config switches in the residential load service.
4. Move direct external data calls in the residential model behind input adapters.
5. Add a frontend layer registry that can read current static layers plus generated model metadata records.
6. Start the PV map as an independent model service with standalone local inputs first.
7. Start the grid map as an independent model service with standalone local inputs first.
8. Promote shared external API connections into crawler/ingestion services when the data contract stabilizes.
9. Add a scenario interaction service only after at least two independent model outputs have stable metadata records.

## Open Questions

- What is the first shared Timescale/PostGIS schema for model profiles once CSV output is no longer enough?
- What is the canonical spatial unit for each model: PC6, building, grid node, feeder, transformer, or mixed?
- Do model runs need persistence and history from the start, or only latest-result behavior during prototyping?
- Should the frontend call model services directly, or should there be a thin model registry/orchestrator API?
- Which external sources belong in the RDP crawler immediately, and which can remain standalone-only while prototyping?
