# policy-tool-backend/Dockerfile
FROM python:3.11-slim

# OS security updates. No compiler or libpq headers: every dependency installs from a
# wheel (psycopg2-binary bundles libpq), and gcc/libpq-dev pulled in kernel headers and Kerberos.
RUN apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache

# Copy all source code and the api.py entry point
COPY . .

# Ensure the output directory exists so the mount point is ready
RUN mkdir -p /app/data/processed

# Start the API on port 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]