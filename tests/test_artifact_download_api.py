# tests/test_artifact_download_api.py
import os, sqlite3
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from langgraph_sandbox.artifacts.store import ensure_artifact_store
from langgraph_sandbox.artifacts.ingest import ingest_files
from langgraph_sandbox.artifacts.api import router as artifacts_router
from langgraph_sandbox.artifacts.tokens import create_token

def make_app() -> FastAPI:
    app = FastAPI()
    ensure_artifact_store()
    app.include_router(artifacts_router)
    return app

def test_download_flow(tmp_path, monkeypatch):
    # isolated store
    db_path = tmp_path / "artifacts.db"
    blob_dir = tmp_path / "blobstore"
    monkeypatch.setenv("ARTIFACTS_DB_PATH", str(db_path))
    monkeypatch.setenv("BLOBSTORE_DIR", str(blob_dir))
    monkeypatch.setenv("ARTIFACTS_TOKEN_SECRET", "test-secret")

    app = make_app()
    client = TestClient(app)

    # create a staged file and ingest
    sid = "sid_abc"
    staging = tmp_path / "sessions" / sid / "artifacts"
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / "hello.txt"
    f.write_text("hello api\n", encoding="utf-8")

    descs = ingest_files([f], session_id=sid, run_id="run1")
    art = descs[0]
    art_id = art["id"]

    # head requires token
    token = create_token(art_id)
    r = client.get(f"/artifacts/{art_id}/head", params={"token": token})
    assert r.status_code == 200
    meta = r.json()
    assert meta["id"] == art_id
    assert meta["filename"] == "hello.txt"
    assert meta["size"] > 0

    # download
    r2 = client.get(f"/artifacts/{art_id}", params={"token": token})
    assert r2.status_code == 200
    assert r2.content == b"hello api\n"

    # invalid token
    r3 = client.get(f"/artifacts/{art_id}", params={"token": "bad"})
    assert r3.status_code in (401, 403, 400)
