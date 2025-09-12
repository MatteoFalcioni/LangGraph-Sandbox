import io
import sys
import tarfile
from pathlib import Path

import pytest

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config, SessionStorage, DatasetAccess
from src.datasets.cache import read_ids, add_id, cache_file_path
from src.datasets.staging import (
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

def test_api_tmpfs__tmpfs_mode_stages_into_container(tmp_path):
    cfg = _cfg(tmp_path, SessionStorage.TMPFS, DatasetAccess.API_TMPFS)
    sid = "abc"
    c = FakeContainer()

    desc = stage_dataset_into_sandbox(
        cfg=cfg, session_id=sid, container=c, ds_id="qdb", fetch_fn=fake_fetch(b"BYTES")
    )
