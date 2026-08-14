# Wind turbine integration

The Wind model is integrated as an independent RDP model container and a shared
GeoServer layer. The model remains usable on its own; it does not receive
Postgres or GeoServer credentials. The shared `layer-publisher` calls the model
API, verifies the returned artifact, writes the point features to PostGIS, and
registers `rdp:public_wind_turbines` in the existing `rdp` workspace and
`rdp_postgis` datastore.

## Pinned release

- repository: `JortGroen/Wind-turbine-map`
- release commit: `b89bd49c717a1e301954aa0b8c1bdb98a91f8d44`
- model-reported image: `ghcr.io/jortgroen/wind-turbine-map-api:sha-b89bd49c717a1e301954aa0b8c1bdb98a91f8d44`
- deployment digest: `sha256:820822bfa5300bc8e2126482147b1d430d075c1834bd080999334825caa21828`
- model version: `0.2.0`
- API and schema contracts: `1.0.0`

The distinction between the reported image tag and deployment digest is
intentional. The model embeds the immutable commit tag as its release identity;
Compose independently pins the registry artifact by digest.

## Runtime modes

Production runs `python -m wind_turbine_map.api.initialize --mode real` against
the bounded Alkmaar sources. Local development and CI explicitly enable and
mount the model-owned four-turbine fixture. Fixture mode cannot be selected by
accident because it requires both `WIND_API_ALLOW_FIXTURE=true` and
`--allow-fixture`.

Both initializer and API run as UID/GID `10001:10001`, use a read-only root
filesystem, drop Linux capabilities, and write only to the persistent `/data`
volume. The model receives no shared platform credentials.

## Publication checks

The publisher validates model, release, contract, CRS, data mode, field, unit,
quality, feature-ID, point-geometry, byte-size, and SHA-256 identities before a
database update. Publication uses staging plus upsert/delete synchronization;
unchanged repeated runs report zero changed and zero deleted features.

The integration smoke test proves the model API, the four-feature fixture,
`wind-turbine-2811`, WFS schema and feature retrieval, WMS rendering, registry
metadata, dashboard control, and persistent scenario controls. The fixture's
position `[4.7523, 52.593]` and positive capacity are durable assertions; model
estimates are deliberately not pinned to exact future values.
