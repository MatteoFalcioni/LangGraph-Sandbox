# tests/test_artifact_reader.py
from pathlib import Path
import sqlite3

from src.artifacts.store import ensure_artifact_store
from src.artifacts.ingest import ingest_files
from src.artifacts.reader import get_metadata, read_bytes, read_text

def test_reader_roundtrip(tmp_path, monkeypatch):
    # isolated store
    db_path = tmp_path / "artifacts.db"
    blob_dir = tmp_path / "blobstore"
    monkeypatch.setenv("ARTIFACTS_DB_PATH", str(db_path))
    monkeypatch.setenv("BLOBSTORE_DIR", str(blob_dir))

    ensure_artifact_store()

    # stage + ingest
    sid = "sid_reader"
    staging = tmp_path / "sessions" / sid / "artifacts"
    staging.mkdir(parents=True, exist_ok=True)
    content = b"hello reader\n"
    f = staging / "note.txt"
    f.write_bytes(content)

    desc = ingest_files([f], session_id=sid, run_id="run1")[0]
    art_id = desc["id"]

    # read metadata and content
    meta = get_metadata(art_id)
    assert meta["filename"] == "note.txt"
    assert meta["size"] == len(content)

    b = read_bytes(art_id)
    assert b == content

    t = read_text(art_id)
    assert t == "hello reader\n"
