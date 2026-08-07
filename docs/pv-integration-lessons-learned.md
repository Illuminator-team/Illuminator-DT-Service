# PV Integration Lessons Learned

## Purpose

This record captures lessons from the first attempt to integrate PV-MAP as an
independent Illuminator model. The
[model developer integration guide](model-developer-integration-guide.md) is the
normative checklist; this document records the evidence behind new rules.

Evidence:

- Illuminator draft PR: <https://github.com/Illuminator-team/Illuminator-DT-Service/pull/14>
- PV resilience PR: <https://github.com/JortGroen/PV-MAP/pull/10>
- PV cache-bootstrap PR: <https://github.com/JortGroen/PV-MAP/pull/12>
- failed live-source run: <https://github.com/Illuminator-team/Illuminator-DT-Service/actions/runs/31024373154>
- failed publisher-SQL run: <https://github.com/Illuminator-team/Illuminator-DT-Service/actions/runs/31107449535>
- failed publisher-packaging run: <https://github.com/Illuminator-team/Illuminator-DT-Service/actions/runs/31109126622>
- successful full-stack run: <https://github.com/Illuminator-team/Illuminator-DT-Service/actions/runs/31110105407>
- PV source commit: `bd29351e108d9db002b9e54d5c7fb2356416a306`
- PV API image: `ghcr.io/jortgroen/pv-map-api@sha256:0fffb8dd6e725956257c4dc51c94225ea7c5745478ed33cf8bce597ee8551710`
- PV source-cache image: `ghcr.io/jortgroen/pv-map-source-cache@sha256:e432f76ad7b6dfd67bb55c52445d985027c3a87f3de6e5502bedb1c236c8620b`

PR 14 remained draft and undeployed while its complete gate was failing. The
final full-stack run passed; the PR can now leave draft state for review, but
it is not merged or deployed by this evidence update.

## What Happened

The integration first could not pull the private PV image. A dedicated GitHub
token limited to `read:packages` was stored as the encrypted repository secret
`JORT_PRIVATE_DOCKER_IMAGES`. The workflow then authenticated to GHCR and
pulled the digest-pinned image. No token value entered Git or logs.

The real-data initializer then failed with an unspecific connection timeout.
PV-MAP PR 10 added bounded retries, reusable source-cache behavior, and
sanitized source-specific diagnostics. A replacement image passed the model
repository unit, API end-to-end, and container-image gates.

The next Illuminator run passed contracts, dashboard tests, authentication,
credential setup, and Compose validation. The initializer reached
`source=3dbag-roof-surfaces` and exhausted four attempts with
`failure_type=ConnectTimeout`. Smoke and publisher-idempotence checks were
correctly skipped, and cleanup succeeded.

The supported WFS endpoint `https://data.3dbag.nl/api/BAG3D/wfs` was also
unreachable from the developer environment. The responding experimental API
uses a different CityJSON data path and is not a safe transport-only
substitution because it could change scientific outputs. The selected follow-up
is a model-owned, immutable, provenance-checked source-cache bootstrap.

PV-MAP PR 12 implemented that bootstrap. On 6 August 2026, the existing
release-bound public-source snapshot was exported into an allow-listed bundle,
validated, built as a separate private cache image, pulled back by digest, and
used with networking disabled. The ordinary initializer produced 66 Alkmaar
buurt features with a total of 108,327.8 kWp for source period `2025JJ00`.
The exact API image then passed real HTTP acceptance against the reconstructed
cache. The bundle contains 228 files (995,731,099 bytes) with fingerprint
`775c9ee5868ef15b1139f4739add58b4d7a376faeefbcf18cfccd88f5a95cf0b`.

This first cache adopts a previously successful July 2026 real-source cache;
it was not produced by a new live-source download on 6 August. That limitation
is recorded rather than hidden. A future routine refresh should create the next
cache image from a clean trusted-network run and repeat the same acceptance.

The first cache-backed Illuminator run reached the publisher but exposed an
extra closing parenthesis in the PostGIS bulk-insert template. The next run
showed that the corrected SQL helper passed host tests but had not been copied
into the publisher image. The SQL expression was made explicit and shared,
tests now pin its balanced shape, and the publisher Dockerfile test requires
the helper to be packaged. The final run passed model initialization, PC6 and
PV WMS/WFS smoke checks, artifact integrity, GeoServer publication, repeatable
publisher execution, and cleanup.

## Durable Lessons

1. **Model CI and RDP acceptance prove different things.** A deterministic
   fixture proves API and output contracts. It does not prove that a fresh
   deployment can acquire and process every real source.
2. **Retries improve resilience, not reachability.** Repeated timeouts provide
   better evidence but do not make a persistently unreachable host usable.
3. **Source bootstrap is model-owned.** RDP must not embed model-specific data
   workarounds. The model must validate whether cached bytes remain
   scientifically compatible.
4. **Code and data artifacts have separate lifecycles.** The API image contains
   code and dependencies, not source caches. Record code-image and cache-artifact
   digests separately.
5. **Private package access must be designed explicitly.** Do not assume an
   integration repository's automatic `GITHUB_TOKEN` can pull a private package
   owned elsewhere. One read-only deployment credential may cover multiple
   packages its identity can access; use the minimum scope and never copy the
   token into Compose, an image, PR text, or logs.
6. **One immutable identity flows through every boundary.** The reviewed commit,
   OCI digest, runtime identity, model metadata, layer manifest, and test
   expectations must agree.
7. **A strict failed gate is useful evidence.** Never substitute fixture data,
   ignore initializer failure, or publish a partial layer to make CI green.
8. **Exercise real geometry through the database.** Parser and API fixtures do
   not validate a bulk PostGIS expression. Keep the SQL template test and the
   full publication smoke check.
9. **Test the built image, not only the checkout.** Explicit Dockerfile copy
   lists can omit a new imported module even when host tests pass. Container
   gates must import or start the packaged application.

## Required Promotion Lanes

Future model integrations use cumulative lanes:

1. **Deterministic model:** network-free or fixture-backed calculation, API,
   security, and container tests on every model PR.
2. **Real-source model:** dated clean initialization against authoritative
   sources, stable fixture acceptance, provenance, and a cached rerun.
3. **Artifacts:** reviewed API image by immutable digest and, when needed, a
   separately verified source-cache artifact by immutable digest.
4. **RDP integration:** private image retrieval, initialization, API readiness,
   PostGIS/GeoServer publication, registry/dashboard validation, and repeatable
   publication in one full-stack run.
5. **Release:** merge to `dev` only through a PR after lane 4. Promotion to
   `main` and deployment remain explicit decisions.

Passing an earlier lane never substitutes for a later lane.

## Cache Bootstrap Requirements

A source-cache bundle or cache image must:

- be produced by a successful real-source initialization on a trusted network;
- remain outside the code repository and normal API image;
- be immutable and checksum-verified;
- record model, configuration, source-contract, producer, retrieval, and
  per-file provenance;
- exclude credentials, readiness markers, locks, temporary files, generated
  outputs, and unrelated caches;
- reject traversal, links, tampering, drift, and conflicting cache files; and
- run the ordinary initializer after import so only normal model validation can
  create readiness.

## Open Follow-Up

- Produce the next cache artifact from a fresh clean run on a trusted network.
- Add an outer CI startup deadline after measuring valid clean and cached runs.
- Keep promotion to `main` and deployment as separate explicit decisions.
