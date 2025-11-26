FROM python:3.10-slim

WORKDIR /app

RUN pip install poetry~=2.1.2 --progress-bar off

RUN touch README.md
COPY src/poetry.lock src/pyproject.toml ./
RUN poetry install --no-root
COPY src/illuminator_pv ./illuminator_pv

ENTRYPOINT ["poetry", "run", "python", "-m", "illuminator_pv"]
CMD ["-c", "config.yml"]
