import sys
from pathlib import Path

import pytest

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config, SessionStorage, DatasetAccess
from src.datasets.cache import (
    cache_file_path, read_ids, write_ids, add_id, is_cached
)


def _cfg(tmp_path: Path) -> Config:
    return Config(
        session_storage=SessionStorage.TMPFS,
        dataset_access=DatasetAccess.API,
        sessions_root=tmp_path / "sessions",
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )


def test_empty_read_returns_list(tmp_path):
    cfg = _cfg(tmp_path)
    sid = "s1"
    assert read_ids(cfg, sid) == []
    assert cache_file_path(cfg, sid).parent.exists() is False  # not created yet


def test_add_and_is_cached_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    sid = "s1"
    assert not is_cached(cfg, sid, "ds1")
    add_id(cfg, sid, "ds1")
    assert is_cached(cfg, sid, "ds1")
    # idempotent
    add_id(cfg, sid, "ds1")
    assert read_ids(cfg, sid) == ["ds1"]


def test_write_and_read_order_and_dedup(tmp_path):
    cfg = _cfg(tmp_path)
    sid = "s1"
    write_ids(cfg, sid, ["a", "b", "a", "c", "b"])
    assert read_ids(cfg, sid) == ["a", "b", "c"]
