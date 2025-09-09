FROM python:3.11-slim

RUN pip install --no-cache-dir numpy pandas matplotlib geopandas pyarrow fastapi uvicorn

RUN useradd -m -u 1000 sandbox
WORKDIR /app

COPY src/repl_server.py /app/repl_server.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER sandbox

EXPOSE 9000
CMD ["uvicorn", "repl_server:app", "--host", "0.0.0.0", "--port", "9000"]
