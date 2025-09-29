# src/artifacts/store.py
"""
Artifact Store Bootstrap and Database Schema Management

This module handles the initialization of the artifact storage system:
- Creates a local blob folder (where actual file bytes are stored)
- Creates a SQLite database (where artifact metadata is stored)
- Sets up the database schema with proper indexes

The storage system uses a content-addressed approach:
- Files are stored by their SHA256 hash (e.g., blobstore/ab/cd/abcdef...)
- Database tracks metadata and relationships between artifacts and sessions
- This enables deduplication and efficient storage

Environment variables (optional):
- ARTIFACTS_DB_PATH: path to SQLite file (default: <project>/artifacts.db)
- BLOBSTORE_DIR: path to blob folder (default: <project>/blobstore)
"""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Dict


def _project_root() -> Path:
    """
    Find the project root directory.
    
    This function navigates up from the current file location to find the project root.
    Path: .../project/langgraph_sandbox/artifacts/store.py -> project/
    
    Returns:
        Path object pointing to the project root directory
    """
    # .../project/langgraph_sandbox/artifacts/store.py  -> project/
    return Path(__file__).resolve().parents[2]


def _resolve_paths(custom_db_path: str | None = None, custom_blob_dir: str | None = None) -> Dict[str, Path]:
    """
    Resolve the paths for database and blob storage.
    
    Priority order:
    1. Custom parameters (if provided)
    2. Environment variables
    3. Default paths relative to project root
    
    Args:
        custom_db_path: Optional custom path for the SQLite database file
        custom_blob_dir: Optional custom path for the blob store directory
    
    Returns:
        Dictionary with 'db_path' and 'blob_dir' as Path objects
    """
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
    """
    Create a SQLite database connection with optimized settings.
    
    Configures SQLite for better performance and reliability:
    - WAL mode: Better concurrency (multiple readers, single writer)
    - NORMAL sync: Good balance between safety and performance
    - Foreign keys: Enforces referential integrity
    
    Args:
        db_path: Path to the SQLite database file
    
    Returns:
        Configured SQLite connection object
    """
    conn = sqlite3.connect(db_path)
    # Sensible defaults for small, local DB
    conn.execute("PRAGMA journal_mode=WAL;")      # Write-Ahead Logging for better concurrency
    conn.execute("PRAGMA synchronous=NORMAL;")    # Balanced safety/performance
    conn.execute("PRAGMA foreign_keys=ON;")       # Enforce foreign key constraints
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    """
    Create the database schema for artifact storage.
    
    Creates two main tables:
    1. 'artifacts': Stores file metadata (ID, SHA256, size, MIME type, etc.)
    2. 'links': Tracks relationships between artifacts and sessions/runs
    
    The schema supports:
    - Content deduplication (same SHA256 = same file)
    - Session tracking (which artifacts belong to which conversation)
    - Run tracking (which artifacts were created by which tool calls)
    - Efficient lookups via indexes
    
    Args:
        conn: SQLite database connection
    """
    # id: app-facing ID (e.g., art_01H...), sha256: content fingerprint
    conn.executescript(
        """
        -- Main artifacts table: stores file metadata
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,                    -- Human-readable ID (art_abc123)
            sha256 TEXT NOT NULL UNIQUE,            -- Content hash for deduplication
            size INTEGER NOT NULL,                  -- File size in bytes
            mime TEXT NOT NULL,                     -- MIME type (image/png, text/csv, etc.)
            filename TEXT,                          -- Original filename
            created_at TEXT NOT NULL                -- ISO timestamp of creation
        );

        -- Links table: tracks relationships between artifacts and sessions
        CREATE TABLE IF NOT EXISTS links (
            artifact_id TEXT NOT NULL,              -- References artifacts.id
            session_id TEXT NOT NULL,               -- Which conversation/session
            run_id TEXT,                            -- Which LangGraph run
            tool_call_id TEXT,                      -- Which specific tool call
            created_at TEXT NOT NULL,               -- When this link was created
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
        );

        -- Performance indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);
        CREATE INDEX IF NOT EXISTS idx_links_artifact_id ON links(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_links_session ON links(session_id);
        """
    )
    conn.commit()


def ensure_artifact_store(custom_db_path: str | None = None, custom_blob_dir: str | None = None) -> Dict[str, str]:
    """
    Initialize the artifact storage system.
    
    This is the main entry point for setting up artifact storage. It:
    1. Creates the blob storage directory (if it doesn't exist)
    2. Creates the SQLite database with proper schema (if it doesn't exist)
    3. Sets up all necessary indexes for performance
    
    This function is idempotent - it's safe to call multiple times.
    
    Args:
        custom_db_path: Optional custom path for the SQLite database file
        custom_blob_dir: Optional custom path for the blob store directory
    
    Returns:
        Dictionary with resolved paths as strings:
        - 'db_path': Path to the SQLite database file
        - 'blobstore_dir': Path to the blob storage directory
    """
    # Resolve paths using the priority system
    paths = _resolve_paths(custom_db_path, custom_blob_dir)
    
    # Create the blob storage directory (where actual files are stored)
    paths["blob_dir"].mkdir(parents=True, exist_ok=True)

    # Create the database and schema
    with _connect(paths["db_path"]) as conn:
        _create_schema(conn)

    return {
        "db_path": str(paths["db_path"]),
        "blobstore_dir": str(paths["blob_dir"]),
    }


if __name__ == "__main__":
    # When run directly, initialize the store and print the paths
    info = ensure_artifact_store()
    print("Artifact store ready:")
    for k, v in info.items():
        print(f"  - {k}: {v}")
