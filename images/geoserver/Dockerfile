# TEMPORARY. Remove when the official GeoServer 3.0.3 image is released (expected mid-December 2026)
# and switch the geo service back to docker.osgeo.org/geoserver@<digest>.
#
# The official 3.0.2 image unchanged, plus the Ubuntu package updates published after it was
# built. GeoServer, Tomcat and Java are not touched: they are not installed through apt.
FROM docker.osgeo.org/geoserver@sha256:5a372d4988116e8f62c71ae5ff6eb8d433967697670fb1dec15379bf476721fe
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*
