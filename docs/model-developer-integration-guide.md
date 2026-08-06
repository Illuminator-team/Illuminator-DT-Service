# Model Developer Integration Guide

## Purpose

This guide defines when an individual model is ready to be integrated into the
REFORMERS Rapid Deployment Platform (RDP). It applies to PV, consumption, EV,
grid, congestion, and future models.

In simple terms, a model is integration-ready when a developer can start from a
fresh clone, prepare its data explicitly, start it in a container, call it over
HTTP, retrieve a documented geospatial result, and understand the quality and
age of that result. The RDP must not need access to the model's source tree or
internal files to use it.

The words in this guide have these meanings:

- **MUST**: required before an integration PR can merge into `dev`.
- **SHOULD**: expected unless the model documents a good reason not to do it.
- **LATER**: part of the professional target, but not required for the first
  working integration.

This is the implementation companion to the
[future model integration plan](model-integration-plan.md). If the two documents
conflict, record the decision in the plan and update this guide in the same PR.

## The Boundary

Keeping ownership clear prevents every model from inventing its own deployment
path.

| Model repository owns | Shared RDP integration owns |
| --- | --- |
| Scientific method and calculation code | Calling and orchestrating model APIs |
| Source acquisition and local source cache | Deployment secrets, routing, and service discovery |
| Stable feature identifiers | Validation at the integration boundary |
| Output schema, units, and null semantics | Loading and updating shared PostGIS tables |
| Model-specific quality and `datacompleetheid` rules | Publishing shared GeoServer layers and styles |
| Provenance and source actuality | Frontend layer registry and user presentation |
| Standalone API and container | Cross-model and full-stack tests |
| Model initialization, readiness, and model tests | Release of the integrated stack |

The model MUST expose data and metadata through its API. It MUST NOT require a
shared filesystem path, a PostGIS writer password, or GeoServer administrator
credentials. The shared RDP publisher is the only component that writes model
output to the common PostGIS and GeoServer deployment.

A model may have its own database or a development-only map preview when that is
useful to its developers. Those are model internals and are not the RDP
publication contract.

## Recommended Delivery Sequence

Developers SHOULD make small, reviewable changes in the model repository. A
model that already satisfies a step does not need an artificial PR for it.

1. **Output contract**: define the layer, stable IDs, fields, units, geometry,
   metadata, and quality meaning.
2. **HTTP service**: expose metadata, runs, and downloadable output without
   changing the scientific calculation.
3. **Reproducible container**: build and run the service from a clean checkout.
4. **Data initialization**: make heavy downloads and preprocessing explicit,
   persistent, observable, and restartable.
5. **Model acceptance**: prove a stable test area works and publish the evidence.
6. **RDP integration**: pin a reviewed model version and add the shared
   PostGIS/GeoServer/frontend path in an Illuminator PR to `dev`.

Every merged step MUST leave the model working. Do not defer basic tests until
the final integration PR.

Model release and RDP acceptance are separate promotion steps. The model PR
MUST merge and its tests MUST pass before an image is published. The RDP MUST
then pin the published image by digest and independently prove the complete
deployment path. A passing model fixture or image test does not make an RDP
integration mergeable.

## 1. Repository And Workflow

The model repository MUST:

- use reviewed pull requests for changes intended for integration;
- contain setup, initialization, run, test, and cleanup commands in its README;
- keep secrets, local `.env` files, downloaded source data, generated outputs,
  caches, virtual environments, and editor files out of Git;
- include a sanitized `.env.example` when configuration is required;
- run its automated tests in CI from a clean checkout;
- declare the supported runtime and dependency versions; and
- identify the license of the model code and, where known, the licenses and use
  restrictions of its source datasets.

The release handed to the RDP MUST be an immutable Git commit or tag. A mutable
branch name by itself is not a release identifier.

## 2. Standalone Operation

The model MUST remain useful outside the RDP. A developer MUST be able to run its
calculation through its documented library or CLI entry point and through the
HTTP API.

The API wrapper MUST call the same scientific implementation as the standalone
entry point. It MUST NOT contain a second copy of the model logic. Adding the API
MUST NOT silently change formulas, parameters, source selection, or outputs.

Configuration MUST come from documented command-line options, configuration
files, or environment variables. Machine-specific absolute paths are not valid
defaults.

## 3. Minimum HTTP Contract

The first version does not need to implement the full OGC API Processes
standard. It does need predictable resources that can later be mapped to that
standard.

| Method and path | Purpose | Required behavior |
| --- | --- | --- |
| `GET /` | Liveness | Cheap response proving the HTTP process is alive; no data download or model run |
| `GET /ready` | Readiness | `200` only when required initialized data is valid; otherwise `503` with a safe reason |
| `GET /metadata` | Model metadata | Model identity, version, sources, method, quality rule, and supported selections |
| `GET /layers` | Output catalogue | Available layers, schemas, spatial coverage, CRS, units, and links |
| `POST /runs` | Start a calculation | Validates the request and returns a run record or completed result |
| `GET /runs/{run_id}` | Inspect a run | Status, timestamps, input summary, model version, errors, and output links |
| `GET /outputs/{output_id}` | Inspect output | Output metadata and a link to its data representation |
| `GET /outputs/{output_id}/data` | Retrieve output | Returns the output bytes over HTTP, initially as `application/geo+json` |

Large layers MAY additionally offer a documented bulk representation such as
GeoPackage or GeoParquet through HTTP content negotiation. They MUST still offer
a bounded GeoJSON selection suitable for contract testing and MUST never replace
HTTP retrieval with an internal file path.

The API MUST also:

- publish an OpenAPI document generated from or checked against the running API;
- use ISO 8601 timestamps with a timezone, preferably UTC with `Z`;
- use documented enum values and explicit units rather than values encoded in
  free text;
- return a stable JSON error shape with a machine-readable code and a safe human
  explanation;
- return `4xx` for invalid or unsupported selections;
- return `404` for unknown run and output IDs;
- never silently replace an invalid area selection with a national or full-data
  run;
- never expose internal filesystem paths, stack traces, credentials, or raw
  exception messages; and
- reject caller-controlled output paths and path traversal attempts.

The MVP may execute a run synchronously. Its records and links SHOULD still be
shaped so asynchronous execution, progress, cancellation, and retries can be
added later without replacing the API.

Run and output IDs MUST be unique, and concurrent runs MUST NOT overwrite each
other. An output link MUST become visible only after its bytes and metadata are
complete. The API MUST document result retention and cleanup; an expired result
SHOULD return `410` rather than an unrelated `404`.

## 4. Heavy Data And Initialization

Large downloads and preprocessing are a lifecycle concern, not an invisible
side effect of starting the web server.

If the model requires source data or a prepared cache, it MUST provide one
explicit one-shot command, for example:

```shell
python -m example_model.api.initialize
```

The initialization flow MUST:

- use the same container image and configuration as the API;
- store reusable data in a documented persistent volume;
- use explicit connect and read timeouts for every external source;
- retry only transient failures, such as timeouts, rate limits, and server errors,
  with a bounded backoff policy; permanent client, schema, and validation errors
  MUST fail promptly;
- preserve each completed, validated source artifact so a retry or resumed run does
  not repeat unaffected downloads;
- be safe to run more than once;
- resume safely or restart cleanly after interruption;
- write temporary files first and publish completed files atomically;
- use a lock so two initializers cannot corrupt the same cache;
- validate content and structure, not only the existence of a directory;
- publish a small state or marker record only after validation succeeds; and
- fail with a non-zero exit code and a useful sanitized message.

The state record SHOULD include:

- model version or calculation contract version;
- initialization configuration fingerprint;
- source dataset identifiers and versions or reference periods;
- retrieval timestamps and checksums when available;
- completion timestamp; and
- schema or cache format version.

`GET /ready` MUST validate this state against the running model and current
configuration. `POST /runs` MUST fail fast before calculation when the state is
missing, incomplete, or incompatible.

Container build, process import, API startup, and liveness checks MUST NOT start
heavy downloads or preprocessing. Readiness checks MUST be quick and MUST NOT
repair data as a side effect.

Retry logs MUST identify the stable source or component, attempt number, and failure
class without printing credentials, signed URLs, query payloads, or private paths.

The README MUST state the expected download size, prepared size, initialization
time range, external hosts contacted, timeout and retry policy, and how to clear or
refresh the cache.

Retries improve resilience but do not solve persistent source unreachability.
When all bounded attempts against a required source are exhausted, the model
MUST fail closed and identify the stable source and failure class. It MUST NOT
substitute fixture data or a scientifically different API merely to make CI
pass.

If a supported live source cannot be reached reliably from the deployment
network, the model MAY provide a verified source-cache bundle or cache image.
That bootstrap artifact MUST:

- be produced by a documented successful real-source initialization on a
  trusted network;
- remain outside the code repository and normal API image;
- be addressed and deployed by immutable digest or checksum;
- carry model version, configuration fingerprint, source-contract version,
  source provenance, producer identity, retrieval times, and per-file checksums;
- exclude credentials, readiness markers, locks, temporary files, generated
  model outputs, and unrelated local caches;
- reject traversal, links, tampering, incompatible configuration, source drift,
  and conflicting existing cache files before publishing imported bytes; and
- invoke the ordinary initializer after import so only the model's normal
  structural and scientific validation can create readiness.

The live-download and bootstrap paths MUST use the same cache contract and
scientific calculation. The handoff MUST document how the artifact is produced,
refreshed, retained, and revoked. Code-image and cache-artifact identities MUST
be recorded separately.

## 5. Reproducible Container

The integration release MUST include a production-oriented Dockerfile. It MUST:

- pin the base image to an immutable digest;
- install locked dependencies, with hashes where the ecosystem supports them;
- run as a non-root user;
- use an allow-listed build context;
- exclude `.git`, secrets, local data, outputs, tests not needed at runtime,
  `__pycache__`, bytecode, package metadata, and virtual environments;
- contain no source-data cache or generated model result;
- expose a documented port and start command;
- handle termination cleanly; and
- have a container-level health check or documented Compose health check.

Pay special attention to negated `.dockerignore` rules. Re-including a source
directory can accidentally re-include nested cache files. CI SHOULD inspect the
built image and prove that generated artifacts are absent.

A Compose example SHOULD show the API and, when needed, a one-shot initializer
using the same image and named data volume. A fresh build and API startup MUST
work without access to a developer's home directory.

### Private Image Distribution

When an integration image is private, the handoff MUST document its registry
owner, package name, immutable digest, login username, and minimum pull
permission. Do not assume an integration repository's automatic
`GITHUB_TOKEN` can read a package owned by another repository, organization,
or personal account.

When a separate credential is required, it MUST be pull-only, stored as an
encrypted repository or deployment-environment secret, and used only for
registry login. The token value MUST NOT enter Git, `.env`, Compose, image
layers, PR text, artifacts, or logs. The workflow SHOULD validate the secret is
configured, authenticate, and pull the immutable image before starting expensive
data initialization so access failures are fast and unambiguous.

## 6. Geospatial Output Contract

The first RDP transfer format is a GeoJSON `FeatureCollection` returned over
HTTP. Every feature MUST contain:

- a stable feature ID that remains the same between reruns for the same real
  object or area;
- a persistent feature URI, or a documented URI template based on that stable
  ID, using the project's `https://reformers01.ewi.tudelft.nl/id/` base;
- one valid geometry of the documented type;
- the canonical model value fields;
- documented units and null semantics;
- `datacompleetheid` or a documented layer-level quality default;
- enough provenance to trace the output to a run and model version; and
- no `NaN`, infinity, or undocumented sentinel values.

GeoJSON coordinates MUST use the RFC 7946 longitude/latitude order and WGS 84
world geodetic reference system. The manifest MUST record the CRS using a stable
CRS URI. Native Dutch RD data may be retained internally, but it MUST be
transformed for this initial GeoJSON representation. Support for additional CRS
representations can be added later using OGC API Features CRS conventions.

The layer contract MUST document:

- layer ID, title, description, and owning model;
- geometry type and spatial resolution, such as CBS buurt, PC6, point, or grid
  component;
- spatial coverage;
- every property name, type, unit, range, and null meaning;
- uniqueness and construction of the feature ID;
- whether values are measured, registered, model-estimated, or scenario output;
- update frequency or trigger;
- source actuality and model generation time; and
- expected feature count or a defensible range.

Do not invent a different schema for GeoServer. The shared publisher transforms
or loads the same documented model output.

### Profiles

A phase-1 static layer does not need to calculate profiles. When a model does
produce a profile, it MUST link the time series to the stable feature ID rather
than duplicating the geometry. It MUST document the quantity, unit, timezone,
start and end, interval, missing-value meaning, model version, and scenario or
assumption set. The project default interval is 15 minutes, represented as
`PT15M`. Keep profile data separate from feature properties so a later
SensorThings, OGC API, or time-series storage interface can be added without
changing feature identity.

## 7. Metadata And Provenance

The model repository MUST contain a versioned machine-readable manifest next to
the model code and source-data configuration. The API SHOULD generate
`/metadata`, `/layers`, and run metadata from this manifest plus runtime facts,
instead of maintaining several manual copies.

At minimum, metadata MUST distinguish:

| Field or concept | Meaning |
| --- | --- |
| `source_reference_period` | Period represented by the source observations or register |
| `source_modified_at` | When the source publisher last changed that source, if known |
| `source_retrieved_at` | When this model downloaded or accessed the source |
| `model_run_at` | When calculation began |
| `output_generated_at` | When this result was completed |

Do not use retrieval time as `source_modified_at` or describe it as the source's
last update. Unknown values MUST be `null` or omitted according to the schema,
not guessed.

The current RDP registry also uses the compatibility name
`source_last_updated`. When that field is present, it MUST mean the source
publisher's last modification or documented source vintage. It MUST NOT contain
`source_retrieved_at`.

Metadata MUST also include:

- persistent model and layer IDs;
- model semantic version and Git commit;
- container image digest when available;
- calculation or schema contract version;
- source names, source links, licenses, and versions or reference periods;
- a concise method and lineage summary;
- supported selections and known limitations;
- contact or owning organization; and
- links to the OpenAPI document and output schema.

Every output record MUST snapshot the model version, input summary, relevant
source versions, and quality rule used for that output. This keeps old results
explainable after the model is updated.

## 8. `datacompleetheid`

`datacompleetheid` is a coarse qualitative confidence indicator for users. It is
not a measured accuracy percentage.

| Value | Meaning |
| --- | --- |
| `3` | All relevant data is available and the result is considered very accurate |
| `2` | The result is quite accurate, but some inputs are missing or assumptions are used |
| `1` | Some supporting values are available, but the result relies on many assumptions |
| `0` | The result is fully based on assumptions |

The model developer owns this assessment because only that developer knows the
sources and assumptions. The rule MUST be:

- deterministic for the same inputs;
- versioned with the model contract;
- described in plain language and machine-readable metadata;
- accompanied by evidence fields or reason codes where practical; and
- tested at boundary cases.

Each assessment MUST expose its integer score, a short user-facing label, a
method or rule version, an assessment timestamp, and a concise evidence summary.

The model SHOULD provide feature-level values when source coverage varies by
location. It MAY provide a documented layer-level value when the evidence is
truly uniform. The RDP validates the `0` to `3` range but does not recalculate
the model's score.

When a model produces scenario results, it MUST assess the result as well as its
input layers. The output metadata MUST link to the input assessments and explain
how missing data and assumptions affected the result. The first scenario model
may use a simple conservative rule, but that rule must be explicit and versioned.

Richer dimensions such as accuracy, actuality, uncertainty, lineage, and
validation status are **LATER** fields. Their addition MUST remain possible and
must not be compressed irreversibly into `datacompleetheid`.

## 9. Change And Freshness Support

The first integration may detect updates using timestamps and version records.
To avoid full reloads later, model outputs MUST use stable feature IDs and MUST
publish an output version and generation timestamp.

The model SHOULD expose, when inexpensive:

- source or output checksums;
- created, changed, and deleted feature IDs;
- a change extent or affected area;
- previous output version; and
- whether a full replacement is required.

These fields are optional in the MVP. The schema MUST allow them to be added
without changing feature identity. Event-triggered refresh and incremental
publisher updates are **LATER** work.

## 10. Security Minimum

Before handoff, the model repository and image MUST pass a sensitive-information
review.

The review MUST scan the current tree, relevant Git history, and final container
image or image layers. If a real secret was ever committed, revoke or rotate it
first; deleting the file in a later commit is not sufficient. A secret scanner
SHOULD run in CI to prevent recurrence.

At minimum:

- no real credentials, tokens, private keys, service passwords, or private URLs
  are committed or baked into the image;
- example credentials are clearly unusable placeholders;
- secrets are supplied only by the deployment environment;
- the API does not accept arbitrary filesystem paths or shell fragments;
- output IDs cannot escape the configured output directory;
- logs and errors do not reveal secrets, local paths, or source records that
  should not be public;
- untrusted request fields are validated with explicit limits; and
- the service can run on an internal container network without being published
  directly to the internet.

GeoServer and shared PostGIS credentials belong only to the RDP publisher and
deployment. Giving those credentials to a model is an integration defect.

## 11. Required Test Evidence

Tests MUST cover behavior rather than only importing modules.

| Test level | Minimum evidence |
| --- | --- |
| Unit | Calculation boundaries, schema creation, quality rule, and validation errors |
| Scientific regression | A small deterministic case that detects unintended model changes |
| API contract | Every required route, media type, status code, metadata field, and invalid selection |
| Security | Traversal attempts, unknown IDs, malformed payloads, and sanitized errors |
| Initialization | Missing, successful, repeated, interrupted/incomplete, incompatible, concurrent, transient retry/recovery, retry exhaustion, and permanent-failure states |
| Live HTTP | Tests connect to a real listening server, not only an in-process test client |
| Container | Clean build, non-root process, health/readiness, named volume, and no hidden local files |
| End to end | Initialize, start, run a stable feature, retrieve GeoJSON, and validate its contract |

Each model MUST define one stable acceptance fixture that is small enough for CI
or a documented integration job. Assertions SHOULD check durable facts such as
the selected feature ID, non-empty geometry, value type/range, and a positive
result where scientifically justified. Avoid exact floating-point values when
normal source-data updates may legitimately change them.

For the first PV capacity model, the agreed fixture is CBS buurt
`BU03610302` (`Overdie-Oost`) and `pv_capacity_kwp` MUST be greater than zero.

When heavy external data makes the full case unsuitable for every PR, CI MUST
still run a deterministic lightweight fixture. The handoff MUST also include a
dated result from the real clean-data workflow and its second cached run.

Treat acceptance as three cumulative evidence lanes:

1. the deterministic model lane proves calculation, API, security, and
   container contracts without depending on public-source availability;
2. the real-source model lane proves clean initialization, provenance, the
   stable fixture, and a cached rerun against authoritative data; and
3. the RDP lane proves private image retrieval where applicable, initialization,
   API readiness, shared PostGIS/GeoServer publication, registry/dashboard
   behavior, and repeatable publication in one full-stack run.

Evidence from one lane MUST NOT be described as evidence for another. Fixture
data MUST NOT be silently used in the real-source or RDP lane.

## 12. Handoff Package

The model developer MUST provide all of the following before an Illuminator
integration PR starts:

- repository URL and immutable Git commit or tag;
- container image name and digest, or exact clean build command;
- source-cache artifact digest and provenance, when a bootstrap is required;
- supported architecture and minimum CPU, memory, disk, and expected runtime;
- initialization command and cache volume details;
- API start command, internal port, liveness URL, and readiness URL;
- OpenAPI document URL or checked-in file;
- model manifest and output schema;
- example valid request and GeoJSON response;
- stable acceptance fixture and expected durable assertions;
- source inventory, licenses, reference periods, and update method;
- `datacompleetheid` rule and evidence fields;
- test commands and CI run link;
- clean initialization, transient-failure recovery, and cached rerun evidence;
- separate deterministic, real-source, and RDP evidence status;
- known limitations and unsupported selections; and
- maintainer or owning team.

Use this compact handoff record in the model PR or release notes:

```text
Model:
Release commit/tag:
Container image/digest:
Source-cache artifact/digest (if used):
Initialization command:
API start command:
Liveness URL:
Readiness URL:
OpenAPI URL/file:
Manifest file:
Layer IDs:
Geometry and CRS:
Canonical value fields and units:
Stable fixture:
Clean initialization size/time:
Cached rerun time:
Source versions/reference periods:
Datacompleetheid rule version:
Test command and CI evidence:
Known limitations:
Owner/contact:
```

## 13. Integration Acceptance Gate

The RDP reviewer runs this gate before accepting the model version:

- [ ] A fresh clone builds the documented image without local files.
- [ ] The image runs as non-root and contains no secrets, cache, or generated output.
- [ ] Liveness succeeds before data initialization and remains cheap.
- [ ] Readiness returns `503` before initialization.
- [ ] The explicit initializer completes and validates its state.
- [ ] Transient source failures are retried within a bound, while permanent
  failures fail promptly.
- [ ] Exhausted live-source retries fail closed without fixture substitution.
- [ ] Any bootstrap artifact is immutable, provenance-bound, checksum-verified,
  and revalidated by the ordinary initializer before readiness.
- [ ] Private registry access is proven with the documented minimum-scope
  credential before expensive initialization begins.
- [ ] Repeating initialization is safe and reuses valid data.
- [ ] Readiness returns `200` only after initialization is valid.
- [ ] The stable fixture can be submitted through `POST /runs`.
- [ ] The run and output records contain immutable version and provenance facts.
- [ ] Output data is downloadable over HTTP without an internal path.
- [ ] GeoJSON, stable IDs, CRS, fields, units, and feature count validate.
- [ ] Unsupported selections fail explicitly rather than expanding scope.
- [ ] `datacompleetheid` is in range and its rule is documented.
- [ ] API, security, container, and end-to-end tests pass in CI.
- [ ] Deterministic model, real-source model, and full RDP evidence are reported
  separately, and all required lanes pass.
- [ ] Full-stack startup has an outer CI deadline based on measured valid clean
  and cached initialization times; source-level timeout and retry bounds remain
  model-owned.
- [ ] The handoff package is complete enough for integration without reading model internals.

Only after this gate passes should the Illuminator integration pin the model
version, add its service to Compose, configure the shared publisher, register
the GeoServer/frontend layer, and add full-stack smoke tests.

For the concrete evidence behind these requirements, see the
[PV integration lessons learned](pv-integration-lessons-learned.md).

## Standards Path Without Overengineering

The MVP intentionally uses GeoServer WMS/WFS for shared publication. It prepares
for the professional target by using stable web identifiers, GeoJSON feature
collections, explicit CRS and units, OpenAPI, linked metadata, and clear
provenance now.

This follows the practical direction of:

- the [Geonovum NLDT architecture](https://geonovum.github.io/NLDT-Architectuur/),
  with loosely coupled, containerable, API-speaking model and data components;
- the [Dutch API Design Rules](https://docs.geostandaarden.nl/api/API-Designrules/),
  for predictable resource APIs and documentation;
- the [Geonovum OGC API Features guideline](https://docs.geostandaarden.nl/api/ogc-api-features-guideline/),
  for feature-level web access, OpenAPI, metadata links, and explicit CRS;
- [OGC API Features](https://ogcapi.ogc.org/features/), as the later modern
  feature-access surface; and
- [DCAT-AP-NL 3.0](https://docs.geostandaarden.nl/dcat/dcat-ap-nl30/), as the
  later catalogue metadata exchange profile.

Full OGC API Features hosting, OGC API Processes, catalogue publication,
RDF/knowledge graphs, data-space connectors, event triggers, and detailed ISO
quality metadata are **LATER** capabilities. A model MUST preserve the IDs,
metadata, and provenance needed for those upgrades, but its first integration
MUST prioritize a small working system.
