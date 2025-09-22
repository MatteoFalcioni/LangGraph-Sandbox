# src/artifacts/store.py
"""
Artifact Store bootstrap 
- Creates a local blob folder (where file bytes live)
- Creates a tiny SQLite DB (where artifact metadata lives)

No runtime reads/writes yet—this is just setup.

Environment variables (optional):
- ARTIFACTS_DB_PATH: path to SQLite file (default: <project>/artifacts.db)
- BLOBSTORE_DIR: path to blob folder    (default: <project>/blobstore)
"""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Dict


def _project_root() -> Path:
    # .../project/langgraph_sandbox/artifacts/store.py  -> project/
    return Path(__file__).resolve().parents[2]


def _resolve_paths(custom_db_path: str | None = None, custom_blob_dir: str | None = None) -> Dict[str, Path]:
    root = _project_root()
    
    # Priority: custom parameters > environment variables > defaults
    if custom_db_path:
        db_path = Path(custom_db_path).resolve()
    else:
        db_path = Path(os.getenv("ARTIFACTS_DB_PATH", root / "artifacts.db")).resolve()
    
    if custom_blob_dir:
        blob_dir = Path(custom_blob_dir).resolve()
    else:
        blob_dir = Path(os.getenv("BLOBSTORE_DIR", root / "blobstore")).resolve()
    
    return {"db_path": db_path, "blob_dir": blob_dir}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # sensible defaults for small, local DB
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    # id: app-facing ID (e.g., art_01H...), sha256: content fingerprint
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL,
            mime TEXT NOT NULL,
            filename TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS links (
            artifact_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            run_id TEXT,
            tool_call_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
        );

        -- Helpful indexes
        CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);
        CREATE INDEX IF NOT EXISTS idx_links_artifact_id ON links(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_links_session ON links(session_id);
        """
    )
    conn.commit()


def ensure_artifact_store(custom_db_path: str | None = None, custom_blob_dir: str | None = None) -> Dict[str, str]:
    """
    Creates (if missing):
      - blob folder
      - SQLite DB with the two tables
    
    Args:
        custom_db_path: Optional custom path for the SQLite database file
        custom_blob_dir: Optional custom path for the blob store directory
    
    Returns resolved paths as strings.
    """
    paths = _resolve_paths(custom_db_path, custom_blob_dir)
    paths["blob_dir"].mkdir(parents=True, exist_ok=True)

    with _connect(paths["db_path"]) as conn:
        _create_schema(conn)

    return {
        "db_path": str(paths["db_path"]),
        "blobstore_dir": str(paths["blob_dir"]),
    }


if __name__ == "__main__":
    info = ensure_artifact_store()
    print("Artifact store ready:")
    for k, v in info.items():
        print(f"  - {k}: {v}")
