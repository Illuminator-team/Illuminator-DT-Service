# Two stages: Poetry, pip and virtualenv only exist in the builder. The runtime image
# gets the locked dependencies (the same ones `poetry install` resolves from
# poetry.lock) and no package manager, so nothing there can install code and the
# scanner finds no pip/poetry/virtualenv packages to flag.
FROM python:3.11-slim@sha256:064f01707f2fc8b06bae86bb43875266c6e41bac7994e77ec5dc623c4a4d0545 AS builder
ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/app
RUN pip install --no-cache-dir "poetry~=2.3.4"
COPY src/poetry.lock src/pyproject.toml ./
RUN touch README.md \
    && poetry install --no-root --no-interaction \
    && /opt/app/.venv/bin/python -m pip check \
    && /opt/app/.venv/bin/python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache

FROM python:3.11-slim@sha256:064f01707f2fc8b06bae86bb43875266c6e41bac7994e77ec5dc623c4a4d0545
RUN python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache \
    && apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/app/.venv /opt/app/.venv
# Fail the build if a package manager is still importable in either interpreter.
RUN python -c "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))" \
    && /opt/app/.venv/bin/python -c "import importlib.util as u; assert all(u.find_spec(m) is None for m in ('pip','setuptools','wheel'))"
ENV PATH=/opt/app/.venv/bin:$PATH
WORKDIR /app
COPY src/illuminator_pv ./illuminator_pv

ENTRYPOINT ["python", "-m", "illuminator_pv"]
CMD ["-c", "config.yml"]
