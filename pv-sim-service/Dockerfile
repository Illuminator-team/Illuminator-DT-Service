# Two stages: Poetry, pip and virtualenv only exist in the builder. The runtime image
# gets the locked dependencies (the same ones `poetry install` resolves from
# poetry.lock) and no package manager, so nothing there can install code and the
# scanner finds no pip/poetry/virtualenv packages to flag.
FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS builder
ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/app
RUN pip install --no-cache-dir "poetry~=2.3.4"
COPY src/poetry.lock src/pyproject.toml ./
RUN touch README.md \
    && poetry install --no-root --no-interaction \
    && /opt/app/.venv/bin/python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
RUN python -m pip uninstall -y pip setuptools wheel; rm -rf /root/.cache \
    && apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/app/.venv /opt/app/.venv
ENV PATH=/opt/app/.venv/bin:$PATH
WORKDIR /app
COPY src/pv_sim ./pv_sim

ENTRYPOINT ["python", "-m", "pv_sim"]
CMD ["-c", "config.yml"]
