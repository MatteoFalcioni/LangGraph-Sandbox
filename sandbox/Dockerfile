# sandbox/Dockerfile
FROM python:3.11-slim

# install libs you want available in the sandbox
RUN pip install --no-cache-dir numpy pandas matplotlib geopandas

# Create non-root user
RUN useradd -m -u 1000 sandbox
WORKDIR /work

# Security-hardening basics
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER sandbox
