# langgraph_sandbox/artifacts/reader.py
"""
Artifact Reading and Data Access Utilities

This module provides high-level functions to read artifacts from the local blobstore
using artifact IDs. It abstracts away the complexity of:
- Looking up artifacts in the SQLite database
- Resolving SHA256 hashes to actual file paths
- Reading file contents in various formats
- Creating download URLs for artifacts

Key features:
- No network calls (all local operations)
- No filesystem paths exposed to callers (uses artifact IDs)
- Support for raw bytes, text, and structured data formats
- Session-based artifact discovery
- Automatic error handling for missing files

Pipeline:
1. Look up artifact in SQLite to get SHA256 and metadata
2. Resolve the blob path on disk using the SHA256
3. Return bytes/text, or parse common formats (CSV, Parquet)
"""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List

from .store import _resolve_paths

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
    Convert a SHA256 hash to the corresponding blob storage path.
    
    Uses a two-level directory structure to avoid too many files in one directory:
    - First 2 characters: top-level directory
    - Next 2 characters: second-level directory  
    - Full hash: filename
    
    Example: sha256="abc123..." → "blobstore/ab/c1/abc123..."
    
    Args:
        blob_dir: Base directory for blob storage
        sha256: SHA256 hash of the file content
    
    Returns:
        Path object pointing to the actual file location
    """
    return Path(blob_dir) / sha256[:2] / sha256[2:4] / sha256

def get_metadata(artifact_id: str) -> Dict:
    """
    Retrieve metadata for an artifact by its ID.
    
    Looks up the artifact in the database and returns all available metadata
    without reading the actual file content. This is useful for:
    - Checking if an artifact exists
    - Getting file size, MIME type, creation date
    - Validating artifact IDs before attempting to read content
    
    Args:
        artifact_id: The unique identifier for the artifact (e.g., "art_abc123")
    
    Returns:
        Dictionary containing:
        - id: The artifact ID
        - sha256: Content hash
        - mime: MIME type (e.g., "image/png", "text/csv")
        - filename: Original filename
        - size: File size in bytes
        - created_at: ISO timestamp of creation
    
    Raises:
        FileNotFoundError: If the artifact ID doesn't exist in the database
    """
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
    """
    Read the raw bytes of an artifact by its ID.
    
    This is the fundamental reading function that all other readers use.
    It:
    1. Looks up the artifact metadata in the database
    2. Converts the SHA256 hash to the actual file path
    3. Reads and returns the raw file bytes
    
    Args:
        artifact_id: The unique identifier for the artifact
    
    Returns:
        Raw bytes of the file content
    
    Raises:
        FileNotFoundError: If the artifact ID doesn't exist or the file is missing
    """
    paths = _resolve_paths()
    meta = get_metadata(artifact_id)
    blob = _blob_path_for_sha(paths["blob_dir"], meta["sha256"])
    if not blob.exists():
        raise FileNotFoundError(f"Blob missing for {artifact_id} (sha={meta['sha256']})")
    return blob.read_bytes()

def read_text(artifact_id: str, encoding: str = "utf-8", max_bytes: Optional[int] = None) -> str:
    """
    Read an artifact as text with optional size limiting.
    
    Decodes the raw bytes as text using the specified encoding.
    Useful for reading text files, JSON, CSV headers, etc.
    
    Args:
        artifact_id: The unique identifier for the artifact
        encoding: Text encoding to use (default: "utf-8")
        max_bytes: Optional limit on bytes to read (useful for large files)
    
    Returns:
        Decoded text content
    
    Raises:
        FileNotFoundError: If the artifact doesn't exist
        UnicodeDecodeError: If the file can't be decoded with the specified encoding
    """
    data = read_bytes(artifact_id)
    if max_bytes is not None and len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode(encoding, errors="replace")

# Optional parsing helpers 
def load_csv(artifact_id: str, **pandas_kwargs):
    """
    Load a CSV artifact as a pandas DataFrame.
    
    This function provides a convenient way to read CSV files that were generated
    by the Data Analyst agent. It handles the file reading and parsing automatically.
    
    Args:
        artifact_id: The unique identifier for the artifact
        **pandas_kwargs: Additional arguments passed to pd.read_csv()
    
    Returns:
        pandas DataFrame containing the CSV data
    
    Raises:
        FileNotFoundError: If the artifact doesn't exist
        ImportError: If pandas is not installed
        pandas.errors.ParserError: If the CSV is malformed
    """
    import pandas as pd  # lazy import
    from io import BytesIO
    data = read_bytes(artifact_id)
    return pd.read_csv(BytesIO(data), **pandas_kwargs)

def load_parquet(artifact_id: str, **pandas_kwargs):
    """
    Load a Parquet artifact as a pandas DataFrame.
    
    Parquet is a columnar storage format that's efficient for large datasets.
    This function reads Parquet files that may have been created by the Data Analyst agent.
    
    Args:
        artifact_id: The unique identifier for the artifact
        **pandas_kwargs: Additional arguments passed to pd.read_parquet()
    
    Returns:
        pandas DataFrame containing the Parquet data
    
    Raises:
        FileNotFoundError: If the artifact doesn't exist
        ImportError: If pandas is not installed
        pandas.errors.ParserError: If the Parquet file is malformed
    """
    import pandas as pd  # lazy import
    from io import BytesIO
    data = read_bytes(artifact_id)
    return pd.read_parquet(BytesIO(data), **pandas_kwargs)

def fetch_artifact_urls(session_id: str) -> List[Dict[str, str]]:
    """
    Fetch all artifacts for a given session and return their download URLs.
    
    This function is useful for:
    - Listing all files generated in a conversation
    - Creating download links for the frontend
    - Session management and cleanup
    
    The function queries the database to find all artifacts linked to a specific
    session, then creates signed download URLs for each one.
    
    Args:
        session_id: The session/conversation identifier
    
    Returns:
        List of dictionaries, each containing:
        - id: Artifact ID
        - filename: Original filename (or artifact ID if no filename)
        - mime: MIME type
        - size: File size in bytes
        - created_at: Creation timestamp
        - download_url: Complete URL for downloading the artifact
    
    Note:
        This function handles errors gracefully - if URL creation fails for
        any artifact, it logs a warning but continues processing others.
    """
    from .tokens import create_download_url
    import sqlite3
    
    artifacts = []
    
    try:
        # Use the artifact store's path resolution (respects environment variables)
        paths = _resolve_paths()
        db_path = paths["db_path"]
        
        with sqlite3.connect(db_path) as conn:
            # Get all artifacts linked to this session
            rows = conn.execute("""
                SELECT a.id, a.filename, a.mime, a.size, a.created_at
                FROM artifacts a
                JOIN links l ON a.id = l.artifact_id
                WHERE l.session_id = ?
                ORDER BY a.created_at DESC
            """, (session_id,)).fetchall()
            
            for row in rows:
                artifact_id, filename, mime, size, created_at = row
                try:
                    download_url = create_download_url(artifact_id)
                    artifacts.append({
                        "id": artifact_id,
                        "filename": filename or artifact_id,
                        "mime": mime,
                        "size": size,
                        "created_at": created_at,
                        "download_url": download_url
                    })
                except Exception as e:
                    print(f"Warning: Could not create URL for artifact {artifact_id}: {e}")
                    
    except Exception as e:
        print(f"Error fetching artifacts: {e}")
    
    return artifacts
