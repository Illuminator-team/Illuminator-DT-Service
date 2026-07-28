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
- All model services expose APIs and can be called independently. The policy-tool frontend calls the policy-tool backend, and the policy-tool backend orchestrates calls to consumption, PV, EV, grid, and later model APIs for scenario workflows.
- The minimum model API contract is `GET /`, `GET /metadata`, `GET /layers`, `POST /runs`, `GET /runs/{run_id}`, and `GET /outputs/{output_id}`. Legacy endpoints may remain during transition.
- Model and scenario runs are synchronous in the first working version, but every run still gets a `run_id`, status, timestamps, inputs, output links, and metadata so the same contract can become asynchronous later.
- Scenario execution uses one JSON request to the policy-tool backend, with time settings, layer-native spatial selections, per-model parameter blocks, and requested outputs. The MVP schema should stay simple but map cleanly to OpenAPI and future OGC API Processes inputs/outputs.
- There is no single canonical scenario area yet. Spatial selections are layer-native feature references: CBS buurt, PC6, public EV charger, grid asset, transformer area, or later custom geometry, depending on the model/layer.
- The grid model publishes grid assets/topology only. The congestion model owns a stored grid-assignment mapping that links each layer feature/profile to the closest Euclidean LV component and refreshes that mapping whenever source layers change.
- Allocation rules for area features with multiple LV components, such as CBS buurten or PC6 areas, are deferred to the congestion model story.
- Each metadata record should be designed so it can later map to DCAT-AP-NL, ISO 19115/19119, OGC API Records, and SensorThings concepts.
- Data completeness, confidence, provenance, and freshness should be available for every layer, feature, profile, and scenario result where possible.

Geonovum/NLDT interpretation:

- Use NEN 3610/MIM-style thinking for geo-object concepts and relationships.
- Use OGC services for spatial publication. WMS/WFS are acceptable during the transition, while OGC API Features/Tiles are the intended modern direction.
- Use ISO 19115/19119 and DCAT-AP-NL concepts for dataset and service metadata, but do not require full catalogue publication in the first prototype.
- Use observation/time-series language for profiles so the system can later align with SensorThings-style APIs.
- Keep spatial features and observation/time-series data conceptually separate, even when the prototype stores them in simple files. This leaves room for SensorThings and OGC API Joins later without blocking the first working version.
- Treat the policy-tool backend as the first pragmatic orchestration component. This fits the NLDT guardrails of loosely coupled, API-speaking, containerable components; OGC API Processes can be a later alignment target for standardized process execution, not an MVP requirement.
- Document APIs with OpenAPI once the route shapes stabilize, matching the Dutch API Strategy direction. Geo-oriented APIs should stay compatible with the geospatial API strategy and OGC API Features direction where relevant.
- OGC API Processes supports synchronous and asynchronous execution patterns with job/status/result concepts. The MVP should borrow those concepts lightly without implementing the full standard yet.
- Scenario request fields should use standards-friendly names and explicit units, identifiers, geometry references, and output links so they can later be expressed as JSON Schema/OpenAPI, catalogue metadata, or OGC API Processes execution inputs.
- Prefer references to existing geo-objects over copying geometry into scenario requests. This aligns with NEN 3610/MIM-style geo-object identity, OGC API Features-style feature access, and later OGC API Joins for connecting tabular/profile data to geo-objects.
- Store grid assignments as relationships between source geo-objects/profiles and grid geo-objects, with method, distance, confidence, provenance, and source versions. This keeps the mapping standards-friendly and auditable instead of hiding it inside model code.
- Treat early JSON records as a pragmatic bridge toward standards, not as a private replacement for standards.

## Target Shape

Model services should follow this pattern:

```text
input adapter -> model core -> output adapter
```

The model core should be independent from RDP infrastructure. Input and output adapters decide whether the model reads local files, direct API/cache data, Redis streams, Timescale/PostGIS tables, or writes file outputs, API responses, and GeoServer/PostGIS layers.

Planned services:

- `policy-tool-backend`: frontend-facing scenario/orchestration API. It coordinates calls to model APIs and may keep the current residential load calculation internally during transition.
- `consumption-model-service`: generates residential, commercial, and industrial demand layers and profiles. The current residential load logic should move here or be wrapped as this service over time.
- `pv-map-service`: generates PV potential/generation layers and profiles.
- `ev-charger-model-service`: generates public EV charger location layers and charging demand profiles.
- `grid-map-service`: publishes grid topology, asset, capacity, and headroom layers. It should not own load/PV/EV-to-grid assignment logic.
- `congestion-model-service`: consumes model profiles, grid layers, and the stored grid-assignment mapping to aggregate profiles and calculate congestion indicators.
- `other-model-service`: placeholder for later independent model services that publish layers/profiles through the same contract.

If orchestration grows beyond simple scenario coordination, it can later be split out of the policy-tool backend. For the next versions, keeping orchestration in the policy-tool backend gives the frontend one stable API to call.

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

## Model APIs And Orchestration

Each model service should expose a small common API surface so the policy-tool backend can call consumption, PV, EV, grid, and later models consistently:

```text
GET  /
GET  /metadata
GET  /layers
POST /runs
GET  /runs/{run_id}
GET  /outputs/{output_id}
```

Endpoint meanings:

- `GET /`: lightweight health and service identity response.
- `GET /metadata`: model metadata, including model id, version, owner, spatial coverage, temporal resolution, inputs, outputs, assumptions, and data quality fields.
- `GET /layers`: map layer metadata for outputs that can be shown in GeoServer or a future OGC API layer endpoint.
- `POST /runs`: starts a model run from scenario inputs. It may execute synchronously in the MVP, but should still return a `run_id` and output metadata when practical.
- `GET /runs/{run_id}`: returns run status, parameters, timestamps, and links to outputs.
- `GET /outputs/{output_id}`: returns output metadata plus links to layer resources, profile files, database records, or service endpoints.

The existing residential load behavior can keep `GET /simulate/{pc6}` during transition, but new model APIs should move toward run IDs and output metadata records. That will make it easier for the policy-tool backend to consume multiple model outputs consistently.

Maturity path:

- MVP: simple FastAPI/HTTP JSON routes, permissive internal schemas, synchronous runs allowed, and optional generated CSV/profile files.
- Next: shared request/response schemas across models, explicit error responses, stable run/output ids, and generated OpenAPI specs.
- Professional target: API Design Rules/OpenAPI documentation, geospatial alignment where applicable, and OGC API Processes-style execution for standardized process invocation when it starts paying for itself.

The policy-tool backend should expose the frontend-facing scenario API. MVP endpoints can stay simple, but the direction is:

```text
GET  /
GET  /metadata
GET  /models
POST /scenarios
GET  /scenarios/{scenario_id}
GET  /scenarios/{scenario_id}/outputs
```

In the MVP, orchestration may be synchronous and direct: receive scenario settings, call the relevant model APIs, collect output metadata, and return links to layers and profiles. Later versions can add async jobs, retries, model registry lookup, authorization, and OGC API Processes-style execution once the basic workflow is stable.

## Run Lifecycle

The first version should execute model and scenario runs synchronously when the calculation is quick enough for an HTTP request. The response should still be shaped like a persisted run so the frontend and orchestrator do not need a redesign later.

Minimum run fields:

- `run_id`: stable identifier for the calculation.
- `status`: at least `accepted`, `running`, `completed`, or `failed`, even if MVP runs usually jump straight to `completed` or `failed`.
- `created_at`, `started_at`, and `finished_at`: timestamps for debugging, provenance, and later history views.
- `inputs`: the scenario/model parameters used for the run, or a pointer to them.
- `outputs`: links to layer metadata, profile files, database records, or API outputs.
- `data_quality`: completeness/confidence/provenance summary for the run result.

Maturity path:

- MVP: calculate immediately, return `run_id`, status, outputs, and metadata in the same response.
- Next: persist run records so `GET /runs/{run_id}` can return previous results and failures.
- Professional target: support asynchronous jobs, cancellation, progress/status polling, result retrieval, and OGC API Processes-style execution where it improves interoperability.

## Scenario Input Contract

The policy-tool frontend should send one scenario JSON request to the policy-tool backend when a user presses calculate. The policy-tool backend then translates that scenario request into calls to the enabled model APIs.

The spatial part should be flexible. Users are not always selecting a single area. Depending on the active layer, they might select a CBS buurt, a PC6 area, one public charging station, a grid cable, a transformer area, or later a custom drawn polygon.

MVP request shape:

```json
{
  "scenario_name": "High PV and EV adoption",
  "spatial_selection": {
    "items": [
      {
        "model": "consumption",
        "feature_type": "cbs_buurt",
        "ids": ["BU03610000"]
      },
      {
        "model": "ev",
        "feature_type": "public_charging_station",
        "ids": ["evse-12345"]
      }
    ]
  },
  "time": {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-01-02T00:00:00Z",
    "resolution": "PT15M"
  },
  "models": {
    "consumption": { "enabled": true },
    "pv": { "enabled": true },
    "ev": { "enabled": true },
    "grid": { "enabled": true }
  },
  "outputs": {
    "layers": true,
    "profiles": true,
    "data_quality": true
  }
}
```

Minimum fields:

- `scenario_name`: human-readable name for the run.
- `spatial_selection`: one or more selected feature references, using stable identifiers where possible.
- `time`: start, end, and resolution, with `PT15M` as the scenario time step for now.
- `models`: one block per model, each with `enabled` and model-specific scenario parameters.
- `outputs`: requested result types, such as map layers, profiles, data quality, and later reports.

Spatial selection rules:

- each layer/model defines which feature types it supports, such as `cbs_buurt`, `pc6`, `public_charging_station`, `grid_asset`, or `transformer_area`;
- prefer selecting existing feature identifiers from GeoServer/PostGIS instead of sending copied geometries;
- allow custom GeoJSON geometry later for drawn polygons or analysis areas, but treat that as an additional feature type with clear CRS and provenance;
- keep model-specific interpretation inside the model service. For example, the EV model understands EV charger ids, while the consumption model understands PC6 or CBS buurt ids;
- the policy-tool backend validates that the requested models can understand the selected feature types before it starts a run.

Geonovum alignment guardrail:

- keep the request as plain JSON for the first working version;
- make units, identifiers, spatial references, temporal resolution, and requested outputs explicit;
- avoid frontend-only parameter names that cannot be understood by another client;
- document the request with OpenAPI/JSON Schema once the fields stabilize;
- keep the structure close enough to OGC API Processes `inputs` and `outputs` concepts that it can later be wrapped as a standards-facing process execution request;
- keep feature references compatible with NEN 3610/MIM-style object identity, OGC API Features-style feature access, and later OGC API Joins where profiles or tabular scenario data need to connect to geo-objects.

This gives the dashboard a quick working contract while keeping a clear path to the professional Geonovum/NLDT-style setup.

## Grid Assignment Mapping

The grid model should share the grid: topology, assets, geometry, voltage level, capacity, and other grid metadata. It should not decide how consumption, PV, EV, or other profiles connect to the grid.

The congestion model should own a stored assignment mapping. That mapping links each relevant feature/profile from each layer to a grid component. The first working rule is closest Euclidean LV component.

MVP mapping record:

```json
{
  "id": "https://reformers01.ewi.tudelft.nl/id/grid-assignment/ev/evse-12345",
  "source": {
    "layer_id": "https://reformers01.ewi.tudelft.nl/id/layer/ev/public-chargers",
    "feature_type": "public_charging_station",
    "feature_id": "evse-12345",
    "profile_id": "https://reformers01.ewi.tudelft.nl/id/time-series/ev/evse-12345/charging-demand/base"
  },
  "grid_target": {
    "layer_id": "https://reformers01.ewi.tudelft.nl/id/layer/grid/lv-components",
    "component_type": "lv_component",
    "component_id": "lv-component-987"
  },
  "assignment": {
    "method": "nearest_euclidean_lv_component",
    "distance_m": 42.7,
    "share": 1.0,
    "confidence": "medium"
  },
  "provenance": {
    "source_layer_version": "2026-07-28",
    "grid_layer_version": "2026-07-28",
    "updated_at": "2026-07-28T00:00:00Z"
  }
}
```

MVP behavior:

- build or refresh the mapping when a source layer/profile layer changes;
- build or refresh the mapping when the grid layer changes;
- store the mapping outside the model outputs, preferably in PostGIS/Timescale once integrated, and as a simple file/table during standalone development;
- let the congestion model consume the mapping to aggregate profiles onto LV components, LV/MV transformers, and later MV/HV transformers;
- expose mapping completeness and confidence so the frontend can show where congestion results are based on strong or weak assignment evidence.

Deferred story:

For area features such as CBS buurten or PC6 areas, there may be multiple LV components inside the area. The exact allocation rule is not decided here. The congestion model story should decide whether to use nearest component, centroid distance, spatial overlap, address/building counts, connection data, proportional shares, or another rule. Until then, any area assignment must clearly record the method and confidence.

Geonovum alignment guardrail:

- treat assignments as explicit relationships between geo-objects, not as hidden assumptions;
- prefer persistent identifiers for both source features and grid assets;
- record method, distance, versions, confidence, and provenance;
- keep the structure compatible with later OGC API Joins-style linking between profile/scenario tables and geo-objects.

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
- group layers by model: consumption, PV, EV, grid, scenarios;
- allow multiple overlays when they make sense;
- request scenario runs through the policy-tool backend, which then calls the relevant model APIs;
- render output metadata records rather than assuming every model writes one specific CSV filename.

This keeps the dashboard usable while avoiding a future pileup of model-specific JavaScript branches.

## Near-Term Steps

1. Keep the current policy-tool backend name in code for now, but document it as the frontend-facing scenario/orchestration API.
2. Add a shared model output metadata record shape and generate it alongside the current CSV output.
3. Introduce explicit standalone/RDP config switches in the current residential load code and its future consumption model service.
4. Move direct external data calls in the residential model behind input adapters.
5. Add a frontend layer registry that can read current static layers plus generated model metadata records.
6. Define the first scenario JSON request schema with flexible layer-native spatial selections in the policy-tool backend and frontend.
7. Start the policy-tool backend scenario/orchestration API while preserving the current frontend flow.
8. Start the PV map as an independent model service with standalone local inputs first.
9. Start the EV charger model as an independent model service with standalone local inputs first.
10. Start the grid map as an independent model service with standalone local inputs first.
11. Add the first congestion-model grid-assignment mapping using closest Euclidean LV component, with refresh on layer updates.
12. Promote shared external API connections into crawler/ingestion services when the data contract stabilizes.

## Open Questions

- What is the first shared Timescale/PostGIS schema for model profiles once CSV output is no longer enough?
- Which spatial selection types should each model/layer support first: CBS buurt, PC6, building, EV charger, grid asset, feeder, transformer area, or mixed?
- For area features with multiple LV components, which congestion-model allocation rule should be used first: nearest component, centroid distance, spatial overlap, address/building counts, connection data, proportional shares, or another rule?
- Once run persistence is added, how long should scenario history and output artifacts be retained?
- When should orchestration move out of the policy-tool backend into a dedicated service, if ever?
- Which scenario parameters are generic enough for the policy-tool backend contract, and which should stay inside model-specific parameter blocks?
- Which external sources belong in the RDP crawler immediately, and which can remain standalone-only while prototyping?
