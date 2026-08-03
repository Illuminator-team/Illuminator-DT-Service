# Future Model Integration Plan

## Purpose

This document sketches how the current policy-tool stack can grow into a set of independent RDP model services that feed shared frontend layers and can later interact through scenario models.

The current `policy-tool-backend` contains early residential-load, electrification, PV, and net grid import/export profile behavior behind a small API. Transformer-level congestion calculation is a target capability rather than a current implementation. The target architecture keeps the backend as the frontend-facing orchestration API while model calculations move into independent services that can also run standalone during development.

## Current Starting Point

- `policy-tool-frontend` serves the dashboard at `/dashboard`.
- `policy-tool-backend` serves the API at `/policy-api`.
- The backend currently exposes `GET /simulate/{pc6}` and writes `pc6_profile_<PC6>.csv` into a shared processed-data volume.
- The frontend fetches the simulation endpoint, then reads the generated CSV from `/dashboard/processed`.
- The dashboard currently loads the checked-in `policy-tool-frontend/data/alkmaar_energy_map.geojson` directly into Leaflet. The current PC6 energy layer is not loaded from PostGIS or GeoServer.
- That GeoJSON was produced offline by `policy-tool-frontend/helper scripts/layer_maker.py`, which joins PDOK PC6 polygons to energy attributes.
- The current backend mixes API/orchestration glue, consumption/heat/PV profile behavior, local file ingestion, and direct PVGIS fetching. It does not currently publish the PC6 layer to GeoServer or calculate transformer congestion.
- The existing RDP `layer-publisher` and live GeoServer currently publish only the separate tutorial `rdp:solar_panel_layer`; they are not the publication path for the policy-tool PC6 map.

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
- Source dataset names, source versions, and detailed PV `lineage_summary` text can be finalized from the model repo once the PV model/API is finished; the architecture decision now is to reserve and validate those metadata fields, not guess their final values early.
- Profiles reuse the existing RDP persistence path as their canonical store: model services publish standard Redis output streams, `data-sync-service` resolves `data_points` and writes values to `forecasts` in Timescale/Postgres. PostGIS stores spatial outputs; CSV is only an optional export/debug artifact.
- Model-generated consumption, PV-production, EV, and congestion profiles belong in the existing `forecasts` structure; genuinely observed source values belong in `measurements`. Do not create parallel profile-value tables unless an evidenced requirement cannot fit the RDP contract.
- Reuse the existing RDP `data_points`/`forecasts` contract, API metadata, and services before extending them. Treat fit assessment as an implementation compatibility check: document and test each required model-run, stable-feature, provenance, and quality field against the complete existing contract. Add only the smallest named and versioned metadata/link extension for a demonstrated gap; do not overload unrelated columns or create speculative parallel tables.
- All model services expose APIs and can be called independently. The policy-tool frontend calls the policy-tool backend, and the policy-tool backend orchestrates calls to consumption, PV, EV, grid, and later model APIs for scenario workflows.
- The minimum model API contract is `GET /`, `GET /metadata`, `GET /layers`, `POST /runs`, `GET /runs/{run_id}`, and `GET /outputs/{output_id}`. These endpoints remain directly callable in both standalone and integrated modes. Models may add domain-specific endpoints, and legacy endpoints may remain during transition, but the main frontend does not depend on them.
- Model and scenario runs are synchronous in the first working version, but every run still gets a `run_id`, status, timestamps, inputs, output links, and metadata so the same contract can become asynchronous later.
- Scenario execution uses one JSON request to the policy-tool backend, with time settings, layer-native spatial selections, per-model parameter blocks, and requested outputs. The MVP schema should stay simple but map cleanly to OpenAPI and future OGC API Processes inputs/outputs.
- There is no single canonical scenario area. Spatial selections use stable layer-native `layer_id` and `feature_id` references, with geometry type, selectable feature type, and CRS supplied by layer metadata. The first types are CBS buurt for PV, an individual public charger for EV, and an individual grid asset or transformer for grid/congestion workflows. The renewed consumption model declares whether its first selectable layer uses PC6 or CBS buurt. Custom geometry and additional types can be added later without changing the common reference shape.
- The grid model owns the complete grid-connection calculation and its assignment records for points, areas, profiles, and grid components. Its output is authoritative for downstream services; this integration does not prescribe or reimplement the connection algorithm. Integrated records live in a grid-owned table in the existing RDP PostGIS database.
- In the MVP, the shared layer publisher calls the grid model's assignment-refresh API after successfully publishing a changed source layer. Later this direct call should become a Redis layer-update event without changing assignment ownership.
- The congestion model consumes grid-assignment records for profile aggregation and congestion calculations; it does not implement the spatial matching algorithm.
- Point and area connection rules, including cases with multiple LV components inside CBS buurten or PC6 areas, remain internal to the grid model. The congestion model consumes the returned assignment or connection result without choosing the rule.
- Each metadata record should be designed so it can later map to DCAT-AP-NL, ISO 19115/19119, OGC API Records, and SensorThings concepts.
- A coarse qualitative measure called `datacompleetheid` should be available for every layer, mapping, profile, and scenario result where possible. The MVP uses four ordered integer levels from 0 to 3.
- `datacompleetheid` is a simple user-facing trust indicator that summarizes data availability, expected accuracy, and reliance on assumptions. It is not a calculated percentage or a substitute for the richer quality metadata that should support it.
- The producing model owns its model-specific `datacompleetheid` calculation and thresholds. For the PV capacity layer, the PV model agent defines, documents, tests, and versions the rule in the PV model repo; the integration layer validates and displays the result without recalculating it.
- The legacy baseline PC6 layer is a temporary ownership exception because no standalone producing model exists yet: the current policy-tool component/repo assigns qualitative `datacompleetheid: 2` with label `redelijke betrouwbaarheid` and method version `legacy-pc6-layer-qualitative-v1`. This is one layer-level assessment inherited by every PC6 feature for display, not a feature-specific calculation. Its evidence summary states that the layer combines real/open annual energy and building data with standard load profiles, enrichment, estimates, and assumptions. The renewed consumption model replaces this temporary assessment with its own documented output-level or feature-level method.
- The shared publisher validates that the baseline score, label, method version, timestamp, and evidence summary conform to the integration contract; it does not calculate or reinterpret the score.
- Layer versioning starts with timestamp metadata: `last_updated` on layers/outputs/mappings and `source_last_updated` for dependencies.
- Layer change detection should use a shared lightweight diff checker in the crawler/ingestion/layer-publishing path. Models may report their own changed feature ids when available, but the shared diff checker is the fallback that compares previous and current published layer versions by stable feature id and feature hash.
- Phase 1 only requires stable feature ids, layer version/update metadata, and room for optional change manifests; incremental congestion recalculation consumes these manifests later and is not required for the first PV layer PR.
- Model metadata should be kept current by making the model repo the source of truth: model-owned metadata manifests feed `GET /metadata`, `GET /layers`, run records, and output records, while CI checks prevent required metadata from drifting when model code or source-data configuration changes.
- The MVP manifest format is one combined `model-manifest.json` per model repo. It can be split into separate model, layer, source, and output records later if the manifest becomes too large or if catalogue publication needs a different structure.
- The first PV PR should use a rich manifest, not a minimal placeholder. Required sections should already cover model identity/versioning, ownership/contact, model purpose, spatial and temporal scope, inputs/source provenance, output layers, attribute schema, units, CRS, GeoServer publication metadata, `datacompleetheid` rules, update/freshness metadata, API links, and run/output snapshot behavior.
- Rich manifest fields are allowed to evolve. Fields whose final values depend on the finished model repo may be marked as `provisional`, `unknown`, or `to_be_confirmed`, but the field and its owner must exist from the first PV PR.
- For the first PV PR, the geospatial output artifact must have a concrete CRS and be GeoServer-ready. Concrete fields include output format/path or table, CRS, geometry type, required attributes, and publication status.
- GeoServer publication details such as workspace, final layer name, WMS/WFS URLs, style, and legend may be provisional when publication wiring is not finished yet, but the manifest must state the intended values, owner, and whether the layer is `ready_for_publication` or already `published`.
- Default GeoServer styling is acceptable for the first PV PR. A custom SLD style and polished legend are not required before merge, but the manifest should expose style metadata such as `style_status: default_geoserver` so the dashboard can later replace it with a proper PV capacity style.
- The professional target is event-based update triggers, but refresh work should be incremental: update only affected mapping rows and derived results when changed feature ids can be identified.
- A generic dependency knowledge graph is a possible far-future professional target, not a phase-1 or phase-2 requirement. The first implementation should use an ordinary grid-owned assignment table and congestion-owned aggregation/dependency records keyed by stable feature and grid-object identifiers.
- A future data space and a future knowledge graph are related but separate concerns: the data space governs trusted sharing between independent parties, while the knowledge graph gives objects, concepts, and relationships machine-readable meaning. Adopt either only when a concrete interoperability use case justifies it.
- Preserve that upgrade path now through persistent web identifiers, explicit typed relationships, versioned provenance, metadata manifests, and standards-friendly APIs; do not require RDF, a triple store, a data-space connector, or semantic reasoning for the first working integrations.
- Initial scenario execution does not durably store run history or scenario-specific results. It returns a transient run/result envelope and keeps a storage adapter boundary plus persistence-ready identifiers and metadata fields so Postgres/Timescale/PostGIS persistence can be enabled later without changing the API contract. This exception does not change the chosen storage paths for reusable model data, published source/model layers, profiles outside scenario history, or grid assignments.
- While scenario persistence is disabled, API responses return result metadata plus inline or streamed transient outputs. The contract reserves output identifiers, persistence state, and future links without claiming that a durable result resource exists.
- Phase 1 does not include scenario result layers. Scenario output persistence and GeoServer publication remain disabled for the first scenario implementation and require a later explicit decision.
- The frontend uses a layer registry driven by layer metadata. The MVP uses `GET /layers` on the policy-tool backend as the canonical dashboard contract, with static `layers.json` only as a fallback or seed; later versions should evolve toward catalogue-style discovery.
- Layer registry records have a mandatory MVP field set: stable ids, title/description, group/model/version, metadata URL, GeoServer publication details, geometry type, selectable feature type, CRS, metrics/units, style status, actions, `datacompleetheid`, freshness state, and lightweight provenance.
- Model containers should own domain calculations and expose APIs. The policy-tool backend should own frontend-facing orchestration, not long-term model logic.
- The current policy-tool map/profile workflow is treated as the phase-1 reference behavior, but its PC6 energy layer is currently dashboard-visible through static GeoJSON rather than GeoServer-visible.
- The selected phase-1 baseline PR first migrates that existing PC6 energy layer through the shared publisher into PostGIS/GeoServer and makes GeoServer WFS the dashboard's primary layer source while retaining the static GeoJSON as a temporary fallback.
- The baseline migration must preserve the existing feature selection, sliders, policy-backend profile calculation, and chart workflow. It does not split the policy backend or change model calculations.
- After that baseline PR, PV remains the first new standalone model layer to add.
- Current residential-load behavior can stay in the policy-tool backend during transition, but it is legacy behavior that will be replaced by the independently renewed `consumption-model-service`; do not treat extraction or cleanup of the old calculation code as the target architecture.
- The intended congestion responsibility associated with the policy tool needs a follow-up `congestion-model-service`, which owns profile aggregation, grid assignment consumption, and congestion indicators. The current checked-in backend does not yet implement transformer-level congestion calculation.
- The first `congestion-model-service` vertical slice consumes aligned 15-minute model profiles and existing grid-assignment records, aggregates the profiles per transformer, and stores/exposes the resulting transformer profile with stable identifiers, units, source versions, timestamps, provenance, and `datacompleetheid`. It does not yet classify congestion or compare the profile with transformer capacity; those follow after aggregation is reliable.
- External data/API fetching moves toward shared crawler/data services for integrated RDP, while standalone model development may keep isolated input adapters and caches.
- GeoServer publishing should use a shared layer-publishing path instead of every model implementing its own publishing logic.
- The selected spatial publication path is option 3: model services own their output features and metadata, while the shared RDP layer publisher owns validation, PostGIS loading/upserting, GeoServer datastore/layer registration, and publication status.
- Reuse and adapt the existing `layer-publisher` component as a configurable shared publisher; do not add a separate PV-specific publishing service. Model containers should not receive PostGIS writer or GeoServer administration credentials.
- The selected GeoServer organization path is option 2: reuse workspace `rdp` and database `rdp_db`, introduce one generic `rdp_postgis` datastore, and publish separately named layers from it instead of reusing the PV-specific datastore or creating a workspace per model.
- The baseline PC6 layer uses PostGIS table `public.policy_tool_pc6_energy`, GeoServer layer `rdp:policy_tool_pc6_energy`, persistent layer URI `https://reformers01.ewi.tudelft.nl/id/layer/policy-tool/pc6-energy`, and feature URIs based on `https://reformers01.ewi.tudelft.nl/id/geo-object/pc6/{postcode6}`.
- For the first PV capacity integration, the model supplies CBS buurt polygons, stable `cbs_buurt_code`, `pv_capacity_kwp`, CRS, version, provenance, and `datacompleetheid`; the shared publisher turns that output into the PostGIS/GeoServer layer.
- The main frontend should call the policy-tool backend; direct model API calls remain useful for standalone development and testing.
- Implementation order is phase-based and incremental: first migrate the current static PC6 energy layer to the shared PostGIS/GeoServer publication path, then add each new model as a GeoServer layer one model at a time, checking the whole stack after each model, then connect model outputs to transformer profiles, then add scenario UI controls, then harden into the professional standards-aligned setup.
- After the PC6 baseline migration proves the shared publication pattern, PV is the first new model layer to integrate in phase 1.
- Development uses a long-lived `dev` integration branch. Feature/fix branches should open PRs into `dev`; the project owner may explicitly approve a release to `main` at any working checkpoint, independent of the implementation phase.
- The selected `dev` base is cleaned deployment commit `7273c94d65e34a7680872445b70c9556eb25c329` (`Remove policy-tool deployment credential exposure`). Planning and implementation work enters that base through PRs rather than being included when the branch is created.
- Everything should keep functioning at all times. Once phase 1 starts, every model-layer PR into `dev` should run tests/smoke checks that protect dashboard, API, GeoServer layer, and layer-registry behavior before the next model is added.
- Anything merged into `dev` should be fully working in the integration setup. For model-layer PRs, this means full end-to-end checks across model manifest, model API, output artifact, GeoServer publication, layer registry, and dashboard visibility, not metadata-only checks.
- The first PV full end-to-end smoke test should use CBS buurt `BU03610302` / `Overdie-Oost` as the stable fixture area. The test should assert that this feature exists and that `pv_capacity_kwp` is present and greater than zero, unless the PV model repo later documents a better fixture with equivalent stability.
- The PV integration smoke test should not assert an exact `pv_capacity_kwp` value for `BU03610302`; it should assert that the value is present, numeric, and greater than zero, because model-estimated values may change as source data and model logic improve.

Geonovum/NLDT interpretation:

- Use NEN 3610/MIM-style thinking for geo-object concepts and relationships.
- Use OGC services for spatial publication. WMS/WFS are acceptable during the transition, while OGC API Features/Tiles are the intended modern direction.
- Use ISO 19115/19119 and DCAT-AP-NL concepts for dataset and service metadata, but do not require full catalogue publication in the first prototype.
- Use observation/time-series language for profiles so the system can later align with SensorThings-style APIs.
- Keep spatial features and observation/time-series data conceptually separate, even when the prototype stores them in simple files. This leaves room for SensorThings and OGC API Joins later without blocking the first working version.
- Treat the current policy-tool workflow as a pragmatic prototype: it combines profile calculations, a small API, and a useful static dashboard layer. The baseline migration moves that layer behind a shared standards-based publication boundary before deeper model separation. This fits the NLDT guardrails of working from use cases, using what is reliable today, avoiding pre-optimization, and moving toward loosely coupled API-speaking components over time; OGC API Processes can be a later alignment target for standardized process execution, not an MVP requirement.
- Document APIs with OpenAPI once the route shapes stabilize, matching the Dutch API Strategy direction. Geo-oriented APIs should stay compatible with the geospatial API strategy and OGC API Features direction where relevant.
- OGC API Processes supports synchronous and asynchronous execution patterns with job/status/result concepts. The MVP should borrow those concepts lightly without implementing the full standard yet.
- Scenario request fields should use standards-friendly names and explicit units, identifiers, geometry references, and output links so they can later be expressed as JSON Schema/OpenAPI, catalogue metadata, or OGC API Processes execution inputs.
- Prefer references to existing geo-objects over copying geometry into scenario requests. This aligns with NEN 3610/MIM-style geo-object identity, OGC API Features-style feature access, and later OGC API Joins for connecting tabular/profile data to geo-objects.
- Store grid assignments as relationships between source geo-objects/profiles and grid geo-objects, with method, distance, confidence, provenance, and source versions. This keeps the mapping standards-friendly and auditable instead of hiding it inside model code.
- Keep `datacompleetheid` as a lightweight front-end indicator, but preserve enough provenance, actuality, completeness, accuracy, and lineage metadata to map later to ISO 19115/19119 metadata quality elements, DCAT-AP-NL catalogue records, and NLDT trustworthiness expectations.
- Treat timestamps and source dependency versions as lightweight actuality/provenance metadata. Later event triggers should complement catalogue metadata and service links rather than replace them.
- Treat change manifests as implementation-level provenance and update-scope metadata. They should preserve stable feature identifiers so they can later map cleanly to OGC API Features collections, catalogue metadata, and auditable lineage records.
- Keep metadata close to the source data/model code and generate as much of it as possible from model manifests, source-data configuration, run records, and API responses. This follows the Geonovum metadata direction of avoiding scattered manual metadata while preserving links between data, APIs, models, and concepts.
- When scenario outputs become map-visible in a later phase, publish those result geometries through GeoServer/WMS/WFS first, while keeping the design ready for OGC API Features/Tiles and catalogue records through DCAT-AP-NL or OGC API Records later. Phase 1 should not invent scenario result layers before there are real scenario outputs to publish.
- Treat the frontend registry as the MVP discovery layer. It should use the same identifiers and metadata fields that can later be exposed through OGC API Records, DCAT-AP-NL catalogue entries, or OGC API Features/Tiles service metadata. The mandatory MVP fields deliberately mirror Geonovum metadata basics: persistent identifiers, titles, summaries, dates, responsible model/source context, CRS, protocol/service links, and enough quality/provenance information for users to judge whether a layer is fit for purpose.
- Keep ownership aligned with NLDT building blocks: Data & Sensors for crawler/ingestion, Rekenmodellen for model containers, Visualisatie for the frontend, and Fundament for catalogue/IAM/metadata concerns. Components should remain loosely coupled and API-speaking.
- Keep the delivery workflow close to the Geonovum OGC API Testbed pattern: separate stable and sandbox/integration flows, use GitHub PR/workflow checks, and redeploy/test only affected services where possible.
- Treat early JSON records as a pragmatic bridge toward standards, not as a private replacement for standards.

## Target Shape

Model services should follow this pattern:

```text
input adapter -> model core -> output adapter
```

The model core should be independent from RDP infrastructure. Input and output adapters decide whether the model reads local files, direct API/cache data, Redis streams, or Timescale/PostGIS tables. Canonical profile and integrated spatial outputs go to Postgres/Timescale/PostGIS; APIs expose them and optional file exporters can produce development/download artifacts.

Planned services:

- `policy-tool-backend`: frontend-facing scenario/orchestration API. It coordinates calls to model APIs and may temporarily keep the legacy residential-load, electrification, and profile logic solely to preserve working behavior during migration.
- `consumption-model-service`: the renewed, independently developed source of truth for residential, commercial, and industrial demand layers and profiles. It replaces rather than wraps the legacy consumption calculation.
- `pv-map-service`: first publishes model-estimated PV capacity at CBS buurt resolution using `pv_capacity_kwp`; future versions can add PV potential, production profiles, and scenario-derived generation layers.
- `ev-charger-model-service`: generates public EV charger location layers and charging demand profiles.
- `grid-map-service`: publishes grid topology, asset, capacity, and headroom layers and owns the API, logic, and persistent records for matching external areas or points to grid components.
- `congestion-model-service`: first consumes model profiles and stored grid-assignment records to aggregate 15-minute transformer profiles; after that foundation is reliable, it also consumes capacity/headroom data and calculates congestion indicators. This capability is introduced as a separate service rather than extracted from a complete existing transformer-congestion implementation.
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
| `grid-map-service` | Grid topology/assets/capacity/headroom publication plus spatial matching and grid-assignment records in the existing RDP PostGIS database | Consumption/PV/EV calculations or congestion calculations |
| `congestion-model-service` | Grid assignment consumption, profile aggregation, transformer/headroom/congestion indicators | Publishing the raw grid, implementing spatial matching, or owning unrelated model logic |
| RDP crawler/data services | Shared external API ingestion, cached source data, reusable Postgres/PostGIS/Timescale inputs | Model-specific scenario calculations |
| Layer publisher | Shared path to GeoServer/layer publication | Domain model calculations |
| Frontend | Map UI, layer registry rendering, scenario controls | Direct orchestration across all model containers in the main app |

Migration note:

The current policy-tool backend may keep its legacy calculations while the MVP is being stabilized. The renewed `consumption-model-service` replaces the consumption calculation through its API once its output contract and integration checks are ready; the policy backend then forwards or adapts compatible requests instead of running that domain calculation locally. Existing code still needs to be inventoried to separate reusable API/orchestration behavior and ingestion concerns, but the legacy consumption implementation does not need to be migrated into the renewed service. Transformer aggregation and congestion calculation should be introduced behind the separate `congestion-model-service` boundary instead of being added to the legacy backend.

MVP behavior:

- keep the policy-tool backend as the single API the frontend calls;
- keep the shared minimum model API endpoints directly callable in standalone and integrated modes for development, testing, debugging, and independent use;
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
PROFILE_PIPELINE=redis-timescale
SPATIAL_STORE=postgis
EXPORT_BACKEND=none|file
```

Standalone mode should prioritize fast development while exercising the same storage path:

- read sample CSV/GeoJSON/Parquet files from the service directory;
- optionally read from a local cache of external API responses;
- start the minimum existing RDP storage components locally: Redis, Timescale/PostGIS, `db-scheme`, and `data-sync-service`;
- publish model output using the same Redis message shape and data-sync configuration used in RDP;
- optionally export CSV/GeoJSON files to `data/processed` or another ignored local output directory for inspection;
- expose the same HTTP API shape as the deployed service where practical.

RDP mode should prioritize integration:

- read from RDP-managed Redis streams, Timescale tables, or PostGIS tables;
- use data generated by crawler/ingestion services instead of each model calling external APIs directly;
- publish profiles to Redis and let `data-sync-service` write them with the existing restricted data-source role;
- publish spatial model outputs through the existing PostGIS and GeoServer path.

## Profile Storage Decision

Profiles should live in the database from the beginning by reusing RDP's existing data path. The repository already runs TimescaleDB/PostgreSQL with GIS support as permanent time-series storage, initializes `rdp_db` through `db-scheme`, resolves data-point identities and synchronizes Redis streams through `data-sync-service`, connects Grafana to those tables, and uses PostGIS as a GeoServer publication source. The current policy-tool profile CSV flow is therefore legacy behavior to migrate, not the target pattern for new models.

First implementation:

- model services publish profiles to a model-specific Redis stream using the existing RDP array time-series pattern;
- `data-sync-service` uses `get_or_create_data_point_id(...)` to reuse `data_points` identity and writes model-generated values to `forecasts`;
- map profile fields onto the existing contract: metric to data-point name, model to data provider, stable PC6/buurt/charger/grid identifier to location, physical unit to unit, run/generation timestamp to `fc_time`, 15-minute profile timestamps to `obs_time`, and profile values to `value`;
- use `measurements` only for observed source values, not model-estimated or scenario-generated profiles;
- keep the PV capacity layer in PostGIS/GeoServer; only later PV production time series belong in `forecasts`;
- PostGIS stores or references the geo-objects that the profiles belong to;
- profile records reference stable feature identifiers rather than embedding duplicate geometries;
- output metadata links GeoServer feature identifiers to the profile rows or profile collection;
- model APIs read profile metadata/values from the database and return metadata plus resource links;
- the frontend reads those API resources and does not depend on model-specific filenames;
- first test whether required model/run/provenance/quality metadata can be represented by the complete existing RDP schema and API metadata;
- do not overload identity fields with unrelated metadata merely to avoid a schema change; if a real gap remains, document it and add the smallest compatible extension through a versioned migration;
- test the Redis-to-Timescale path in standalone and integrated Docker Compose setups.

Standalone behavior:

- the model's standalone Docker Compose setup includes or references the existing RDP Redis, database, schema, and synchronization services;
- it exercises the same stream-to-`forecasts` path as RDP;
- optional CSV/Parquet exports may be generated for developers, tests, or downloads, but they are never the authoritative copy.

Geonovum alignment guardrail:

- treat the database schema as an internal implementation contract and expose data to consumers through documented APIs and metadata;
- keep time-series observations logically separate from geo-object geometry and connect them with stable identifiers;
- keep data at its authoritative source and avoid model-specific file copies becoming parallel sources of truth;
- reuse proven standards and platform building blocks before introducing project-specific alternatives.

Professional target:

- metadata records can be published through catalogue-style interfaces aligned with DCAT-AP-NL, ISO 19115/19119, and OGC API Records;
- time-series/observation access can move toward a SensorThings-style API where that gives real interoperability value;
- table-to-geo-object linking can align with OGC API Joins where profile or scenario data needs to be connected to existing spatial objects without duplicating geometries.

This uses the RDP components and schema already present, avoids a parallel storage design, and still keeps standalone development self-contained.

## Data Ownership

External API connections should move toward crawler/ingestion services rather than living inside every model.

Preferred flow:

```text
external source -> RDP crawler/ingestion -> Redis/Timescale/PostGIS -> model service -> layer publisher/GeoServer/API -> frontend
```

Temporary standalone exceptions are allowed for development, but any direct API call in a model should be isolated behind an input adapter so it can be replaced by an RDP data source later.

Similarly, GeoServer publication should move through a shared layer-publishing path rather than being reimplemented inside every model service.

## Shared Spatial Layer Publication

Selected path: use the existing RDP `layer-publisher` component as the one shared PostGIS/GeoServer publication boundary.

Easy explanation:

The model says what the layer contains; the publisher handles where and how it is hosted. A PV model should be able to calculate and return a valid CBS buurt dataset without knowing database passwords, GeoServer workspaces, REST configuration, or dashboard registry details. In the integrated stack, the publisher takes that output and makes it available as a reliable map layer.

Model responsibilities:

- produce or expose a complete geospatial output artifact through its output/API contract;
- provide stable feature ids, geometry, CRS, attribute schema, units, model/output version, freshness, provenance, and `datacompleetheid` metadata;
- keep standalone generation and API behavior working without requiring GeoServer;
- for the first PV layer, provide CBS buurt polygons with `cbs_buurt_code` and numeric `pv_capacity_kwp`.

Shared layer-publisher responsibilities:

- fetch/read the model output using its declared artifact or API link;
- validate required fields, stable ids, geometry type, CRS, and manifest/output consistency before publication;
- load or upsert features into the configured PostGIS table, preferably through a staging/transaction step so users never see a half-updated layer;
- ensure the configured GeoServer workspace, PostGIS datastore, feature type/layer, and default style exist;
- report `ready_for_publication`, `published`, or failed status and expose the resulting WMS/WFS links to the policy-tool layer registry;
- after a successful layer update, call the grid model's assignment-refresh API with the layer id, version, changed feature ids, and a resolvable feature-collection link;
- be idempotent so rerunning the same output version does not create duplicate tables, layers, or features;
- use restricted PostGIS-writer and GeoServer-publisher credentials held only by the publishing component.

Reuse rule:

- adapt the existing `layer-publisher` instead of creating another service;
- replace its current hardcoded single-point/`p_forecast` assumptions with configuration from model/layer metadata;
- do not use the file-only `geojson-loader` path as the canonical PV publication route because PostGIS is the selected source of truth;
- add only the configuration and validation needed by real model layers, starting with PV capacity.

First PV publication contract:

```text
source model:       pv-map-service
feature type:       cbs_buurt
feature id field:   cbs_buurt_code
required metric:    pv_capacity_kwp (kWp)
geometry:           polygon/multipolygon as declared by the model
CRS:                concrete value declared by the model manifest
canonical store:    PostGIS
publication:        GeoServer WMS/WFS
initial style:      default GeoServer style
```

Standalone and integration behavior:

- standalone model tests stop after validating the model artifact/API and metadata;
- the integrated PR test starts the publisher, PostGIS, and GeoServer and proves the layer is published end to end;
- publication failure must not corrupt or replace the last successfully published layer;
- the model remains callable even when the shared publisher or GeoServer is unavailable.

Geonovum alignment guardrail:

- keep WMS/WFS for the first working publication because GeoServer supports them and WFS GeoJSON can preserve the current Leaflet feature interactions;
- preserve stable feature ids, CRS, metadata, and object-oriented feature access so the same PostGIS data can later also be exposed through OGC API Features and OGC API Tiles;
- treat the publication interface and metadata as the interoperability contract, not the internal PostGIS table layout.

## Baseline PC6 GeoServer Migration

Selected path: option 1. Before integrating PV, migrate the existing PC6 energy map through the shared PostGIS/GeoServer publication path in a dedicated baseline PR.

Selected identifiers:

```text
database:             rdp_db
schema:               public
table:                policy_tool_pc6_energy

GeoServer workspace:  rdp
GeoServer datastore:  rdp_postgis
GeoServer layer:      policy_tool_pc6_energy
qualified layer name: rdp:policy_tool_pc6_energy

layer URI:            https://reformers01.ewi.tudelft.nl/id/layer/policy-tool/pc6-energy
feature URI template: https://reformers01.ewi.tudelft.nl/id/geo-object/pc6/{postcode6}
```

The workspace and public URI namespace express stable ownership and meaning. The PostGIS schema/table and GeoServer datastore are implementation details: they may be reorganized during later hardening without changing the layer URI, feature URI template, or externally advertised layer contract.

GeoServer should connect through `rdp_postgis` using a restricted read-only database role. The shared publisher uses a separate restricted writer role for validated loads/upserts; model containers receive neither GeoServer administration credentials nor general PostGIS write access.

Easy explanation:

Use data and interactions that already work to prove the new publication route. The calculation behavior stays in place; only the way the existing map layer is stored, published, and loaded changes.

Baseline PR scope:

- use the current `alkmaar_energy_map.geojson` as the initial publication artifact without redesigning its offline generation process;
- use `postcode6` as the stable feature id and preserve the existing polygon/multipolygon geometry and dashboard attributes, including `p6_gasm3_2023`, `p6_kwh_2023`, and `p6_kwh_productie_2023`;
- make the shared `layer-publisher` configurable enough to validate the artifact, transactionally load/upsert it into PostGIS, and register the PostGIS layer in GeoServer;
- make GeoServer WFS the dashboard's primary feature source so current client-side selection and styling can continue with GeoJSON features;
- retain the checked-in static GeoJSON as a clearly marked temporary fallback while the WFS route is being stabilized in `dev`;
- keep the current `GET /simulate/{pc6}`, shared CSV volume, sliders, and chart behavior working unchanged;
- do not split the policy backend, redesign the data-generation helper, add PV, or introduce scenario/congestion functionality in this baseline PR;
- add lightweight layer metadata for stable identity, CRS, attributes/units, source artifact, update timestamp, publication links, and known quality limitations.
- publish the temporary layer-level `datacompleetheid: 2` / `redelijke betrouwbaarheid` assessment as inherited metadata on every baseline PC6 feature, using method version `legacy-pc6-layer-qualitative-v1`, publication-time assessment timestamp, and an evidence summary covering real/open source data, standard profiles, estimates, assumptions, and known missing/sentinel values.

Completion criteria:

- the layer exists in PostGIS and is advertised by GeoServer WMS and WFS;
- the dashboard normally obtains PC6 features from GeoServer WFS;
- PC6 `1842EM` is available as the stable baseline fixture with numeric gas, electricity, and PV-production attributes;
- selecting a PC6, moving the current sliders, running the existing backend profile calculation, and rendering the returned CSV chart still work;
- disabling or making WFS unavailable exercises the static fallback without breaking the dashboard;
- publication is repeatable and does not duplicate features or corrupt the last successful layer.

Upgrade path:

Once the WFS-backed dashboard has proved stable in `dev`, remove the static fallback in a later cleanup PR. The same publisher contract then becomes the route for PV and each subsequent model layer. Stable PC6 identifiers, CRS, WMS/WFS links, and metadata preserve the path toward OGC API Features and catalogue discovery.

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
- `GET /outputs/{output_id}`: returns output metadata plus links to layer resources and database-backed profile/API resources; optional file exports may also be linked when they exist.

The existing residential load behavior keeps `GET /simulate/{pc6}` during transition. Once the renewed consumption service is integrated, the policy backend should preserve that route as a compatibility adapter until the frontend has migrated, while new model APIs move toward run IDs and output metadata records. This lets the implementation behind the route change without breaking the working dashboard.

Maturity path:

- MVP: simple FastAPI/HTTP JSON routes, permissive internal schemas, synchronous runs, transient scenario results returned directly or streamed, no durable scenario history, and a disabled persistence adapter boundary for later use.
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

The first version should execute model and scenario runs synchronously when the calculation is quick enough for an HTTP request. The response should still use a persistence-ready run envelope so the frontend and orchestrator do not need a redesign later, but the envelope is not durably stored.

Minimum run fields:

- `run_id`: stable identifier for the calculation.
- `status`: at least `accepted`, `running`, `completed`, or `failed`, even if MVP runs usually jump straight to `completed` or `failed`.
- `created_at`, `started_at`, and `finished_at`: timestamps for debugging, provenance, and later history views.
- `inputs`: the scenario/model parameters used for the run, or a pointer to them.
- `outputs`: inline or streamed transient results in the MVP; later this may also contain links to durable layer metadata, profile resources, or database-backed outputs.
- `data_quality`: completeness/confidence/provenance summary for the run result.

Maturity path:

- MVP: calculate immediately, return `run_id`, status, outputs, metadata, and `persistence: none` in the same response; do not promise historical retrieval after the request/process lifetime.
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

The grid model shares the grid topology, assets, geometry, voltage level, capacity, and other grid metadata. It also owns the existing grid-connection logic for consumption, PV, EV, and other source features because it owns the authoritative grid representation and valid connection targets.

The grid model exposes its connection result through its API and/or assignment records using stable source and grid-object references. Its own repository and API contract define the algorithm and required inputs. The congestion model consumes these results to aggregate profiles and calculate congestion; it does not duplicate or reinterpret the grid-connection logic.

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
    "method": "grid_model_defined",
    "method_version": "grid-model-version-or-method-id",
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

- expose grid matching through the grid model API so it also works during standalone development;
- calculate matches only against grid component types that the grid model declares valid for the requested assignment;
- let the grid model own a persistent `grid_assignments` table in the existing RDP PostGIS database, using a restricted service role;
- after successful source-layer publication, let the shared layer publisher call `POST /assignments/refresh` on the grid model;
- identify the source layer, source version, changed feature ids, and a resolvable API/WFS collection link in the refresh request rather than copying a complete layer into the request;
- refresh affected mapping rows when a source layer/profile layer changes and changed feature ids are known;
- request a full-layer refresh only for initial backfill or when a reliable change set cannot be produced;
- refresh assignments affected by changed grid components when the grid layer changes;
- keep the refresh endpoint manually callable for standalone development and operational recovery;
- do not make the policy-tool backend the routine refresh caller; it may expose stale/missing assignment status when orchestrating a scenario;
- let the congestion model consume the mapping to aggregate profiles onto LV components, LV/MV transformers, and later MV/HV transformers;
- expose mapping completeness and confidence so the frontend can show where congestion results are based on strong or weak assignment evidence.
- if assignment refresh fails, keep the published source layer available but mark its assignments stale or failed instead of silently using them as current.

Later path: replace the publisher's direct refresh call with a versioned `layer.updated` event on an RDP Redis stream. The grid model subscribes to that event and performs the same targeted refresh, so the direct MVP flow can evolve without changing the assignment contract.

Ownership rule:

The integration plan does not choose point or area allocation rules. For CBS buurten, PC6 areas, chargers, or other features, the grid model decides how many grid connections are returned and any associated shares or confidence. Downstream services rely on that output and retain the grid-model method/version and provenance where the grid contract exposes them.

Geonovum alignment guardrail:

- treat assignments as explicit relationships between geo-objects, not as hidden assumptions;
- prefer persistent identifiers for both source features and grid assets;
- retain the grid model method/version and any distance, share, confidence, and provenance fields its authoritative contract exposes;
- keep the structure compatible with later OGC API Joins-style linking between profile/scenario tables and geo-objects.

## Datacompleetheid

`datacompleetheid` is the first user-facing data quality measure. It should be coarse, qualitative, and easy to display on the map. It answers: how much confidence should the user place in this layer, mapping, profile, or scenario result, considering the available data, expected accuracy, missing values, and assumptions?

MVP bins:

| Value | Label | Meaning | Typical UI |
| --- | --- | --- | --- |
| `0` | `volledig gebaseerd op aannames` | No supporting observed or source data is available for the result; it is fully based on assumptions. | grey |
| `1` | `lage betrouwbaarheid` | Some supporting data is available, but much of the result depends on assumptions or missing values. | red |
| `2` | `redelijke betrouwbaarheid` | The result is expected to be reasonably accurate, but some assumptions, estimates, or missing values remain. | amber |
| `3` | `hoge betrouwbaarheid` | All data required for the intended result is available and the result is expected to be very accurate. | green |

Rules for the first version:

- every layer metadata record should include `datacompleetheid` when possible;
- the model or service that produces an output owns the qualitative assessment, model-specific rubric, supporting evidence, and changes to that method;
- the shared integration contract requires a score from 0 to 3, its label, and a short method/explanation reference; method version, assessment timestamp, and an evidence summary distinguishing observed, estimated, missing, and assumed inputs should be included when available;
- the model repo documents and tests its rule in `model-manifest.json` and exposes the resulting metadata through its API;
- integration CI validates the field shape, allowed values, and manifest/API consistency, but does not attempt to judge or reproduce the domain calculation;
- for the legacy PC6 baseline, use the agreed inherited layer-level score `2`, label `redelijke betrouwbaarheid`, and method `legacy-pc6-layer-qualitative-v1`; the publisher validates and carries that assessment into PostGIS, GeoServer attributes/metadata, and the layer registry without presenting it as feature-specific;
- grid-assignment mappings should include `datacompleetheid` so users can see whether profile-to-grid coupling is strong or approximate;
- scenario results should expose an overall `datacompleetheid`, using the most conservative contributing score by default;
- keep the level assignment simple and documented per model or layer; do not imply unsupported numerical precision;
- if a score is manually assigned during prototyping, record that in provenance so it is not mistaken for an automated quality calculation.

Professional target:

Later versions can expose richer quality dimensions such as accuracy, completeness, actuality, lineage, validation status, and uncertainty separately. `datacompleetheid` should remain a simple front-end summary, while the underlying metadata can grow toward ISO metadata quality elements, DCAT-AP-NL records, and NLDT trustworthiness requirements.

Geonovum alignment guardrail:

- create and maintain quality metadata as close as possible to the producing data/model process;
- keep responsibility for the content with the data/model provider while allowing shared infrastructure to validate the metadata contract;
- keep `datacompleetheid` clearly identified as a project-specific summary metric, with method and provenance, because ISO 19157 and DQV support richer and separately defined quality dimensions and metrics.

## Layer Versions And Update Triggers

The first version should detect layer changes with timestamps. Every layer, output, and mapping should expose `last_updated`. Derived records should also keep the timestamps of the source layers they depend on. Every published layer should have a stable feature id field so later diffing, joins, and mapping refreshes can identify changed objects.

Metadata maintenance rule:

- each model repo owns one versioned `model-manifest.json`, stored next to the model code and source-data configuration;
- `GET /metadata`, `GET /layers`, run records, and output records are generated from `model-manifest.json` plus runtime fields such as git commit, container image digest, timestamps, source versions, and output ids;
- the policy-tool backend and frontend consume model API metadata instead of maintaining separate hand-copied layer descriptions;
- every transient run/output response includes a metadata snapshot; when durable persistence is enabled later, that same snapshot is stored so historical scenario results remain explainable after model changes.
- the first PV manifest is intentionally rich: it must include the categories needed for discovery, publication, provenance, data quality, and API integration, even when some individual values are provisional during model development.
- CRS and GeoServer-readiness are not optional for geospatial outputs: the first PV layer must state the output CRS and produce a publishable artifact, even if the final GeoServer service URLs remain provisional.
- default GeoServer styling is acceptable for the first PV layer; custom SLD and legend metadata can be added once the layer is visible and the dashboard styling need is clear.

Change detection decision:

In easy terms: after a model publishes a new layer version, the publishing path should compare it with the previous version and write a small "what changed?" manifest. If the model already knows which features changed, it can provide that list directly. If it does not, the shared diff checker compares stable feature ids and hashes of relevant geometry/attribute values.

Ownership:

- model services own stable feature ids and domain output values;
- the crawler/ingestion/layer-publishing path owns generic diffing between previous and current published layer versions;
- the policy-tool backend exposes change metadata through layer/output metadata where useful;
- the congestion model consumes change manifests later, when incremental mapping/profile refresh is implemented.

Step-1 scope:

- require stable feature ids per layer, such as `cbs_buurt_code`, PC6, EV charger id, or grid asset id;
- record `layer_version`, `last_updated`, and `source_last_updated`;
- allow `change_manifest_url` to be absent until the diff checker exists;
- do not block the first PV layer PR on incremental congestion recalculation.

Example change manifest:

```json
{
  "layer_id": "layer:pv:capacity-cbs-buurt",
  "previous_version": "2026-07-28T10:00:00Z",
  "current_version": "2026-07-29T10:00:00Z",
  "change_detection_method": "feature_hash_diff",
  "feature_id_field": "cbs_buurt_code",
  "added_feature_ids": [],
  "updated_feature_ids": ["BU03610302"],
  "removed_feature_ids": [],
  "changed_bbox": [109000, 515000, 111000, 517000],
  "changed_count": 1
}
```

MVP metadata shape:

```json
{
  "layer_id": "https://reformers01.ewi.tudelft.nl/id/layer/pv/capacity",
  "metadata_schema_version": "0.1.0",
  "model_id": "pv-capacity-model",
  "model_version": "0.1.0",
  "model_git_sha": "<filled by build/runtime>",
  "layer_version": "2026-07-28T10:30:00Z",
  "feature_id_field": "<required stable feature id field>",
  "capacity_method": "model_estimated",
  "output_crs": "<required concrete CRS>",
  "publication_status": "ready_for_publication",
  "source_names": ["<filled from model metadata>"],
  "last_updated": "2026-07-28T10:30:00Z",
  "source_last_updated": {
    "<source_dataset_id>": "2026-07-28T10:30:00Z"
  },
  "lineage_summary": "<short human-readable summary from the model repo>",
  "change_detection": {
    "change_manifest_url": "<optional until diff checker exists>",
    "change_detection_method": "timestamp_only|model_reported|feature_hash_diff"
  },
  "geoserver": {
    "workspace": "<provisional_or_concrete>",
    "layer_name": "<provisional_or_concrete>",
    "wms_url": "<optional until published>",
    "wfs_url": "<optional until published>",
    "publication_owner": "<team/person>",
    "style_status": "default_geoserver",
    "sld_name": "<optional until custom style exists>",
    "legend_url": "<optional until custom style exists>"
  }
}
```

MVP refresh behavior:

- when a source layer timestamp changes, mark dependent mappings/results as potentially stale;
- when a new layer version is published, run the shared diff checker if the model did not provide its own changed feature ids;
- when model code, model metadata, or source-data configuration changes, expose the new `model_version`/git hash and refresh or republish affected layer outputs;
- if the update contains changed feature ids from the model or the shared diff checker, refresh only those mapping rows and any derived congestion results that depend on them;
- if changed feature ids are not available, fall back to refreshing the affected layer/model mapping, not the entire system;
- if the grid layer changes, refresh assignments for features near changed grid components where possible; only rebuild the full mapping when the change scope is unknown;
- after refresh, update `last_updated`, source timestamps, provenance, and `datacompleetheid`.

This keeps the first version practical while avoiding unnecessary full recomputation whenever a small layer update arrives.

Professional target:

- emit events such as `layer.updated`, `features.updated`, `mapping.stale`, `mapping.updated`, and `scenario.outputs.stale`;
- include changed feature ids, feature id field names, change manifests, or bounding boxes in update events whenever possible;
- maintain explicit congestion-owned dependency records so the model knows which mappings and scenario outputs depend on which layers/features;
- promote those records to a generic knowledge graph only if cross-model semantic queries, reasoning, or links to external ecosystems make that additional complexity worthwhile;
- add retries, audit logs, automated metadata validators, and eventually content hashes for reproducibility where needed;
- expose update state to the frontend so users can see whether a layer/result is current, stale, refreshing, or failed.

Geonovum alignment guardrail:

- timestamps support basic actuality metadata;
- dependency timestamps and event history support provenance and lineage;
- later catalogue records can expose update frequency, modified timestamps, lineage, and service links through DCAT-AP-NL, ISO metadata, or OGC API Records;
- incremental refresh should preserve stable geo-object identifiers so joins and derived mappings remain explainable; the shared diff checker is a practical implementation bridge until event-based update triggers are available.

## Future Data Space And Knowledge Graph Path

In easy terms: the working system can keep its data in normal databases and exchange it through normal APIs. If the project later needs to share governed data with other universities, network operators, municipalities, or European ecosystems, a data space can add agreements, identity, access control, catalogues, usage policies, and trusted connectors. If the project later needs machines to understand and traverse relationships such as "this PV estimate belongs to this buurt, feeds these LV assets, and contributes to this transformer result," a knowledge graph can represent those links explicitly.

These are separate upgrades:

- a data space addresses who may discover, access, and use which data under which conditions;
- a knowledge graph addresses what objects and concepts mean and how they are related;
- a deployment may eventually use both, but one does not require the other.

Staged path:

1. Working integrations: use stable feature ids, the existing URI-style identifiers, model manifests, OpenAPI-friendly APIs, GeoServer layers, and ordinary Postgres/PostGIS tables.
2. Explicit dependencies: let the congestion model store assignment and derivation records with source and target ids, relationship type, method, versions, timestamps, and provenance. Query these tables to determine what must be refreshed.
3. Semantic pilot, only when useful: map selected domain concepts and relationships to NEN 3610 Linked Data and established vocabularies. RDF/RDFS can express data and relationships, SKOS can define shared concepts, SHACL can validate graph records, OWL can support reasoning where needed, and PROV-O can represent lineage.
4. Data-space pilot, only for a concrete multi-party sharing case: publish discoverable data products and policies through a catalogue, add participant identity and access/usage controls, and test a standards-based data connector such as one using the Dataspace Protocol.

Adoption gates:

- do not introduce a triple store until relational dependency queries have become limiting or a semantic interoperability use case is approved;
- do not introduce data-space infrastructure until there is at least one external provider/consumer relationship that needs governed or sovereign sharing beyond ordinary authenticated APIs;
- run either upgrade as a bounded pilot before making it part of the critical RDP runtime;
- keep GeoServer, model APIs, and the dashboard working while semantic or data-space interfaces are added alongside them.

Geonovum alignment guardrail:

- NEN 3610 Linked Data provides the future bridge from geo-information models to linked data, with persistent identifiers and W3C vocabularies for semantics, validation, and provenance;
- Geonovum's data-space exploration treats APIs, metadata/self-descriptions, catalogues, provenance, identity, access/usage control, governance, and connectors as distinct building blocks rather than one product that must be installed at once;
- this staged approach follows the wider Geonovum data-ecosystem direction: start from a concrete societal use case, reuse standards and shared building blocks, and grow federation only as participants and trust requirements demand it.

## Scenario Result Handling And Future Storage

Scenario results can include profiles, summary values, provenance, `datacompleetheid`, and references to the model outputs and source layer versions used during the calculation.

Current decision: transient execution only.

- do not durably store scenario/run/result records in Postgres, Timescale, PostGIS, files, or export folders;
- execute the first scenario flow synchronously and return the result directly in the response, or stream a large profile to the requesting client;
- include a generated `run_id`, status, timestamps, input summary, model/source versions, provenance, `datacompleetheid`, and `persistence: none` in the returned envelope;
- do not advertise durable output URLs or historical retrieval when no stored resource exists;
- `GET /runs/{run_id}` may expose an active or short-lived in-process run, but the MVP makes no guarantee that completed runs survive a restart or remain historically retrievable;
- keep published reusable model layers, canonical non-scenario model data/profiles, and persistent grid assignments separate from this no-scenario-history decision.

Transient MVP response shape:

```json
{
  "run_id": "scenario-local-dev-001",
  "scenario_name": "High PV and EV adoption",
  "status": "completed",
  "persistence": "none",
  "finished_at": "2026-07-28T11:00:00Z",
  "source_versions": {
    "consumption": "2026-07-28T10:00:00Z",
    "pv": "2026-07-28T10:15:00Z",
    "ev": "2026-07-28T10:30:00Z",
    "grid_assignment": "2026-07-28T10:45:00Z"
  },
  "outputs": {
    "profiles": [
      {
        "profile_type": "transformer_load",
        "time_resolution": "PT15M",
        "unit": "kW",
        "delivery": "inline_or_streamed"
      }
    ],
    "summary": {
      "worst_transformer_id": "transformer-987",
      "overload_hours": 3.25
    }
  },
  "data_quality": {
    "datacompleetheid": 2,
    "datacompleetheid_label": "redelijke betrouwbaarheid"
  }
}
```

Future-storage guardrail:

- place persistence behind a replaceable interface/configuration switch that is disabled in the first version;
- keep request/response schemas stable enough to add durable output ids and links later;
- reserve optional fields such as `expires_at` without requiring or populating them now;
- when persistence is explicitly enabled, reuse Postgres for run metadata, Timescale for time series, PostGIS/GeoServer for selected map-visible result layers, and files only for optional exports;
- decide retention, cleanup, access control, catalogue exposure, and stale-result handling at that later activation point.

Geonovum alignment guardrail:

- describe the synchronous operation and response through OpenAPI even though results are not persisted;
- use explicit identifiers, units, timestamps, source versions, provenance, and quality metadata in the transient response;
- keep the contract ready for later OGC API Processes-style jobs and OGC API/GeoServer publication without implementing durable job resources prematurely.

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
    "datacompleetheid_label": "hoge betrouwbaarheid",
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

The frontend should evolve from hardcoded layer radio buttons into a layer registry. In the MVP, the dashboard should use `GET /layers` on the policy-tool backend as the canonical layer discovery endpoint. A static `layers.json` may still exist as fallback or seed data for local development, but it should not be the dashboard's primary source of truth.

In easy terms: the dashboard should ask the policy-tool backend, "which layers can I show right now?" The backend can then answer with consumption, PV, EV, grid, and scenario layers, even if some of those records were initially loaded from static configuration.

MVP registry record, using the first PV layer as the shape to implement:

```json
{
  "id": "https://reformers01.ewi.tudelft.nl/id/layer/pv/capacity-cbs-buurt",
  "local_id": "layer:pv:capacity-cbs-buurt",
  "title": "PV Capacity by CBS Buurt",
  "description": "Model-estimated installed PV capacity per CBS buurt.",
  "group": "pv",
  "model_id": "https://reformers01.ewi.tudelft.nl/id/model/pv-capacity",
  "model_version": "to_be_confirmed",
  "metadata_url": "/policy-api/models/pv-capacity/metadata",
  "geoserver": {
    "workspace": "rdp",
    "layer": "pv_capacity_cbs_buurt",
    "qualified_name": "rdp:pv_capacity_cbs_buurt",
    "wms_url": "/geoserver/rdp/wms",
    "wfs_url": "/geoserver/rdp/wfs"
  },
  "geometry_type": "polygon",
  "selectable_feature_type": "cbs_buurt",
  "crs": "EPSG:28992",
  "metrics": [
    {
      "name": "pv_capacity_kwp",
      "title": "PV capacity",
      "unit": "kWp",
      "data_type": "number"
    }
  ],
  "style": {
    "style_status": "default_geoserver",
    "sld_name": null,
    "legend_url": null,
    "default_visible": false
  },
  "actions": {
    "selectable": true,
    "show_profile": false,
    "scenario_input": true
  },
  "data_quality": {
    "datacompleetheid": 2,
    "datacompleetheid_label": "redelijke betrouwbaarheid",
    "datacompleetheid_method": "to_be_confirmed"
  },
  "provenance": {
    "source_names": ["to_be_confirmed"],
    "lineage_summary": "to_be_confirmed"
  },
  "last_updated": "to_be_confirmed",
  "source_last_updated": "to_be_confirmed",
  "state": "current"
}
```

Mandatory MVP fields:

- identity: `id`, `local_id`, `title`, and `description`;
- ownership and traceability: `group`, `model_id`, `model_version`, and `metadata_url`;
- publication: `geoserver.workspace`, `geoserver.layer`, `geoserver.qualified_name`, `geoserver.wms_url`, and `geoserver.wfs_url`;
- spatial contract: `geometry_type`, `selectable_feature_type`, and `crs`;
- metric contract: `metrics[]` with `name`, `title`, `unit`, and `data_type`;
- style contract: `style.style_status`, `style.default_visible`, and optional `sld_name`/`legend_url` values, which may be `null` while GeoServer default styling is used;
- interaction contract: `actions.selectable`, `actions.show_profile`, and `actions.scenario_input`;
- quality and freshness: `data_quality.datacompleetheid`, `data_quality.datacompleetheid_label`, `last_updated`, `source_last_updated`, and `state`;
- provenance: `provenance.source_names` and `provenance.lineage_summary`.

A field may temporarily contain `unknown`, `to_be_confirmed`, or `null` only when the owning model PR explains why and the value is not needed for the dashboard smoke test. The field itself should still be present so schema validation, frontend rendering, and later catalogue mapping do not drift.

MVP behavior:

- load available layers from `GET /layers` on the policy-tool backend;
- allow a static `layers.json` fallback or seed dataset for local development and bootstrap cases;
- group layers by model: consumption, PV, EV, grid, scenarios;
- allow multiple overlays when they make sense;
- show `datacompleetheid`, freshness, and stale/current/refreshing/failed state per layer/result;
- use registry metadata to decide whether a feature can show a profile, be selected for a scenario, and later display a scenario output;
- request scenario runs through the policy-tool backend when a registry action says a layer/feature can be used as scenario input;
- render output metadata records rather than assuming every model writes one specific CSV filename;
- validate the mandatory registry fields for every layer returned by `GET /layers`.

Maturity path:

- MVP: `GET /layers` JSON from the policy-tool backend, optionally seeded by static `layers.json`;
- Next: merge static layers and model outputs into one registry response; later add scenario result layers when scenario functionality exists;
- Professional target: catalogue-style discovery through OGC API Records/DCAT-AP-NL-style metadata, with geospatial access through GeoServer now and OGC API Features/Tiles later.

This keeps the dashboard usable while avoiding a future pileup of model-specific JavaScript branches.

## Implementation Order And Branch Strategy

The implementation should prioritize visible, working map layers before deeper model coupling. The system should stay functional at every step, with PR checks becoming stricter as soon as the first layer milestone is reached.

Implementation phases:

1. GeoServer-visible model layers: first migrate the current static PC6 energy layer into the shared PostGIS/GeoServer path, then make each new model publish its first useful output as a GeoServer-visible layer. Deliver this phase one layer/model at a time: verify the dashboard, API, publisher, and GeoServer setup after the PC6 baseline and after every new model. PV is the first new model, followed by EV, grid, and later others. Scenario result layers remain out of scope.
2. Transformer profile coupling: connect consumption, PV, EV, grid, and other outputs through the congestion model so profiles can be aggregated at LV/MV transformers and later MV/HV transformers.
3. Scenario UI: add sliders, buttons, synchronous scenario requests, transient run metadata, and directly returned profiles/summaries on top of the working model/layer foundation. Durable history and GeoServer-published scenario result layers remain disabled until explicitly introduced.
4. Professional setup: harden the existing PostGIS/Timescale stores with production migrations, retention, backup, performance, and access controls, then add event-based triggers, richer tests, OpenAPI documentation, catalogue-style metadata, and OGC API/Geonovum-aligned publication where useful.

Branching policy:

- use the long-lived `dev` branch created from cleaned deployment commit `7273c94d65e34a7680872445b70c9556eb25c329` as the integration branch for active development;
- create feature/fix branches from `dev` and open PRs back into `dev`; do not develop directly on `main`;
- only merge/release from `dev` to `main` after explicit approval from the project owner;
- no implementation phase automatically triggers a release; approval may be given at any working and sufficiently tested checkpoint; deployment to the actual server remains a separate explicit decision;
- use `dev` for full integration tests before anything is shipped to `main` or the live server;
- keep branch names informative, such as `feature/...` or `fix/...`.

PR/testing guardrail:

After phase 1 starts landing, every model-layer PR into `dev` should include automated checks that prove the existing app still works and that the new model layer is fully usable before adding the next model. The required path is full end-to-end, not API-only or GeoServer-only.

For the baseline PC6 GeoServer migration PR, this means:

Fixture area: PC6 `1842EM`.

- Docker Compose configuration validation for the integrated stack;
- repeatable publisher execution and PostGIS feature-count/id uniqueness checks;
- WMS `GetCapabilities`, non-empty `GetMap`, WFS `DescribeFeatureType`, and WFS `GetFeature` checks for the published PC6 layer;
- fixture checks that `1842EM` exists, has numeric `p6_gasm3_2023`, `p6_kwh_2023`, and `p6_kwh_productie_2023` attributes, and exposes inherited `datacompleetheid: 2` with label `redelijke betrouwbaarheid` and method `legacy-pc6-layer-qualitative-v1`;
- dashboard checks that WFS is the primary source, PC6 selection and sliders work, and the static GeoJSON fallback works when WFS is unavailable;
- existing policy-backend health and `GET /simulate/1842EM` checks, including retrieval and chart parsing of the generated CSV;
- checks that the baseline PR does not introduce PV-model, transformer-assignment, or congestion behavior.

For the first PV model-layer PR, this means:

Fixture area: CBS buurt `BU03610302` / `Overdie-Oost`.

- Docker Compose configuration validation for the integrated stack;
- model API checks: `GET /`, `GET /metadata`, `GET /layers`, `POST /runs`, `GET /runs/{run_id}`, and `GET /outputs/{output_id}`, using `BU03610302` / `Overdie-Oost` where a spatial fixture is needed;
- fixture value check: API output or WFS `GetFeature` for `BU03610302` returns `pv_capacity_kwp` as a numeric value greater than zero, without asserting an exact model-estimated value;
- policy-tool backend health/API smoke tests, including layer-registry/orchestration compatibility where the PV layer is exposed through the policy-tool path;
- frontend/dashboard smoke test: dashboard loads, PV layer is available in the layer UI or registry-driven equivalent, toggling/activating the layer produces no frontend errors;
- GeoServer publication checks: WMS `GetCapabilities` includes the PV layer, WMS `GetMap` returns a non-empty image for or around `BU03610302`, and WFS `DescribeFeatureType` exposes expected fields including `pv_capacity_kwp`;
- layer registry schema/metadata validation, including ids, title/description, model/group/version, metadata URL, CRS, metric names/units, GeoServer layer and WMS/WFS fields, style status, freshness, `datacompleetheid`, provenance, and actions;
- model-owned `model-manifest.json`/API consistency checks;
- `datacompleetheid`, `last_updated`, source provenance, model version/git hash, CRS, output artifact, and output-link validation.

Geonovum alignment guardrail:

This is consistent with NLDT guardrails: work from use cases, avoid pre-optimization, keep components containerable and API-speaking, and use the best reliable setup available today. It also mirrors the Geonovum OGC API Testbed idea of stable versus sandbox/integration environments and GitHub workflow based maintenance.

## Near-Term Steps

1. Create the long-lived `dev` branch at cleaned deployment commit `7273c94d65e34a7680872445b70c9556eb25c329`, then merge this planning branch into `dev` only through its PR.
2. Start phase 1 with a dedicated baseline PR that makes the shared `layer-publisher` configurable, publishes the existing PC6 energy GeoJSON through PostGIS/GeoServer, makes WFS the dashboard's primary feature source, and preserves the static file as a temporary fallback.
3. After the baseline is fully working in `dev`, add the first new GeoServer-visible model layer for model-estimated PV capacity in its own PR, using CBS buurt polygons and `pv_capacity_kwp`, with full end-to-end smoke tests proving the integrated stack still works.
4. Repeat the model-layer PR pattern for EV chargers, grid, and later other layers, even if their first outputs are simple standalone datasets.
5. Add a frontend layer registry backed by `GET /layers` on the policy-tool backend, optionally seeded by static `layers.json`, then use it to render available model layers first and scenario outputs later.
6. Add mandatory registry fields, including `datacompleetheid`, `last_updated`, `source_last_updated`, CRS, metrics/units, GeoServer service links, style status, actions, and lightweight provenance.
7. Add PR checks for `dev` that validate Docker Compose config, model API, policy-tool backend, dashboard reachability/layer toggle, GeoServer WMS/WFS publication, layer registry metadata, manifest consistency, provenance, and output links.
8. Inventory current policy-tool backend code into API/orchestration glue, consumption/profile behavior, and data ingestion, and document the missing transformer-level congestion capability; do this as preparation for later splits rather than before the PV layer.
9. Keep the current policy-tool backend name and legacy profile/orchestration behavior in code until PV is working as the first new model layer.
10. Start phase 2 with the first `congestion-model-service` vertical slice: consume grid assignments and aligned 15-minute model profiles, aggregate them per transformer, and persist/expose the transformer profile with provenance and quality metadata.
11. Integrate the grid model's existing grid-connection API/output and authoritative assignment records, with incremental refresh on relevant layer updates and consumption by the congestion model; do not implement a competing matching rule in this repository.
12. Once transformer profile aggregation is reliable, add transformer capacity/headroom comparison and the first congestion indicators as a separate increment.
13. Start phase 3 by adding scenario sliders/buttons and `POST /scenarios` flow once phase 2 outputs are stable enough.
14. Keep the first scenario implementation transient. Introduce durable Postgres/Timescale/PostGIS storage, downloadable exports, retention rules, and GeoServer-visible scenario result layers only through a later explicit decision, using the existing persistence-ready contract.
15. Promote shared external API connections into crawler/ingestion services when the data contract stabilizes.
16. Start phase 4 hardening only after the working map/model/scenario flow is stable in `dev`.

## Open Questions

- When should orchestration move out of the policy-tool backend into a dedicated service, if ever?
- Which scenario parameters are generic enough for the policy-tool backend contract, and which should stay inside model-specific parameter blocks?
- Which external sources belong in the RDP crawler immediately, and which can remain standalone-only while prototyping?
