# sandbox/Dockerfile
FROM python:3.11-slim

# libs available IN the sandbox (importable by user code)
RUN pip install --no-cache-dir numpy pandas matplotlib seaborn scikit-learn scikit-image geopandas shapely pyarrow scipy statsmodels fastapi uvicorn

# non-root user
RUN useradd -m -u 1000 sandbox
WORKDIR /app

# REPL server that keeps state in RAM
COPY src/sandbox/repl_server.py /app/repl_server.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER sandbox

EXPOSE 9000
CMD ["uvicorn", "repl_server:app", "--host", "0.0.0.0", "--port", "9000"]
