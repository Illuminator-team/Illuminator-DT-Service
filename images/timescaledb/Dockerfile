# TEMPORARY. Remove when a timescale/timescaledb-ha release ships current builds of these tools
# and packages, and switch the timescale service back to timescale/timescaledb-ha@<digest>.
#
# The official image unchanged (PostgreSQL 17.11, TimescaleDB 2.31, PostGIS 3.6), minus three
# tools and a default key pair this deployment never uses, plus Ubuntu package updates:
#  - pgbackrest_exporter and pgbouncer_exporter (Prometheus exporters for the HA/Patroni setup)
#    and yq: no entrypoint or init script calls them.
#  - ssl-cert-snakeoil: the shared default key pair of the ssl-cert package. This deployment does
#    not use it; only commented-out Patroni template lines mention it.
#  - Ubuntu packages are upgraded by name, not with a blanket `apt-get upgrade`: that would also
#    move the PostgreSQL packages from the PGDG repository to a new minor release, under the
#    extensions built for 17.11. glibc and locales are deliberately left as shipped: a glibc
#    change can alter collation and so the order of PostgreSQL text indexes.
FROM timescale/timescaledb-ha@sha256:3f0b3f6bdf4912878444a36e6113a18346309583c4d1a61d81a0c511342a1afd
USER root
RUN rm -f /usr/bin/pgbackrest_exporter /usr/local/bin/pgbouncer_exporter /usr/local/bin/yq \
        /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install --only-upgrade \
        apt libapt-pkg6.0 libmysqlclient21 libpcre2-8-0 \
        libgssapi-krb5-2 libk5crypto3 libkrb5-3 libkrb5support0 libexpat1 libtiff5 libdav1d5 \
        libdebuginfod-common libdebuginfod1 libdw1 libelf1 \
        perl perl-base perl-modules-5.34 libperl5.34 \
        python3-oauthlib python3-pyasn1 python3-jwt \
    && rm -rf /var/lib/apt/lists/*
USER postgres
