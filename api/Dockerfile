FROM python:3.11-slim

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry

# Make sure Poetry is in PATH
ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONPATH=/app

# Copy pyproject and lock
COPY ./pyproject.toml ./poetry.lock* /app/

# Install dependencies
RUN poetry install --no-root

# Copy code
COPY . /app/

# Run the app
CMD ["poetry", "run", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
