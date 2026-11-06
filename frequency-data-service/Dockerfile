FROM ait1/rdp-data-crawler@sha256:4f564e68c85937ef1513a15326ba02b5024b24e1cc734cf5ca7a4c21f037507c

COPY ./src ./frequency_data_service

# Security updates on top of the base image: OS packages, the crawler's vulnerable
# Python dependencies (installed into its virtualenv by the base image), and the
# system pip, which is not needed at runtime and whose bundled SBOM lists old copies.
# The four overrides are the exact versions tested on the dev server; urllib3 stays
# below 3 and msgpack below 2 (requests and CacheControl in the base require that), and
# `pip check` must pass on the resulting venv before pip is removed.
RUN apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/* \
    && pip --python /app/.venv/bin/python install --no-cache-dir \
        "certifi==2026.10.23" "urllib3==2.8.0" "filelock==4.2.9" "msgpack==1.2.4" \
    && pip --python /app/.venv/bin/python check \
    && /usr/local/bin/python3 -m pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache \
    && /usr/local/bin/python3 -c "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))"
