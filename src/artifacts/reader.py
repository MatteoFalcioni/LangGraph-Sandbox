# src/artifacts/reader.py
"""
Small helpers to read artifacts from the local blobstore by artifact ID.
Pipeline:
- Look up the artifact in SQLite to get its SHA and metadata
- Resolve the blob path on disk using that SHA
- Return bytes/text, or (optionally) parse common formats

No network calls, no filesystem paths exposed to callers.
"""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Optional, Dict

from .store import _resolve_paths

def _db() -> sqlite3.Connection:
    paths = _resolve_paths()
    conn = sqlite3.connect(paths["db_path"])
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    return Path(blob_dir) / sha256[:2] / sha256[2:4] / sha256

def get_metadata(artifact_id: str) -> Dict:
    """Return a dict with DB metadata for an artifact ID, or raise FileNotFoundError."""
    paths = _resolve_paths()
    with _db() as conn:
        row = conn.execute(
            "SELECT sha256, mime, filename, size, created_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Artifact not found: {artifact_id}")
    sha, mime, filename, size, created_at = row
    return {
        "id": artifact_id,
        "sha256": sha,
        "mime": mime,
        "filename": filename,
        "size": size,
        "created_at": created_at,
    }

def read_bytes(artifact_id: str) -> bytes:
    """Return the artifact bytes by ID, or raise FileNotFoundError."""
    paths = _resolve_paths()
    meta = get_metadata(artifact_id)
    blob = _blob_path_for_sha(paths["blob_dir"], meta["sha256"])
    if not blob.exists():
        raise FileNotFoundError(f"Blob missing for {artifact_id} (sha={meta['sha256']})")
    return blob.read_bytes()

def read_text(artifact_id: str, encoding: str = "utf-8", max_bytes: Optional[int] = None) -> str:
    """Return the artifact decoded as text. Optionally limit bytes read."""
    data = read_bytes(artifact_id)
    if max_bytes is not None and len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode(encoding, errors="replace")

# Optional parsing helpers (only if you have pandas installed on host)
def load_csv(artifact_id: str, **pandas_kwargs):
    """Return a pandas DataFrame loaded from a CSV artifact."""
    import pandas as pd  # lazy import
    from io import BytesIO
    data = read_bytes(artifact_id)
    return pd.read_csv(BytesIO(data), **pandas_kwargs)

def load_parquet(artifact_id: str, **pandas_kwargs):
    """Return a pandas DataFrame loaded from a Parquet artifact."""
    import pandas as pd  # lazy import
    from io import BytesIO
    data = read_bytes(artifact_id)
    return pd.read_parquet(BytesIO(data), **pandas_kwargs)
