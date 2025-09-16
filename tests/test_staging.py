import io
import sys
import tarfile
from pathlib import Path

import pytest

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph_sandbox.config import Config, SessionStorage, DatasetAccess
from langgraph_sandbox.datasets.cache import read_ids, add_id, cache_file_path
from langgraph_sandbox.datasets.staging import (
    stage_dataset_into_sandbox,
    container_staged_path,
    container_ro_path,
    host_bind_data_path,
)

# ----- fakes -----

class FakeContainer:
    def __init__(self):
        self.mkdirs = []
        self.archives = []  # list[(path, tar_bytes)]
    def exec_run(self, cmd):
        # Expect: ["/bin/sh","-lc","mkdir -p -- /abs/path"]
        assert isinstance(cmd, list) and cmd[:2] == ["/bin/sh", "-lc"]
        assert "mkdir -p" in cmd[2]
        self.mkdirs.append(cmd[2])
        return (0, b"")
    def put_archive(self, path, data):
        assert path.startswith("/")
        self.archives.append((path, data))
        # validate tar is readable
        bio = io.BytesIO(data)
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            f = tar.extractfile(members[0])
            assert f is not None
            _ = f.read()
        return True

def fake_fetch(ok_bytes: bytes):
    def _fn(ds_id: str) -> bytes:
        return ok_bytes
    return _fn

def raising_fetch(ds_id: str) -> bytes:
    raise AssertionError("fetch() should NOT be called in LOCAL_RO mode")


def _cfg(tmp_path: Path, sess: SessionStorage, dset: DatasetAccess) -> Config:
    return Config(
        session_storage=sess,
        dataset_access=dset,
        sessions_root=tmp_path / "sessions",
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )

# ----- tests -----

def test_api__tmpfs_mode_stages_into_container(tmp_path):
    cfg = _cfg(tmp_path, SessionStorage.TMPFS, DatasetAccess.API)
    sid = "abc"
    c = FakeContainer()

    desc = stage_dataset_into_sandbox(
        cfg=cfg, session_id=sid, container=c, ds_id="qdb", fetch_fn=fake_fetch(b"BYTES")
    )
    
    # Verify staging worked
    assert desc["id"] == "qdb"
    assert desc["staged"] is True
    assert desc["path_in_container"] == container_staged_path(cfg, "qdb")
    
    # Verify container operations
    assert len(c.mkdirs) == 1
    assert "/session/data" in c.mkdirs[0]
    assert len(c.archives) == 1
    assert c.archives[0][0] == "/session/data"
    
    # Verify tar content
    bio = io.BytesIO(c.archives[0][1])
    with tarfile.open(fileobj=bio, mode="r:*") as tar:
        members = tar.getmembers()
        assert len(members) == 1
        assert members[0].name == "qdb.parquet"
        f = tar.extractfile(members[0])
        assert f.read() == b"BYTES"


def test_api__bind_mode_stages_into_container(tmp_path):
    cfg = _cfg(tmp_path, SessionStorage.BIND, DatasetAccess.API)
    sid = "abc"
    c = FakeContainer()

    desc = stage_dataset_into_sandbox(
        cfg=cfg, session_id=sid, container=c, ds_id="test_data", fetch_fn=fake_fetch(b"TEST_BYTES")
    )
    
    # Verify staging worked
    assert desc["id"] == "test_data"
    assert desc["staged"] is True
    assert desc["path_in_container"] == container_staged_path(cfg, "test_data")
    
    # In BIND mode, files are written to host filesystem, not container
    # So no container operations should occur
    assert len(c.mkdirs) == 0
    assert len(c.archives) == 0
    
    # Verify file was written to host
    host_file = host_bind_data_path(cfg, sid, "test_data")
    assert host_file.exists()
    assert host_file.read_bytes() == b"TEST_BYTES"


def test_local_ro__no_staging_needed(tmp_path):
    cfg = _cfg(tmp_path, SessionStorage.TMPFS, DatasetAccess.LOCAL_RO)
    sid = "abc"
    c = FakeContainer()

    desc = stage_dataset_into_sandbox(
        cfg=cfg, session_id=sid, container=c, ds_id="local_data", fetch_fn=raising_fetch
    )
    
    # Verify no staging occurred
    assert desc["id"] == "local_data"
    assert desc["staged"] is False
    assert desc["path_in_container"] == container_ro_path(cfg, "local_data")
    
    # Verify no container operations
    assert len(c.mkdirs) == 0
    assert len(c.archives) == 0


def test_none_mode__no_staging_needed(tmp_path):
    cfg = _cfg(tmp_path, SessionStorage.TMPFS, DatasetAccess.NONE)
    sid = "abc"
    c = FakeContainer()

    desc = stage_dataset_into_sandbox(
        cfg=cfg, session_id=sid, container=c, ds_id="any_data", fetch_fn=raising_fetch
    )
    
    # Verify no staging occurred
    assert desc["id"] == "any_data"
    assert desc["staged"] is False
    # In NONE mode, it should still return a path for LOCAL_RO compatibility
    assert desc["path_in_container"] == container_ro_path(cfg, "any_data")
    
    # Verify no container operations
    assert len(c.mkdirs) == 0
    assert len(c.archives) == 0
