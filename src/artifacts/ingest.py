# src/artifacts/ingest.py
"""
Ingest new artifact files from a session's staging folder (/session/artifacts inside the container).
Host-side: we receive HOST paths of new files, move their bytes into a content-addressed blobstore,
insert metadata in SQLite, delete the originals from the session folder, and return descriptors.

Steps:
- We compute a SHA-256 fingerprint of each file (its "digital fingerprint").
- We save the file once under blobstore/<2-char>/<2-char>/<sha256>.
- We record a row in 'artifacts' (if that sha is new) and a row in 'links' (always).
- We remove the original file from the session folder.
- We return a small "descriptor" for each artifact (id, name, mime, size, sha, created_at).

Env knobs (optional):
- ARTIFACTS_DB_PATH: path to SQLite db (default: <project>/artifacts.db)
- BLOBSTORE_DIR: blob folder (default: <project>/blobstore)
- MAX_ARTIFACT_SIZE_MB: per-file size cap (default: 50 MB)
"""

from __future__ import annotations
import os
import sqlite3
import hashlib
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Iterable, List, Dict, Optional
from datetime import datetime, timezone

from .store import _resolve_paths, _connect 


# ---------- small helpers ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _gen_artifact_id() -> str:
    # short, unique, human-ish
    return "art_" + uuid.uuid4().hex[:24]

def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()

def _blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    # e.g., blobstore/ab/cd/abcdef...
    a, b = sha256[:2], sha256[2:4]
    return blob_dir / a / b / sha256

def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def _sniff_mime(path: Path) -> str:
    mt, _ = mimetypes.guess_type(path.name)
    return mt or "application/octet-stream"

def _max_bytes() -> int:
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
    Args:
      new_host_files: list of new files detected under the session's staging folder (HOST paths).
      session_id: your per-session identifier.
      run_id: your per-tool-call identifier.
      tool_call_id: optional extra tag.

    Returns:
      List of artifact descriptors:
      {
        "id": str,
        "name": str,
        "mime": str,
        "size": int,
        "sha256": str,
        "created_at": str
      }
    """
    paths = _resolve_paths()
    blob_dir = paths["blob_dir"]
    db_path = paths["db_path"]

    descriptors: List[Dict] = []
    max_bytes = _max_bytes()

    # Normalize to Path
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

            sha = _file_sha256(src)
            mime = _sniff_mime(src)
            created_at = _now_iso()

            blob_path = _blob_path_for_sha(blob_dir, sha)
            _ensure_parent(blob_path)

            # INSERT or SELECT existing artifact id by sha
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

            # Remove the original from the session folder (keep containers lean)
            _safe_delete(src)

            descriptors.append({
                "id": artifact_id,
                "name": src.name,
                "mime": mime,
                "size": size,
                "sha256": sha,
                "created_at": created_at,
            })

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
    If sha256 already exists in 'artifacts', return its id.
    Otherwise:
      - copy bytes into blobstore (once)
      - insert new artifacts row
      - return new id
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
    _ensure_parent(dst)
    if dst.exists():
        return
    with src.open("rb") as fsrc, dst.open("wb") as fdst:
        for chunk in iter(lambda: fsrc.read(chunk_size), b""):
            fdst.write(chunk)

def _safe_delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        # last resort: leave it; we don't want to crash ingest
        pass
