import os
import tempfile
from pathlib import Path
import pytest

from src.sandbox.session_manager import (
    SessionManager, SessionStorage, DatasetAccess
)

# --- Monkeypatch ingest_files to simulate moving to a blobstore and deleting the local copy
@pytest.fixture(autouse=True)
def patch_ingest_files(monkeypatch, tmp_path):
    """
    Mocks the ingestion process.
    This fake function gathers file metadata and then DELETES the source file,
    simulating the behavior of moving it to a remote blobstore.
    """
    def fake_ingest(new_host_files, session_id, run_id, tool_call_id):
        descs = []
        for p in new_host_files:
            p = Path(p)
            descs.append({
                "id": p.name,
                "name": p.name,
                "size": p.stat().st_size if p.exists() else 0,
                "mime": "application/octet-stream",
                "sha256": "deadbeef",
                "created_at": "2025-01-01T00:00:00Z",
                "url": f"blobstore://{session_id}/{p.name}" # URL now points to a fake blobstore
            })
            # **CRITICAL SIMULATION**: Delete the file after "uploading".
            if p.exists():
                p.unlink()
        return descs
    monkeypatch.setattr("src.artifacts.ingest.ingest_files", fake_ingest)
    yield

# Prepare a temporary LOCAL_RO datasets dir with one dummy file
@pytest.fixture
def ro_datasets_dir(tmp_path):
    d = tmp_path / "datasets"
    d.mkdir()
    (d / "dummy.txt").write_text("dummy")
    return d

# Parametrize the 4 modes A–D
MODES = [
    ("A", SessionStorage.BIND,   DatasetAccess.LOCAL_RO),
    ("B", SessionStorage.TMPFS,  DatasetAccess.LOCAL_RO),
    ("C", SessionStorage.TMPFS,  DatasetAccess.API),
    ("D", SessionStorage.BIND,   DatasetAccess.API),
]

@pytest.mark.parametrize("label, sess_store, data_access", MODES)
def test_modes_end_to_end(label, sess_store, data_access, ro_datasets_dir):
    kwargs = {
        "session_storage": sess_store,
        "dataset_access": data_access,
        "tmpfs_size": "512m",
    }
    if data_access == DatasetAccess.LOCAL_RO:
        kwargs["datasets_path"] = ro_datasets_dir

    mgr = SessionManager(**kwargs)
    sid = mgr.start()

    # 1) REPL state persists
    r1 = mgr.exec(sid, "a=1; print('a=', a)")
    assert "a= 1" in r1["stdout"]

    r2 = mgr.exec(sid, "a+=2; print('a=', a)")
    assert "a= 3" in r2["stdout"]

    # 2) Dataset visibility by mode
    if data_access == DatasetAccess.LOCAL_RO:
        out = mgr.exec(sid, "import os; print(os.path.exists('/data/dummy.txt'))")
        assert "True" in out["stdout"], f"{label}: /data/dummy.txt should exist"
    else:
        # API: typically staged to /session/data by your pipeline; simulate presence
        mgr.exec(sid, "import os, pathlib; pathlib.Path('/session/data').mkdir(parents=True, exist_ok=True); open('/session/data/sim.dat','w').write('x')")
        out = mgr.exec(sid, "import os; print(os.path.exists('/session/data/sim.dat'))")
        assert "True" in out["stdout"], f"{label}: /session/data/sim.dat should exist"

    # 3) Artifact diff + ingest
    # **CRITICAL CHANGE**: Separate directory creation from file creation to avoid a
    # race condition with the docker daemon reading from tmpfs.
    mgr.exec(sid, 'from pathlib import Path; Path("/session/artifacts").mkdir(parents=True, exist_ok=True)')
    
    code = """
from pathlib import Path
Path("/session/artifacts/test.txt").write_text("ok")
print("artifact done")
"""
    r3 = mgr.exec(sid, code)
    assert r3["artifacts"], f"{label}: expected artifacts ingested"
    names = {a["name"] for a in r3["artifacts"]}
    assert "test.txt" in names

    # 4) session_dir contract and file cleanup verification
    if sess_store == SessionStorage.TMPFS:
        assert r3["session_dir"] == ""
    else:
        assert r3["session_dir"]
        # **CRITICAL CHANGE**: The file should NO LONGER exist on the host after ingestion.
        # It has been "moved" to the blobstore and deleted locally.
        host_file = Path(r3["session_dir"]) / "artifacts" / "test.txt"
        assert not host_file.exists(), f"{label}: The source artifact file should be deleted after ingestion."

    mgr.stop(sid)

# Bonus: idle sweep test (forces eviction)
def test_idle_sweep(tmp_path, ro_datasets_dir, monkeypatch):
    mgr = SessionManager(
        session_storage=SessionStorage.TMPFS,
        dataset_access=DatasetAccess.API,
        tmpfs_size="256m",
    )
    sid = mgr.start()
    # Make session look old
    info = mgr.sessions[sid]
    info.last_used -= 10_000  # pretend it was idle for a long time

    # Trigger sweep on start()
    sid2 = mgr.start("other")
    # Original sid should be gone
    assert sid not in mgr.sessions
    mgr.stop(sid2)

