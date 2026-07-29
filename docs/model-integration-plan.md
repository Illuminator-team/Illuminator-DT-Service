# Future Model Integration Plan

## Purpose

This document sketches how the current policy-tool stack can grow into a set of independent RDP model services that feed shared frontend layers and can later interact through scenario models.

The current `policy-tool-backend` contains early model behavior and scenario logic, including residential load behavior and congestion-related calculation. The target architecture treats it as the frontend-facing orchestration API, while model calculations move into independent services that can also run standalone during development.

## Current Starting Point

- `policy-tool-frontend` serves the dashboard at `/dashboard`.
- `policy-tool-backend` serves the API at `/policy-api`.
- The backend currently exposes `GET /simulate/{pc6}` and writes `pc6_profile_<PC6>.csv` into a shared processed-data volume.
- The frontend fetches the simulation endpoint, then reads the generated CSV from `/dashboard/processed`.
- The current backend mixes orchestration, consumption-model behavior, congestion-model behavior, local file ingestion, layer publication, and some direct external data fetching. Functionally, this combined backend is the first model already visible through the current dashboard/GeoServer path. That is acceptable for the prototype, but should be split into explicit ownership boundaries as new models are added.

## Epic 1 Decisions: Shared Data And Layer Contract

The first implementation should be standards-aware but not standards-heavy. The priority is to keep a working end-to-end map and scenario flow, then upgrade the metadata and API surfaces toward the Geonovum/NLDT direction as the model contracts stabilize.

Decisions made so far:

- Scenario calculations use a 15-minute time step, expressed as `PT15M` in metadata.
- Layers may keep their native spatial resolution. Consumption can use PC6 or CBS buurt areas, public EV chargers can use point locations, PV can use CBS buurt areas, and grid assets can use exact grid geometries where available.
- The first PV capacity layer uses CBS buurt polygons and `pv_capacity_kwp` as the canonical numeric attribute, expressed in kWp.
- `pv_capacity_kwp` is model-estimated PV capacity derived from open available source datasets, including measurement-based inputs that the PV model combines. It should not be presented as a raw measured register value.
- The first PV layer metadata should expose the estimate method and provenance with fields such as `capacity_method: model_estimated`, `source_names`, `source_last_updated`, `model_version`, and `lineage_summary`.
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
- A coarse quantitative measure called `datacompleetheid` should be available for every layer, mapping, profile, and scenario result where possible. The MVP uses four integer bins from 0 to 3.
- `datacompleetheid` is not a precise accuracy score. It is a simple user-facing completeness indicator that can later be backed by richer metadata quality rules.
- Layer versioning starts with timestamp metadata: `last_updated` on layers/outputs/mappings and `source_last_updated` for dependencies.
- The professional target is event-based update triggers, but refresh work should be incremental: update only affected mapping rows and derived results when changed feature ids can be identified.
- Scenario result storage follows a hybrid maturity path: MVP writes result metadata and profile files, publishes map-visible result layers through GeoServer, and later moves the canonical result store to PostGIS/Timescale.
- API responses should return result metadata and links to outputs, not assume every scenario result can be returned inline as one JSON response.
- The frontend uses a layer registry driven by layer metadata. The MVP can use a static `layers.json` or `GET /layers`; later versions should evolve toward catalogue-style discovery.
- Layer registry records should include layer identity, group/model, GeoServer layer name, geometry type, selectable feature type, `datacompleetheid`, freshness/stale state, and available actions such as profile or scenario run.
- Model containers should own domain calculations and expose APIs. The policy-tool backend should own frontend-facing orchestration, not long-term model logic.
- The current policy-tool backend is treated as the phase-1 reference model: a combined consumption-and-congestion prototype that is already exposed through the current dashboard/GeoServer path.
- Before ripping that combined backend apart, PV is the first new standalone model layer to add.
- Current residential-load behavior can stay in the policy-tool backend during transition, but should move into or be wrapped as `consumption-model-service` over time.
- Current congestion-related calculation in the policy-tool backend needs a follow-up split into `congestion-model-service`, which owns profile aggregation, grid assignment consumption, and congestion indicators.
- External data/API fetching moves toward shared crawler/data services for integrated RDP, while standalone model development may keep isolated input adapters and caches.
- GeoServer publishing should use a shared layer-publishing path instead of every model implementing its own publishing logic.
- The main frontend should call the policy-tool backend; direct model API calls remain useful for standalone development and testing.
- Implementation order is phase-based and incremental: first use the current combined policy-tool backend as the already-working reference model layer, then add each new model as a GeoServer layer one model at a time, checking the whole stack after each model, then connect model outputs to transformer profiles, then add scenario UI controls, then harden into the professional standards-aligned setup.
- After the current combined consumption/congestion layer path is used as the reference pattern, PV is the first new model layer to integrate in phase 1.
- Development uses a long-lived `dev` integration branch. Feature/fix branches should open PRs into `dev`; `main` and the actual server receive releases only after a separate release decision.
- Everything should keep functioning at all times. Once phase 1 starts, every model-layer PR into `dev` should run tests/smoke checks that protect dashboard, API, GeoServer layer, and layer-registry behavior before the next model is added.

Geonovum/NLDT interpretation:

- Use NEN 3610/MIM-style thinking for geo-object concepts and relationships.
- Use OGC services for spatial publication. WMS/WFS are acceptable during the transition, while OGC API Features/Tiles are the intended modern direction.
- Use ISO 19115/19119 and DCAT-AP-NL concepts for dataset and service metadata, but do not require full catalogue publication in the first prototype.
- Use observation/time-series language for profiles so the system can later align with SensorThings-style APIs.
- Keep spatial features and observation/time-series data conceptually separate, even when the prototype stores them in simple files. This leaves room for SensorThings and OGC API Joins later without blocking the first working version.
- Treat the current policy-tool backend as a pragmatic combined prototype: it already blends consumption, congestion, and orchestration behavior into one working component and publishes a useful layer. This fits the NLDT guardrails of working from use cases, using what is reliable today, avoiding pre-optimization, and moving toward loosely coupled API-speaking components over time; OGC API Processes can be a later alignment target for standardized process execution, not an MVP requirement.
- Document APIs with OpenAPI once the route shapes stabilize, matching the Dutch API Strategy direction. Geo-oriented APIs should stay compatible with the geospatial API strategy and OGC API Features direction where relevant.
- OGC API Processes supports synchronous and asynchronous execution patterns with job/status/result concepts. The MVP should borrow those concepts lightly without implementing the full standard yet.
- Scenario request fields should use standards-friendly names and explicit units, identifiers, geometry references, and output links so they can later be expressed as JSON Schema/OpenAPI, catalogue metadata, or OGC API Processes execution inputs.
- Prefer references to existing geo-objects over copying geometry into scenario requests. This aligns with NEN 3610/MIM-style geo-object identity, OGC API Features-style feature access, and later OGC API Joins for connecting tabular/profile data to geo-objects.
- Store grid assignments as relationships between source geo-objects/profiles and grid geo-objects, with method, distance, confidence, provenance, and source versions. This keeps the mapping standards-friendly and auditable instead of hiding it inside model code.
- Keep `datacompleetheid` as a lightweight front-end indicator, but preserve enough provenance, actuality, completeness, accuracy, and lineage metadata to map later to ISO 19115/19119 metadata quality elements, DCAT-AP-NL catalogue records, and NLDT trustworthiness expectations.
- Treat timestamps and source dependency versions as lightweight actuality/provenance metadata. Later event triggers should complement catalogue metadata and service links rather than replace them.
- Publish map-visible scenario result geometries through GeoServer/WMS/WFS first, while keeping the design ready for OGC API Features/Tiles and catalogue records through DCAT-AP-NL or OGC API Records later.
- Treat the frontend registry as the MVP discovery layer. It should use the same identifiers and metadata fields that can later be exposed through OGC API Records, DCAT-AP-NL catalogue entries, or OGC API Features/Tiles service metadata.
- Keep ownership aligned with NLDT building blocks: Data & Sensors for crawler/ingestion, Rekenmodellen for model containers, Visualisatie for the frontend, and Fundament for catalogue/IAM/metadata concerns. Components should remain loosely coupled and API-speaking.
- Keep the delivery workflow close to the Geonovum OGC API Testbed pattern: separate stable and sandbox/integration flows, use GitHub PR/workflow checks, and redeploy/test only affected services where possible.
- Treat early JSON records as a pragmatic bridge toward standards, not as a private replacement for standards.

## Target Shape

Model services should follow this pattern:

```text
input adapter -> model core -> output adapter
```

The model core should be independent from RDP infrastructure. Input and output adapters decide whether the model reads local files, direct API/cache data, Redis streams, Timescale/PostGIS tables, or writes file outputs, API responses, and GeoServer/PostGIS layers.

Planned services:

- `policy-tool-backend`: frontend-facing scenario/orchestration API. It coordinates calls to model APIs and may temporarily keep current residential-load and congestion-related logic during migration.
- `consumption-model-service`: generates residential, commercial, and industrial demand layers and profiles. The current residential-load logic should move here or be wrapped as this service over time.
- `pv-map-service`: first publishes model-estimated PV capacity at CBS buurt resolution using `pv_capacity_kwp`; future versions can add PV potential, production profiles, and scenario-derived generation layers.
- `ev-charger-model-service`: generates public EV charger location layers and charging demand profiles.
- `grid-map-service`: publishes grid topology, asset, capacity, and headroom layers. It should not own load/PV/EV-to-grid assignment logic.
- `congestion-model-service`: consumes model profiles, grid layers, and the stored grid-assignment mapping to aggregate profiles and calculate congestion indicators. Current congestion-related calculation in the policy-tool backend should move here in a follow-up story.
- `other-model-service`: placeholder for later independent model services that publish layers/profiles through the same contract.

If orchestration grows beyond simple scenario coordination, it can later be split out of the policy-tool backend. For the next versions, keeping orchestration in the policy-tool backend gives the frontend one stable API to call.

## Model Ownership And Boundaries

The system should stay split by responsibility so new models do not turn the policy-tool backend into one large mixed service.

Ownership boundaries:

| Component | Owns | Should not own long term |
| --- | --- | --- |
| `policy-tool-backend` | Frontend-facing API, scenario orchestration, model calls, result links, auth/routing glue where needed | Domain calculations for consumption, PV, EV, grid, or congestion |
| `consumption-model-service` | Residential, commercial, and industrial consumption calculations and profiles | Frontend orchestration or grid congestion logic |
| `pv-map-service` | Model-estimated PV capacity first, later PV potential/production calculations, layers, and profiles | Scenario orchestration or grid congestion logic |
| `ev-charger-model-service` | EV charger layer/profile logic | Scenario orchestration or grid congestion logic |
| `grid-map-service` | Grid topology/assets/capacity/headroom publication | Load/PV/EV-to-grid assignment or congestion calculations |
| `congestion-model-service` | Grid assignment consumption, profile aggregation, transformer/headroom/congestion indicators | Publishing the raw grid as source data or owning unrelated model logic |
| RDP crawler/data services | Shared external API ingestion, cached source data, reusable Postgres/PostGIS/Timescale inputs | Model-specific scenario calculations |
| Layer publisher | Shared path to GeoServer/layer publication | Domain model calculations |
| Frontend | Map UI, layer registry rendering, scenario controls | Direct orchestration across all model containers in the main app |

Migration note:

The current policy-tool backend may keep existing calculations while the MVP is being stabilized. Follow-up work should identify which current code belongs to orchestration, which belongs to `consumption-model-service`, and which belongs to `congestion-model-service`. The congestion split is especially important because congestion calculation is currently present in the policy-tool backend but belongs in the congestion model target boundary.

MVP behavior:

- keep the policy-tool backend as the single API the frontend calls;
- keep standalone model APIs callable directly for development and debugging;
- isolate any direct external data fetches behind input adapters;
- produce model outputs and metadata from model services, then publish map layers through the shared layer-publishing path;
- avoid adding new domain calculations to the policy-tool backend unless they are explicitly temporary migration code.

Geonovum alignment guardrail:

This mirrors the NLDT building-block split: Data & Sensors, Rekenmodellen, Visualisatie, and Fundament. The MVP can stay pragmatic, but each component should remain containerable, developer-friendly, loosely coupled, and reachable through APIs.

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

Similarly, GeoServer publication should move through a shared layer-publishing path rather than being reimplemented inside every model service.

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
    "confidence": "medium",
    "datacompleetheid": 2
  },
  "provenance": {
    "source_layer_version": "2026-07-28",
    "source_layer_last_updated": "2026-07-28T10:30:00Z",
    "grid_layer_version": "2026-07-28",
    "grid_layer_last_updated": "2026-07-27T16:00:00Z",
    "updated_at": "2026-07-28T00:00:00Z"
  }
}
```

MVP behavior:

- refresh affected mapping rows when a source layer/profile layer changes and changed feature ids are known;
- refresh assignments affected by changed grid components when the grid layer changes;
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

## Datacompleetheid

`datacompleetheid` is the first user-facing data quality measure. It should be coarse, quantitative, and easy to display on the map. It answers: how complete is the data behind this layer, mapping, profile, or scenario result?

MVP bins:

| Value | Label | Meaning | Typical UI |
| --- | --- | --- | --- |
| `0` | `onbekend` | Completeness is unknown or cannot be assessed yet. | grey |
| `1` | `laag` | Important source data is missing; result is mainly indicative. | red |
| `2` | `middel` | Enough data exists for exploration, but visible gaps or coarse assumptions remain. | amber |
| `3` | `hoog` | Most expected data is present for the selected purpose and resolution. | green |

Rules for the first version:

- every layer metadata record should include `datacompleetheid` when possible;
- grid-assignment mappings should include `datacompleetheid` so users can see whether profile-to-grid coupling is strong or approximate;
- scenario results should expose an overall `datacompleetheid`, using the most conservative contributing score by default;
- keep the bin calculation simple and documented per model or layer;
- if a score is manually assigned during prototyping, record that in provenance so it is not mistaken for an automated quality calculation.

Professional target:

Later versions can add richer quality dimensions such as accuracy, actuality, lineage, validation status, and uncertainty. `datacompleetheid` should remain a simple front-end summary, while the underlying metadata can grow toward ISO metadata quality elements, DCAT-AP-NL records, and NLDT trustworthiness requirements.

## Layer Versions And Update Triggers

The first version should detect layer changes with timestamps. Every layer, output, and mapping should expose `last_updated`. Derived records should also keep the timestamps of the source layers they depend on.

MVP metadata shape:

```json
{
  "layer_id": "https://reformers01.ewi.tudelft.nl/id/layer/ev/public-chargers",
  "last_updated": "2026-07-28T10:30:00Z",
  "source_last_updated": {
    "ev_public_chargers": "2026-07-28T10:30:00Z",
    "grid_lv_components": "2026-07-27T16:00:00Z"
  }
}
```

MVP refresh behavior:

- when a source layer timestamp changes, mark dependent mappings/results as potentially stale;
- if the update contains changed feature ids, refresh only those mapping rows and any derived congestion results that depend on them;
- if changed feature ids are not available, fall back to refreshing the affected layer/model mapping, not the entire system;
- if the grid layer changes, refresh assignments for features near changed grid components where possible; only rebuild the full mapping when the change scope is unknown;
- after refresh, update `last_updated`, source timestamps, provenance, and `datacompleetheid`.

This keeps the first version practical while avoiding unnecessary full recomputation whenever a small layer update arrives.

Professional target:

- emit events such as `layer.updated`, `features.updated`, `mapping.stale`, `mapping.updated`, and `scenario.outputs.stale`;
- include changed feature ids or bounding boxes in update events whenever possible;
- maintain a dependency graph so the congestion model knows which mappings and scenario outputs depend on which layers/features;
- add retries, audit logs, and eventually content hashes for reproducibility where needed;
- expose update state to the frontend so users can see whether a layer/result is current, stale, refreshing, or failed.

Geonovum alignment guardrail:

- timestamps support basic actuality metadata;
- dependency timestamps and event history support provenance and lineage;
- later catalogue records can expose update frequency, modified timestamps, lineage, and service links through DCAT-AP-NL, ISO metadata, or OGC API Records;
- incremental refresh should preserve stable geo-object identifiers so joins and derived mappings remain explainable.

## Scenario Result Storage

Scenario results are not one object. A result can include map layers, profiles, summary values, provenance, `datacompleetheid`, and links back to the model outputs and source layer versions that produced it.

MVP storage path:

- write one scenario result metadata JSON record per run;
- write profile outputs as CSV or simple files where that keeps standalone development fast;
- publish map-visible geometries through GeoServer, using GeoJSON/PostGIS as the practical bridge depending on what the service can write at that stage;
- return output metadata and links from the policy-tool backend, rather than embedding all raw profile and map data in the API response;
- include `run_id`, input summary, output links, `datacompleetheid`, `last_updated`, source dependency timestamps, and stale/current state.

MVP result metadata shape:

```json
{
  "run_id": "https://reformers01.ewi.tudelft.nl/id/run/scenario/local-dev-001",
  "scenario_name": "High PV and EV adoption",
  "status": "completed",
  "last_updated": "2026-07-28T11:00:00Z",
  "source_last_updated": {
    "consumption": "2026-07-28T10:00:00Z",
    "pv": "2026-07-28T10:15:00Z",
    "ev": "2026-07-28T10:30:00Z",
    "grid_assignment": "2026-07-28T10:45:00Z"
  },
  "outputs": {
    "layers": [
      {
        "id": "https://reformers01.ewi.tudelft.nl/id/layer/scenario/congestion/local-dev-001",
        "geoserver_layer": "rdp:scenario_congestion_local_dev_001"
      }
    ],
    "profiles": [
      {
        "id": "https://reformers01.ewi.tudelft.nl/id/time-series/scenario/local-dev-001/transformer-load",
        "href": "/dashboard/processed/scenario_local_dev_001_transformer_load.csv"
      }
    ],
    "summary": {
      "worst_transformer_id": "transformer-987",
      "overload_hours": 3.25
    }
  },
  "data_quality": {
    "datacompleetheid": 2,
    "datacompleetheid_label": "middel"
  }
}
```

Integrated RDP target:

- store scenario metadata, summary outputs, and run records in Postgres;
- store time-series outputs in Timescale;
- store map geometries and derived spatial outputs in PostGIS;
- publish map layers from PostGIS through GeoServer first, and later through OGC API Features/Tiles where useful;
- keep file exports as optional downloads/debug artifacts, not as the canonical source of truth.

Professional target:

- API responses return links and metadata for result resources;
- catalogue-style metadata can expose scenario outputs through DCAT-AP-NL, ISO metadata, or OGC API Records;
- result records keep lineage from scenario inputs, model versions, source layer timestamps, grid assignments, and output artifacts;
- stale/current/refreshing/failed state is visible to both API clients and the frontend.

Geonovum alignment guardrail:

- use GeoServer/WMS/WFS as the practical current geospatial publication path;
- keep the path open to OGC API Features and OGC API Tiles for modern standards-based feature and tile access;
- keep result metadata rich enough to become catalogue/search metadata later;
- keep profiles separate from spatial features so time-series access can move toward SensorThings-style APIs if needed.

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
  "version": "2026-07-28",
  "last_updated": "2026-07-28T00:00:00Z",
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
    "datacompleetheid": 3,
    "datacompleetheid_label": "hoog",
    "confidence": "medium",
    "estimated_values": true
  }
}
```

The exact schema can evolve, but every layer should identify:

- model and run identity;
- geometry type and spatial level;
- available metrics and units;
- time handling;
- data source location;
- version, update timestamps, and source dependency timestamps;
- `datacompleetheid`, data quality, and provenance;
- optional style hints for the frontend.

This record is deliberately smaller than DCAT-AP-NL or ISO 19115/19119 metadata. Those standards should influence names, identifiers, provenance, quality, and service links, but the first implementation only needs the fields required to make the dashboard work and remain upgradeable.

## Frontend Direction

The frontend should evolve from hardcoded layer radio buttons into a layer registry. In the MVP, that registry can be a static JSON file or `GET /layers` response. The important change is that the frontend reads layer metadata and builds the layer UI from that metadata.

MVP registry record:

```json
{
  "id": "https://reformers01.ewi.tudelft.nl/id/layer/consumption/residential-pc6",
  "local_id": "layer:consumption:residential-pc6",
  "title": "Residential Load by PC6",
  "group": "consumption",
  "model_id": "https://reformers01.ewi.tudelft.nl/id/model/consumption",
  "geoserver_layer": "rdp:residential_pc6",
  "geometry_type": "polygon",
  "selectable_feature_type": "pc6",
  "style": {
    "legend": "residential_load",
    "default_visible": true
  },
  "actions": {
    "show_profile": true,
    "scenario_input": true
  },
  "data_quality": {
    "datacompleetheid": 3,
    "datacompleetheid_label": "hoog"
  },
  "last_updated": "2026-07-28T10:00:00Z",
  "state": "current"
}
```

MVP behavior:

- load available layers from static metadata records or `GET /layers` on the policy-tool backend;
- group layers by model: consumption, PV, EV, grid, scenarios;
- allow multiple overlays when they make sense;
- show `datacompleetheid`, freshness, and stale/current/refreshing/failed state per layer/result;
- use registry metadata to decide whether a feature can show a profile, be selected for a scenario, or display a scenario output;
- request scenario runs through the policy-tool backend when a registry action says a layer/feature can be used as scenario input;
- render output metadata records rather than assuming every model writes one specific CSV filename.

Maturity path:

- MVP: static `layers.json` or simple `GET /layers` JSON from the policy-tool backend;
- Next: merge static layers, model outputs, and scenario result layers into one registry response;
- Professional target: catalogue-style discovery through OGC API Records/DCAT-AP-NL-style metadata, with geospatial access through GeoServer now and OGC API Features/Tiles later.

This keeps the dashboard usable while avoiding a future pileup of model-specific JavaScript branches.

## Implementation Order And Branch Strategy

The implementation should prioritize visible, working map layers before deeper model coupling. The system should stay functional at every step, with PR checks becoming stricter as soon as the first layer milestone is reached.

Implementation phases:

1. GeoServer-visible model layers: make each model publish its first useful output as a GeoServer-visible layer, similar to the current policy-tool example. This phase should be delivered model by model: integrate one model layer, verify that the existing dashboard, API, and GeoServer setup still work, then move to the next model. This includes consumption, PV, EV, grid, and later other model layers. At this stage, models may still be simple and standalone.
2. Transformer profile coupling: connect consumption, PV, EV, grid, and other outputs through the congestion model so profiles can be aggregated at LV/MV transformers and later MV/HV transformers.
3. Scenario UI: add sliders, buttons, scenario requests, run metadata, and scenario result layers/profiles on top of the working model/layer foundation.
4. Professional setup: harden the architecture toward PostGIS/Timescale canonical stores, event-based triggers, richer tests, OpenAPI documentation, catalogue-style metadata, and OGC API/Geonovum-aligned publication where useful.

Branching policy:

- use a long-lived `dev` branch as the integration branch for active development;
- create feature/fix branches from `dev` and open PRs back into `dev`; do not develop directly on `main`;
- only merge/release from `dev` to `main` after an explicit release decision;
- deployment to the actual server is a separate decision and may happen after phase 1, after phase 2, or later;
- use `dev` for full integration tests before anything is shipped to `main` or the live server;
- keep branch names informative, such as `feature/...` or `fix/...`.

PR/testing guardrail:

After phase 1 starts landing, every model-layer PR into `dev` should include automated checks that prove the existing app still works before adding the next model. The first useful checks are:

- Docker Compose configuration validation;
- policy-tool backend health/API smoke tests;
- frontend/dashboard smoke test;
- GeoServer reachability and expected layer publication checks;
- layer registry schema/metadata validation;
- basic `datacompleetheid`, `last_updated`, and output-link validation.

Geonovum alignment guardrail:

This is consistent with NLDT guardrails: work from use cases, avoid pre-optimization, keep components containerable and API-speaking, and use the best reliable setup available today. It also mirrors the Geonovum OGC API Testbed idea of stable versus sandbox/integration environments and GitHub workflow based maintenance.

## Near-Term Steps

1. Create or confirm the long-lived `dev` branch from the cleaned deployed base once the cleanup base is agreed.
2. Start phase 1 by treating the current combined policy-tool backend as the reference GeoServer-visible model: consumption plus congestion in one working service.
3. Add the first new GeoServer-visible model layer for model-estimated PV capacity in its own PR, using CBS buurt polygons and `pv_capacity_kwp`, with smoke tests proving the existing stack still works.
4. Repeat the model-layer PR pattern for EV chargers, grid, and later other layers, even if their first outputs are simple standalone datasets.
5. Add a frontend layer registry backed by static `layers.json` or `GET /layers`, then use it to render available layers and scenario outputs.
6. Add `datacompleetheid`, `last_updated`, and basic metadata to those layer records.
7. Add PR checks for `dev` that validate Docker Compose config, dashboard/API reachability, GeoServer layers, and layer registry metadata.
8. Inventory current policy-tool backend code into orchestration, consumption-model, congestion-model, data-ingestion, and layer-publishing responsibilities, but do this as preparation for the later split rather than before the PV layer.
9. Keep the current policy-tool backend name in code for now, and let it remain the combined model/orchestration component until PV is working as the first new model layer.
10. Start phase 2 by extracting or wrapping current policy-tool backend congestion calculation into `congestion-model-service`.
11. Add the first congestion-model grid-assignment mapping using closest Euclidean LV component, with incremental refresh on layer updates.
12. Add transformer-level profile aggregation outputs and metadata links.
13. Start phase 3 by adding scenario sliders/buttons and `POST /scenarios` flow once phase 2 outputs are stable enough.
14. Add scenario result metadata records and output links, with file/GeoServer outputs for MVP and PostGIS/Timescale as the integration target.
15. Promote shared external API connections into crawler/ingestion services when the data contract stabilizes.
16. Start phase 4 hardening only after the working map/model/scenario flow is stable in `dev`.

## Open Questions

- What exact branch/commit should be used to create the long-lived `dev` branch?
- Which phase is the first candidate for release from `dev` to `main` and the live server: after GeoServer-visible layers, after transformer profile coupling, or later?
- Which smoke tests are mandatory before each model-layer PR can merge into `dev`?
- Which open source datasets feed the first `pv_capacity_kwp` estimate, and what short `lineage_summary` should explain how measurement-based inputs are combined?

- Which current policy-tool backend functions are orchestration, consumption model logic, congestion model logic, data ingestion, or layer publishing?
- What is the smallest first `congestion-model-service` extraction: wrap existing backend calculation behind an internal API, move the code into a new container, or start with a fresh service contract?
- Which direct model API calls should remain supported for standalone development even though the main frontend uses the policy-tool backend?
- Should the first layer registry be served as static `layers.json`, from `GET /layers` in the policy-tool backend, or both?
- Which registry fields are mandatory for the first frontend UI: title, group, GeoServer layer, geometry type, selectable feature type, `datacompleetheid`, freshness, actions, style, or legend?
- Which scenario outputs must be shown as GeoServer layers in the MVP, and which can remain metadata/profile links only?
- What retention policy should apply to scenario result files once PostGIS/Timescale becomes the canonical store?
- Which layer update jobs can report changed feature ids or bounding boxes, and which only report a changed timestamp?
- What dependency graph does the congestion model need to refresh only affected mappings and scenario outputs?
- What exact model/layer-specific rules determine `datacompleetheid` bins 0-3 for consumption, PV, EV, grid, mapping, and scenario results?
- What is the first shared Timescale/PostGIS schema for model profiles once CSV output is no longer enough?
- Which spatial selection types should each model/layer support first: CBS buurt, PC6, building, EV charger, grid asset, feeder, transformer area, or mixed?
- For area features with multiple LV components, which congestion-model allocation rule should be used first: nearest component, centroid distance, spatial overlap, address/building counts, connection data, proportional shares, or another rule?
- Once run persistence is added, how long should scenario history and output artifacts be retained?
- When should orchestration move out of the policy-tool backend into a dedicated service, if ever?
- Which scenario parameters are generic enough for the policy-tool backend contract, and which should stay inside model-specific parameter blocks?
- Which external sources belong in the RDP crawler immediately, and which can remain standalone-only while prototyping?
