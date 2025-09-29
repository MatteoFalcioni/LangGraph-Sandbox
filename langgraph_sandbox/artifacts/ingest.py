# langgraph_sandbox/artifacts/ingest.py
"""
Artifact Ingestion System

This module handles the process of taking files from the sandbox staging area and
properly storing them in the artifact system. It's the bridge between temporary
files created by agents and the permanent artifact storage.

The ingestion process:
1. Takes files from staging folder (/session/artifacts inside the container)
2. Computes SHA-256 fingerprint for deduplication
3. Stores files in content-addressed blobstore (blobstore/ab/cd/abcdef...)
4. Records metadata in SQLite database
5. Creates links between artifacts and sessions/runs
6. Cleans up original files from staging area
7. Returns artifact descriptors with download URLs

Key features:
- Content deduplication (same file content = same storage)
- Session tracking (which artifacts belong to which conversation)
- Size limits (prevents huge files from consuming storage)
- Atomic operations (all-or-nothing for each file)
- Cleanup (removes staging files after successful ingestion)

Environment variables (optional):
- ARTIFACTS_DB_PATH: path to SQLite db (default: <project>/artifacts.db)
- BLOBSTORE_DIR: blob folder (default: <project>/blobstore)
- MAX_ARTIFACT_SIZE_MB: per-file size cap (default: 50 MB)
"""

from __future__ import annotations
import os
import sqlite3
import hashlib
import mimetypes
import uuid
from pathlib import Path
from typing import Iterable, List, Dict, Optional
from datetime import datetime, timezone

from .store import _resolve_paths, _connect 
from .tokens import create_download_url


# ---------- small helpers ----------

def _now_iso() -> str:
    """
    Get current timestamp in ISO format.
    
    Returns:
        ISO 8601 formatted timestamp string (e.g., "2024-01-01T12:00:00+00:00")
    """
    return datetime.now(timezone.utc).isoformat()

def _gen_artifact_id() -> str:
    """
    Generate a unique, human-readable artifact ID.
    
    Format: "art_" + 24 hex characters from UUID
    Example: "art_abc123def456789012345678"
    
    Returns:
        Unique artifact identifier string
    """
    # short, unique, human-ish
    return "art_" + uuid.uuid4().hex[:24]

def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    Compute SHA-256 hash of a file for content fingerprinting.
    
    Reads the file in chunks to handle large files efficiently without
    loading the entire file into memory at once.
    
    Args:
        path: Path to the file to hash
        chunk_size: Size of each chunk to read (default: 1MB)
    
    Returns:
        SHA-256 hash as hexadecimal string
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()

def _blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    """
    Convert SHA-256 hash to blob storage path.
    
    Uses a two-level directory structure to avoid too many files in one directory:
    - First 2 characters: top-level directory
    - Next 2 characters: second-level directory
    - Full hash: filename
    
    Example: sha256="abc123..." → "blobstore/ab/c1/abc123..."
    
    Args:
        blob_dir: Base directory for blob storage
        sha256: SHA-256 hash of the file content
    
    Returns:
        Path object pointing to the blob storage location
    """
    # e.g., blobstore/ab/cd/abcdef...
    a, b = sha256[:2], sha256[2:4]
    return blob_dir / a / b / sha256

def _ensure_parent(p: Path) -> None:
    """
    Ensure the parent directory of a path exists.
    
    Creates all necessary parent directories if they don't exist.
    Equivalent to `mkdir -p` in Unix.
    
    Args:
        p: Path whose parent directory should exist
    """
    p.parent.mkdir(parents=True, exist_ok=True)

def _sniff_mime(path: Path) -> str:
    """
    Detect MIME type of a file based on its extension.
    
    Uses Python's mimetypes module to guess the MIME type.
    Falls back to "application/octet-stream" for unknown types.
    
    Args:
        path: Path to the file
    
    Returns:
        MIME type string (e.g., "image/png", "text/csv", "application/octet-stream")
    """
    mt, _ = mimetypes.guess_type(path.name)
    return mt or "application/octet-stream"

def _max_bytes() -> int:
    """
    Get maximum file size limit in bytes.
    
    Reads from MAX_ARTIFACT_SIZE_MB environment variable.
    Defaults to 50 MB if not set.
    
    Returns:
        Maximum file size in bytes
    """
    # default 50 MB
    mb = int(os.getenv("MAX_ARTIFACT_SIZE_MB", "50"))
    return mb * 1024 * 1024


# ---------- core ingest ----------

def ingest_files(
    new_host_files: Iterable[Path],
    *,
    session_id: str,
    run_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict]:
    """
    Ingest files from staging area into the artifact system.
    
    This is the main entry point for artifact ingestion. It takes files from the
    sandbox staging area and properly stores them in the artifact system with
    deduplication, metadata tracking, and cleanup.
    
    The process for each file:
    1. Check file size (skip if too large)
    2. Compute SHA-256 hash for deduplication
    3. Store file in content-addressed blobstore
    4. Record metadata in database
    5. Create link between artifact and session
    6. Clean up original staging file
    7. Return artifact descriptor
    
    Args:
        new_host_files: List of file paths from the staging area (HOST paths)
        session_id: Unique identifier for the conversation/session
        run_id: Optional identifier for the specific LangGraph run
        tool_call_id: Optional identifier for the specific tool call
    
    Returns:
        List of artifact descriptors, each containing:
        - id: Artifact ID (None if file was too large)
        - name: Original filename
        - mime: MIME type
        - size: File size in bytes
        - sha256: Content hash (None if file was too large)
        - created_at: ISO timestamp
        - url: Download URL (if environment is configured)
        - error: Error message (if file was too large)
    """
    paths = _resolve_paths()
    blob_dir = paths["blob_dir"]
    db_path = paths["db_path"]

    descriptors: List[Dict] = []
    max_bytes = _max_bytes()

    # Normalize to Path objects and filter out non-files
    new_paths = [Path(p) for p in new_host_files if p and Path(p).is_file()]

    with _connect(db_path) as conn:
        for src in new_paths:
            size = src.stat().st_size
            if size > max_bytes:
                # Skip too-big files gracefully (you can also raise if you prefer)
                # We do NOT delete the source file here; let the caller decide.
                descriptors.append({
                    "id": None,
                    "name": src.name,
                    "mime": _sniff_mime(src),
                    "size": size,
                    "sha256": None,
                    "created_at": _now_iso(),
                    "error": f"File too large (> {max_bytes} bytes)."
                })
                continue

            # Compute content hash for deduplication
            sha = _file_sha256(src)
            mime = _sniff_mime(src)
            created_at = _now_iso()

            # Determine blob storage path
            blob_path = _blob_path_for_sha(blob_dir, sha)
            _ensure_parent(blob_path)

            # INSERT or SELECT existing artifact id by sha (handles deduplication)
            artifact_id = _upsert_artifact(conn, sha, size, mime, src.name, created_at, blob_path, src)

            # Link row ties the artifact to this session/run/tool_call
            conn.execute(
                """
                INSERT INTO links (artifact_id, session_id, run_id, tool_call_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, session_id, run_id, tool_call_id, created_at),
            )
            conn.commit()

            # Create artifact descriptor
            desc = {
                "id": artifact_id,
                "name": src.name,
                "mime": mime,
                "size": size,
                "sha256": sha,
                "created_at": created_at,
            }
            # Optional URL injection (if env is configured)
            try:
                desc["url"] = create_download_url(artifact_id)
            except Exception:
                # No PUBLIC_BASE_URL or SECRET set; descriptor remains without url
                pass

            # Remove the original from the session folder (keep containers lean)
            _safe_delete(src)

            descriptors.append(desc)

    return descriptors


def _upsert_artifact(
    conn: sqlite3.Connection,
    sha256: str,
    size: int,
    mime: str,
    filename: str,
    created_at: str,
    blob_path: Path,
    src_file: Path,
) -> str:
    """
    Upsert (insert or update) an artifact in the database.
    
    This function handles the core deduplication logic:
    - If the SHA256 already exists, return the existing artifact ID
    - If it's a new file, store it in blobstore and create a new database entry
    
    The "upsert" pattern ensures that identical file content is only stored once,
    even if it's created multiple times by different agents or sessions.
    
    Args:
        conn: Database connection
        sha256: Content hash of the file
        size: File size in bytes
        mime: MIME type of the file
        filename: Original filename
        created_at: ISO timestamp
        blob_path: Path where the file should be stored in blobstore
        src_file: Source file path (for copying)
    
    Returns:
        Artifact ID (either existing or newly created)
    """
    # Do we already know this sha?
    cur = conn.execute("SELECT id FROM artifacts WHERE sha256 = ?", (sha256,))
    row = cur.fetchone()
    if row:
        # ensure blob exists (in case it was pruned)
        if not blob_path.exists():
            _copy_bytes(src_file, blob_path)
        return row[0]

    # New artifact: write blob and insert row
    _copy_bytes(src_file, blob_path)
    art_id = _gen_artifact_id()
    conn.execute(
        """
        INSERT INTO artifacts (id, sha256, size, mime, filename, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (art_id, sha256, size, mime, filename, created_at),
    )
    conn.commit()
    return art_id


def _copy_bytes(src: Path, dst: Path, chunk_size: int = 1024 * 1024) -> None:
    """
    Copy file bytes from source to destination in chunks.
    
    This function efficiently copies large files without loading them entirely
    into memory. It reads and writes in chunks to handle files of any size.
    
    Args:
        src: Source file path
        dst: Destination file path
        chunk_size: Size of each chunk to read/write (default: 1MB)
    """
    _ensure_parent(dst)
    if dst.exists():
        return
    with src.open("rb") as fsrc, dst.open("wb") as fdst:
        for chunk in iter(lambda: fsrc.read(chunk_size), b""):
            fdst.write(chunk)

def _safe_delete(path: Path) -> None:
    """
    Safely delete a file without crashing the ingestion process.
    
    This function attempts to delete a file but catches any exceptions.
    It's used to clean up staging files after successful ingestion.
    
    Args:
        path: Path to the file to delete
    """
    try:
        path.unlink(missing_ok=True)
    except Exception:
        # last resort: leave it; we don't want to crash ingest
        pass
