# Heat network integration

Heat-net-map runs as an independent RDP model container and publishes six
separate evidence layers through the shared publisher. The model receives no
Postgres or GeoServer credentials. The publisher requests one bounded API run,
validates every output, synchronizes all six PostGIS tables in one transaction,
and registers each table in the existing `rdp` workspace and `rdp_postgis`
datastore.

## Pinned release

- repository: `JortGroen/Heat-net-map`
- release commit: `1f2b2c8b770e5c59efbed4ab58641b40b164845a`
- immutable tag: `sha-1f2b2c8b770e5c59efbed4ab58641b40b164845a`
- deployment digest: `sha256:2a1afe08732e98b00a880cad0ed3ffff2dbc8c38c960be4c643dd5358676dbda`
- model version: `0.2.0`
- API and schema contracts: `1.0.0`

The private package is pulled by digest. The model reports its embedded release
commit through `/metadata`; the platform separately records the deployment
digest with every published feature.

## Layer boundaries

- `reported_neighbourhood_heat_consumers`: registered aggregate shares and model estimates at neighbourhood resolution.
- `inferred_pc6_heat_consumers`: PC6 inference with corroboration, conflicts, exclusions, and estimated demand.
- `registered_heat_network_developments`: registered plans, not operating connections.
- `documented_actual_heat_sources`: documented operating production sites.
- `documented_large_heat_consumers`: documented examples without unsupported private consumption values.
- `potential_heat_sources`: candidate sources, not evidence of a connection.

Keeping these layers separate preserves the model's evidence semantics. The
dashboard groups them under one Heat evidence selector for usability without
merging their records or meanings.

## Runtime and publication

Production runs
`python -m heat_net_map.api initialize --mode real_source --run-model`. Local
development and CI explicitly run `--mode fixture --allow-fixture`; the model
does not silently fall back to fixture data. The API and initializer use UID/GID
`10001:10001`, a read-only root filesystem, dropped capabilities, and one
persistent `/data` volume.

The API client validates the model release, contract versions, snapshot, CRS,
data mode, six-layer catalog, byte sizes, SHA-256 hashes, feature identity,
geometry, canonical values, provenance, and model-owned
`datacompleetheid-heat-net-v1`. Only per-request UUIDs and timestamps are
excluded from content-change hashes. A second publication of the same snapshot
therefore reports zero changed features, while scientific or source changes
remain detectable.

The deterministic acceptance fixture contains one feature per layer. The
durable PC6 assertion is `pc6-1812ab`, 18 allocated connected dwellings, 414
GJ/year estimated heat demand, and `datacompleetheid` 2. Full integration CI
also verifies all six WFS schemas and features, WMS maps, registry records,
dashboard options, and the unchanged legacy scenario workflow.
