# langgraph_sandbox/artifacts/api.py
"""
FastAPI Artifact Serving Endpoints

This module provides REST API endpoints for serving artifacts to clients.
It implements a secure, token-based file serving system that allows clients
to download artifacts without exposing direct file paths or allowing
unauthorized access.

Key features:
- Token-based authentication (prevents unauthorized access)
- Content streaming (efficient for large files)
- Metadata-only endpoints (for file info without download)
- Proper HTTP status codes and error handling
- MIME type detection and proper headers

Endpoints:
- GET /artifacts/{artifact_id} - Download the actual file
- GET /artifacts/{artifact_id}/head - Get file metadata only

Security:
- Each request requires a valid, signed token
- Tokens are tied to specific artifact IDs
- Tokens have expiration times 
- No direct file path exposure
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import sqlite3

from .store import _resolve_paths
from .tokens import verify_token

# Create router with prefix and tags for API documentation
router = APIRouter(prefix="/artifacts", tags=["artifacts"])

def _db() -> sqlite3.Connection:
    """
    Create a database connection using the configured paths.
    
    Returns:
        SQLite connection with foreign key constraints enabled
    """
    paths = _resolve_paths()
    conn = sqlite3.connect(paths["db_path"])
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    """
    Convert SHA-256 hash to blob storage path.
    
    Uses the same two-level directory structure as the storage system:
    - First 2 characters: top-level directory
    - Next 2 characters: second-level directory
    - Full hash: filename
    
    Args:
        blob_dir: Base directory for blob storage
        sha256: SHA-256 hash of the file content
    
    Returns:
        Path object pointing to the blob storage location
    """
    return Path(blob_dir) / sha256[:2] / sha256[2:4] / sha256

@router.get("/{artifact_id}")
def download_artifact(artifact_id: str, token: str = Query(...)):
    """
    Download an artifact file.
    
    This endpoint serves the actual file content to the client. It performs
    several security checks and then streams the file back to the requester.
    
    Security checks:
    1. Verify the token is valid and not expired
    2. Ensure the token matches the requested artifact ID
    3. Check that the artifact exists in the database
    4. Verify the file exists on disk
    
    Args:
        artifact_id: The unique identifier for the artifact (e.g., "art_abc123")
        token: Signed token for authentication (query parameter)
    
    Returns:
        FileResponse with the actual file content
    
    Raises:
        HTTPException: 401 if token is invalid, 403 if token doesn't match,
                      404 if artifact not found, 410 if file is missing
    """
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
    """
    Get artifact metadata without downloading the file.
    
    This endpoint returns only the metadata about an artifact (size, MIME type,
    filename, etc.) without actually serving the file content. Useful for:
    - Checking if a file exists before downloading
    - Getting file information for UI display
    - Pre-flight checks before large downloads
    
    Args:
        artifact_id: The unique identifier for the artifact
        token: Signed token for authentication (query parameter)
    
    Returns:
        JSONResponse with artifact metadata
    
    Raises:
        HTTPException: 401 if token is invalid, 403 if token doesn't match,
                      404 if artifact not found
    """
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
