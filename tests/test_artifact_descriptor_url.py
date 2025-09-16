# tests/test_artifact_descriptor_url.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

from langgraph_sandbox.artifacts.store import ensure_artifact_store
from langgraph_sandbox.artifacts.ingest import ingest_files
from langgraph_sandbox.artifacts.api import router as artifacts_router

def make_app() -> FastAPI:
    app = FastAPI()
    ensure_artifact_store()
    app.include_router(artifacts_router)
    return app

def test_descriptor_includes_working_url(tmp_path, monkeypatch):
    # Isolated store + public base for token URLs
    db_path = tmp_path / "artifacts.db"
    blob_dir = tmp_path / "blobstore"
    monkeypatch.setenv("ARTIFACTS_DB_PATH", str(db_path))
    monkeypatch.setenv("BLOBSTORE_DIR", str(blob_dir))
    monkeypatch.setenv("ARTIFACTS_TOKEN_SECRET", "secret")
    # TestClient uses http://testserver as base
    monkeypatch.setenv("ARTIFACTS_PUBLIC_BASE_URL", "http://testserver")

    app = make_app()
    client = TestClient(app)

    # Stage a file and ingest
    sid = "sid_url"
    staging = tmp_path / "sessions" / sid / "artifacts"
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / "hello.txt"
    f.write_text("hi\n", encoding="utf-8")

    descs = ingest_files([f], session_id=sid, run_id="run1")
    assert len(descs) == 1
    d = descs[0]
    assert "url" in d and d["url"].startswith("http://testserver/artifacts/")

    # The URL should be directly fetchable by the TestClient
    r = client.get(d["url"])
    assert r.status_code == 200
    assert r.content == b"hi\n"
