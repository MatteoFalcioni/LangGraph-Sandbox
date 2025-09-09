# tests/test_artifact_ingest.py
import os
import sqlite3
import hashlib
from pathlib import Path
from typing import Tuple

import pytest

from src.artifacts.store import ensure_artifact_store
from src.artifacts.ingest import ingest_files

# Helpers
def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def blob_path_for_sha(blob_dir: Path, sha256: str) -> Path:
    return blob_dir / sha256[:2] / sha256[2:4] / sha256

def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

@pytest.fixture()
def temp_store(tmp_path, monkeypatch) -> Tuple[Path, Path]:
    """
    Creates an isolated artifact store in a temp folder:
      - env ARTIFACTS_DB_PATH points to tmp_path / artifacts.db
      - env BLOBSTORE_DIR points to tmp_path / blobstore
    Returns (db_path, blob_dir).
    """
    db_path = tmp_path / "artifacts.db"
    blob_dir = tmp_path / "blobstore"
    monkeypatch.setenv("ARTIFACTS_DB_PATH", str(db_path))
    monkeypatch.setenv("BLOBSTORE_DIR", str(blob_dir))

    info = ensure_artifact_store()
    assert Path(info["blobstore_dir"]).exists()
    assert Path(info["db_path"]).exists()

    return db_path, blob_dir

def test_ingest_smoke(temp_store, tmp_path):
    db_path, blob_dir = temp_store

    # --- Make a fake session staging folder with one file
    session_id = "sid_123"
    staging = tmp_path / "sessions" / session_id / "artifacts"
    staging.mkdir(parents=True, exist_ok=True)

    content1 = b"hello world\n"
    file1 = staging / "hello.txt"
    file1.write_bytes(content1)
    sha1 = sha256_bytes(content1)

    # --- Ingest first time
    descs = ingest_files([file1], session_id=session_id, run_id="run1")
    assert len(descs) == 1
    d1 = descs[0]
    assert d1["id"] and d1["sha256"] == sha1 and d1["size"] == len(content1)
    assert d1["name"] == "hello.txt"
    # staging copy removed
    assert not file1.exists()

    # blob exists
    blob1 = blob_path_for_sha(blob_dir, sha1)
    assert blob1.exists() and blob1.is_file()

    # DB rows: 1 artifact, 1 link
    with open_db(db_path) as conn:
        art_rows = conn.execute("SELECT id, sha256, size, mime, filename FROM artifacts").fetchall()
        link_rows = conn.execute("SELECT artifact_id, session_id, run_id FROM links").fetchall()
        assert len(art_rows) == 1
        assert len(link_rows) == 1
        assert art_rows[0][1] == sha1
        assert link_rows[0][1] == session_id

    # --- Ingest same bytes again (dedup check)
    file2 = staging / "copy.txt"
    file2.write_bytes(content1)

    descs2 = ingest_files([file2], session_id=session_id, run_id="run2")
    assert len(descs2) == 1
    d2 = descs2[0]
    assert d2["sha256"] == sha1
    # still only one blob
    assert blob1.exists()
    # staging copy removed
    assert not file2.exists()

    # DB rows: still 1 artifact, but now 2 links
    with open_db(db_path) as conn:
        art_cnt = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        link_cnt = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        assert art_cnt == 1
        assert link_cnt == 2

    # --- Ingest different bytes → new artifact
    content2 = b"something else\n"
    file3 = staging / "other.txt"
    file3.write_bytes(content2)
    sha2 = sha256_bytes(content2)

    descs3 = ingest_files([file3], session_id=session_id, run_id="run3")
    assert len(descs3) == 1
    d3 = descs3[0]
    assert d3["sha256"] == sha2
    assert not file3.exists()
    assert blob_path_for_sha(blob_dir, sha2).exists()

    with open_db(db_path) as conn:
        art_cnt = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        link_cnt = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        assert art_cnt == 2
        assert link_cnt == 3
