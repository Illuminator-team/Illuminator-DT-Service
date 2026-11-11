---
title: "Vulnerability Applicability Assessment: third-party container images"
subtitle: "Illuminator Digital Twin Service, reformers01.ewi.tudelft.nl"
date: "Scan of 11 November 2026"
---

# Vulnerability Applicability Assessment

## Scope

This document assesses the **critical and high** findings that remain in the **third-party (vendor) container images** of the Illuminator Digital Twin Service deployment on `reformers01.ewi.tudelft.nl` (Docker Compose project `illuminator-dev`).

The images are used unmodified. Our policy is not to build our own images of software we did not develop, so a finding is fixed by adopting a newer vendor release, never by patching the image ourselves. Before this assessment every vendor image was updated to the newest release available, and each image is pinned by digest.

The images built from the project's own repositories are **not** part of this document. Their findings are fixed in the source repositories and resolved by rebuilding; that work is tracked in the repositories' issue trackers.

## Scan

- Scanner: Trivy 0.76.2, `trivy image --ignore-unfixed` on the exact image IDs of the running containers.
- Only findings for which a fixed version exists are reported (`--ignore-unfixed`).
- The raw Trivy reports are stored next to this document: `docs/security/scans/2026-11-11/*.json.gz`.

## Method

Each critical and high finding is assigned to an assessment rule. A rule groups findings that share the same affected component and the same reasoning, for example all Go standard-library findings in a binary that is never executed. A finding is assessed with these questions:

1. **Is the vulnerable component loaded or executed in this deployment?** Checked against the running processes, their command lines, loaded libraries and configuration.
2. **Can an attacker reach the vulnerable code path?** This considers network exposure (only Traefik publishes ports to the outside; see each image), authentication, and whether the input is attacker-controlled.
3. **What limits the impact?** For example TLS termination at the reverse proxy, required login, or a localhost-only binding.

Verdicts:

| Verdict | Meaning |
|---|---|
| Not affected | The vulnerable code is not present, not executed, or cannot be reached by an attacker in this deployment. A justification from the CISA VEX vocabulary is given. |
| Affected, mitigated | The vulnerable code runs, but exploitation is prevented or strongly limited by the deployment (exposure, authentication, configuration). The vendor fix is adopted when released. |
| Affected, action needed | The finding is exploitable in this deployment and needs action beyond waiting for the vendor. |
| Under investigation | Applicability could not be established yet. |

Every rule lists the evidence it relies on (commands run against the deployment and their results). The report generator (`scripts/security_report.py`) refuses to produce the report if a critical or high finding is not covered by a rule, so new findings in a later scan cannot be missed.

## Network exposure overview

| Service | Reachable from the internet | Notes |
|---|---|---|
| Traefik (reverse proxy) | Yes, ports 80/443 | Terminates TLS; its API/dashboard is bound to 127.0.0.1 |
| nginx (dashboard) | Via Traefik, `/dashboard` | Static files only |
| GeoServer | Via Traefik, `/geoserver` | Anonymous read; admin login for writes and the admin UI/REST API |
| Grafana | Via Traefik, `/grafana` | Login required |
| TimescaleDB | No | Internal network; 127.0.0.1:5432 and 127.0.0.1:5433 on the host |
| Redis | No | Internal network only; password required |
| RedisInsight | No | 127.0.0.1:5540 and 127.0.0.1:5541 on the host only. No login of its own and preconfigured with the Redis connection, so any local user of the server can use it (see the RedisInsight section) |
