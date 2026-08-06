# PV Integration Lessons Learned

## Purpose

This record captures lessons from the first attempt to integrate PV-MAP as an
independent Illuminator model. The
[model developer integration guide](model-developer-integration-guide.md) is the
normative checklist; this document records the evidence behind new rules.

Evidence:

- Illuminator draft PR: <https://github.com/Illuminator-team/Illuminator-DT-Service/pull/14>
- PV resilience PR: <https://github.com/JortGroen/PV-MAP/pull/10>
- failed full-stack run: <https://github.com/Illuminator-team/Illuminator-DT-Service/actions/runs/31024373154>
- PV source commit: `d9cd7920108d76b7d645c22b33d8cf26c35fc040`
- PV image: `ghcr.io/jortgroen/pv-map-api@sha256:d561cb0defef3872c97e348f3c7490cbbdf6f6b810675f7dfa01495ce980feb9`

PR 14 remained draft and was not merged or deployed because its complete gate
did not pass.

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
is a model-owned, immutable, provenance-checked source-cache bootstrap. It is
not yet complete or verified.

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
   owned elsewhere. Use the minimum scope and never copy a token into Compose,
   an image, PR text, or logs.
6. **One immutable identity flows through every boundary.** The reviewed commit,
   OCI digest, runtime identity, model metadata, layer manifest, and test
   expectations must agree.
7. **A strict failed gate is useful evidence.** Never substitute fixture data,
   ignore initializer failure, or publish a partial layer to make CI green.

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

- Complete and review the PV-MAP source-cache bootstrap PR.
- Produce the first cache artifact from a successful real-source run.
- Publish and pin a new verified PV image and cache identity.
- Rerun the complete Illuminator PR 14 gate.
- Add an outer CI startup deadline after measuring valid clean and cached runs.
- Keep PR 14 draft and undeployed until the complete gate passes.