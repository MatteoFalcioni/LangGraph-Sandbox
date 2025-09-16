# langgraph_sandbox/artifacts/api.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import sqlite3

from .store import _resolve_paths
from .tokens import verify_token

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

def _db() -> sqlite3.Connection:
    paths = _resolve_paths()
    conn = sqlite3.connect(paths["db_path"])
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    return Path(blob_dir) / sha256[:2] / sha256[2:4] / sha256

@router.get("/{artifact_id}")
def download_artifact(artifact_id: str, token: str = Query(...)):
    # 1) Verify token (artifact_id must match)
    try:
        data = verify_token(token)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if data["artifact_id"] != artifact_id:
        raise HTTPException(status_code=403, detail="Token does not match artifact")

    # 2) Look up sha + mime + filename in DB
    paths = _resolve_paths()
    with _db() as conn:
        row = conn.execute(
            "SELECT sha256, mime, filename FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Artifact not found")
        sha, mime, filename = row

    # 3) Resolve blob on disk
    blob = _blob_path_for_sha(paths["blob_dir"], sha)
    if not blob.exists():
        raise HTTPException(status_code=410, detail="Blob missing (pruned?)")

    # 4) Stream it
    return FileResponse(
        path=str(blob),
        media_type=mime or "application/octet-stream",
        filename=filename or artifact_id,
    )

@router.get("/{artifact_id}/head")
def head_artifact(artifact_id: str, token: str = Query(...)):
    # Same token check; return metadata only (no file)
    try:
        data = verify_token(token)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if data["artifact_id"] != artifact_id:
        raise HTTPException(status_code=403, detail="Token does not match artifact")

    paths = _resolve_paths()
    with _db() as conn:
        row = conn.execute(
            "SELECT sha256, mime, filename, size, created_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Artifact not found")
        sha, mime, filename, size, created_at = row

    return JSONResponse({
        "id": artifact_id,
        "sha256": sha,
        "mime": mime,
        "filename": filename,
        "size": size,
        "created_at": created_at,
    })
