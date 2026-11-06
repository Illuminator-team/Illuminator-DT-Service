# GeoServer with the OS packages brought up to date and the kernel headers removed.
# kartoza/geoserver ships linux-libc-dev (C kernel headers, not used at runtime), which
# accounts for most of the image's scanner findings; removing it and applying the
# current Ubuntu security updates keeps the runtime unchanged.
FROM kartoza/geoserver:2.28.5@sha256:a500f30ec973014be203851290e89996cfccfe4335b1b4345047f64eda05521d

RUN apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && apt-get -y purge linux-libc-dev \
    && apt-get -y autoremove --purge \
    && rm -rf /var/lib/apt/lists/*
