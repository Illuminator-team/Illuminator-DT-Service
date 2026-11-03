FROM python:3.10-slim

WORKDIR /app

RUN pip install --upgrade pip --progress-bar off \
    && pip install poetry~=2.3.4 --progress-bar off

RUN touch README.md
COPY src/poetry.lock src/pyproject.toml ./
RUN poetry install --no-root
COPY src/pv_sim ./pv_sim

ENTRYPOINT ["poetry", "run", "python", "-m", "pv_sim"]
CMD ["-c", "config.yml"]
