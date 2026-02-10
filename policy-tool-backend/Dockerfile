# policy-tool-backend/Dockerfile
FROM python:3.11-slim

# Install system dependencies for GIS and Postgres communication
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code and the api.py entry point
COPY . .

# Ensure the output directory exists so the mount point is ready
RUN mkdir -p /app/data/processed

# Start the API on port 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]