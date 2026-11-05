# rdp-redsql with security updates on top of the base image:
#  - Alpine packages (libcurl, libexpat, openssl, ...),
#  - the vulnerable Python packages in its virtualenv,
#  - the bundled `uv` binary (an old rustls copy; not needed at runtime, which is plain
#    `python -m redsql`) and the system pip, which are removed.
FROM ait1/rdp-redsql@sha256:f703b663f0e9c50c82c4c7674c5e2b844283c86bb3cf51d01c5de432417c8991
USER root
RUN apk upgrade --no-cache \
    && uv pip install --python /usr/redsql/.venv/bin/python --no-cache --upgrade \
        "pygments>=2.20.0" "pytest>=9.0.3" "python-dotenv>=1.2.2" \
    && /usr/local/bin/python3 -m pip uninstall -y pip \
    && rm -f /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && rm -rf /root/.cache
USER redsql:redsql
