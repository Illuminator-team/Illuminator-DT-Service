# Grafana with the current Alpine security updates (curl, openssl, ... in the base).
FROM grafana/grafana-oss@sha256:2e986801428cd689c2358605289c90ab37d2b39e24808874971f54c99bcdc412
USER root
RUN apk upgrade --no-cache
USER 472
