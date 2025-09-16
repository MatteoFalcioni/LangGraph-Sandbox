# tests/test_integration_pipeline.py
import io
import sys
import tarfile
from pathlib import Path

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph_sandbox.config import Config, SessionStorage, DatasetAccess
from langgraph_sandbox.dataset_manager.cache import read_ids, cache_file_path
from langgraph_sandbox.dataset_manager.staging import stage_dataset_into_sandbox, container_staged_path


# ---------------------- fakes ----------------------

class FakeContainer:
    """
    Minimal Docker container stub to capture tar streams written via put_archive
    and mkdir calls via exec_run.
    """
    def __init__(self):
        self.mkdirs = []           # recorded mkdir commands
        self.archives = []         # list[(path, tar_bytes)]

    def exec_run(self, cmd):
        # Expect: ["/bin/sh","-lc","mkdir -p -- /abs/path"]
        assert isinstance(cmd, list) and cmd[:2] == ["/bin/sh", "-lc"]
        assert "mkdir -p" in cmd[2]
        self.mkdirs.append(cmd[2])
        return (0, b"")

    def put_archive(self, path, data):
        assert path.startswith("/")
        # Verify tar looks valid and contains exactly one file we can read
        bio = io.BytesIO(data)
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            m = members[0]
            f = tar.extractfile(m)
            assert f is not None
            _ = f.read()  # consume
        self.archives.append((path, data))
        return True


def make_fake_fetch(counter_list, payload_prefix=b"PARQUET::"):
    """
    Returns a fake fetch function that records ds_id calls to counter_list
    and returns deterministic bytes based on ds_id.
    """
    def _fetch(ds_id: str) -> bytes:
        counter_list.append(ds_id)
        return payload_prefix + ds_id.encode("utf-8")
    return _fetch


# ---------------------- test ----------------------

def test_integration_tmpfs_api_pipeline(tmp_path: Path):
    """
    End-to-end check:
      - uses TMPFS + API config
      - stages a dataset into the container (tar to /session/data)
      - records dataset in host cache list
      - idempotent: second call with same ds_id does not re-fetch nor re-stage
      - validates tar content matches fake fetch bytes and filename
    """
    # Config: TMPFS_API mode
    cfg = Config(
        session_storage=SessionStorage.TMPFS,
        dataset_access=DatasetAccess.API,
        sessions_root=tmp_path / "sessions",
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )
    sid = "sess-123"
    ds_id = "quartieri-di-bologna"

    # Fakes
    container = FakeContainer()
    fetch_calls = []
    fake_fetch = make_fake_fetch(fetch_calls)

    # ---- 1st stage: should fetch and write into container
    desc1 = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id=ds_id,
        fetch_fn=fake_fetch,
        skip_if_cached=True,
    )

    # Descriptor & mode
    assert desc1["id"] == ds_id
    assert desc1["mode"] == "TMPFS_API"
    assert desc1["staged"] is True
    assert desc1["path_in_container"] == container_staged_path(cfg, ds_id)

    # mkdir executed for /session/data
    assert any("/session/data" in cmd for cmd in container.mkdirs)

    # One tar written to /session/data, with expected filename/content
    assert len(container.archives) == 1
    archive_path, tar_bytes = container.archives[0]
    assert archive_path == "/session/data"
    bio = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=bio, mode="r:*") as tar:
        members = tar.getmembers()
        assert len(members) == 1
        m = members[0]
        assert m.name == f"{ds_id}.parquet"
        f = tar.extractfile(m)
        assert f.read() == b"PARQUET::" + ds_id.encode("utf-8")

    # Cache file on host updated with ds_id
    cache_path = cache_file_path(cfg, sid)
    assert cache_path.exists()
    assert read_ids(cfg, sid) == [ds_id]

    # Fake fetch called exactly once
    assert fetch_calls == [ds_id]

    # ---- 2nd stage (same id): should be a no-op (skip_if_cached=True)
    desc2 = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id=ds_id,
        fetch_fn=fake_fetch,
        skip_if_cached=True,
    )
    assert desc2["staged"] is False
    assert desc2["path_in_container"] == container_staged_path(cfg, ds_id)

    # No additional tar writes; still 1
    assert len(container.archives) == 1

    # No additional fetch calls
    assert fetch_calls == [ds_id]

    # Cache unchanged
    assert read_ids(cfg, sid) == [ds_id]
