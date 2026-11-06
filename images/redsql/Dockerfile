# rdp-redsql with security updates on top of the base image:
#  - Alpine packages (libcurl, libexpat, openssl, ...),
#  - the dev-only test tooling removed from its virtualenv (the base installs its `dev`
#    dependency group: pytest, pytest-cov and what they pull in; the runtime is plain
#    `python -m redsql` and imports none of it),
#  - python-dotenv raised to the version tested on the dev server (the one
#    runtime package with a fix available),
#  - the bundled `uv` binary (an old rustls copy; not needed at runtime) and the system
#    pip, which are removed after `uv pip check` has confirmed the venv is consistent.
FROM ait1/rdp-redsql@sha256:f703b663f0e9c50c82c4c7674c5e2b844283c86bb3cf51d01c5de432417c8991
USER root
RUN apk upgrade --no-cache \
    && uv pip uninstall --python /usr/redsql/.venv/bin/python \
        pytest pytest-cov coverage pluggy iniconfig pygments \
    && uv pip install --python /usr/redsql/.venv/bin/python --no-cache "python-dotenv==1.2.4" \
    && uv pip check --python /usr/redsql/.venv/bin/python \
    && /usr/local/bin/python3 -m pip uninstall -y pip \
    && rm -f /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && rm -rf /root/.cache \
    && /usr/local/bin/python3 -c "import importlib.util as u; assert u.find_spec('pip') is None" \
    && /usr/redsql/.venv/bin/python -c "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pytest','pygments','pluggy','coverage'))"
USER redsql:redsql
