# tests/test_config.py
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is importable (langgraph_sandbox/__init__.py exists)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph_sandbox.config import Config, SessionStorage, DatasetAccess  # noqa: E402


ENV_KEYS = [
    "SESSION_STORAGE",
    "DATASET_ACCESS",
    "SESSIONS_ROOT",
    "DATASETS_HOST_RO",
    "HYBRID_LOCAL_PATH",
    "BLOBSTORE_DIR",
    "ARTIFACTS_DB",
    "SANDBOX_IMAGE",
    "TMPFS_SIZE_MB",
]


def _clear_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults_mode_tmpfs_api(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    # run with no env -> defaults: TMPFS + API (TMPFS_API mode)
    c = Config.from_env()
    assert c.session_storage == SessionStorage.TMPFS
    assert c.dataset_access == DatasetAccess.API
    assert c.mode_id() == "TMPFS_API"
    assert c.tmpfs_size_mb == 1024
    # Paths resolve but need not exist
    assert c.sessions_root.name == "sessions"
    assert c.blobstore_dir.name == "blobstore"
    assert c.artifacts_db_path.name == "artifacts.db"


def test_local_ro_requires_host_path(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATASET_ACCESS", "LOCAL_RO")
    with pytest.raises(ValueError):
        Config.from_env()


def test_hybrid_requires_hybrid_path(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATASET_ACCESS", "HYBRID")
    with pytest.raises(ValueError, match="HYBRID_LOCAL_PATH is required when DATASET_ACCESS=HYBRID"):
        Config.from_env()


def test_bind_local_ro_ok(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SESSION_STORAGE", "BIND")
    monkeypatch.setenv("DATASET_ACCESS", "LOCAL_RO")
    monkeypatch.setenv("DATASETS_HOST_RO", str(tmp_path / "llm_data"))
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    c = Config.from_env()
    assert c.is_bind
    assert c.uses_local_ro
    assert c.mode_id() == "BIND_LOCAL"
    assert c.datasets_host_ro == (tmp_path / "llm_data").resolve()
    assert c.session_dir("abc123") == (tmp_path / "sessions" / "abc123").resolve()


@pytest.mark.parametrize(
    "sess,dset,expect_mode,needs_ro",
    [
        ("TMPFS", "API", "TMPFS_API", False),
        ("BIND",  "API", "BIND_API", False),
        ("TMPFS", "LOCAL_RO",  "TMPFS_LOCAL", True),
        ("BIND",  "LOCAL_RO",  "BIND_LOCAL", True),
    ],
)
def test_mode_matrix(monkeypatch, tmp_path, sess, dset, expect_mode, needs_ro):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SESSION_STORAGE", sess)
    monkeypatch.setenv("DATASET_ACCESS", dset)
    if needs_ro:
        monkeypatch.setenv("DATASETS_HOST_RO", str(tmp_path / "ro_data"))
    c = Config.from_env()
    assert c.mode_id() == expect_mode


def test_case_insensitive_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SESSION_STORAGE", "tmpfs")
    monkeypatch.setenv("DATASET_ACCESS", "api")
    c = Config.from_env()
    assert c.session_storage == SessionStorage.TMPFS
    assert c.dataset_access == DatasetAccess.API


def test_overrides(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("TMPFS_SIZE_MB", "2048")
    monkeypatch.setenv("BLOBSTORE_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("ARTIFACTS_DB", str(tmp_path / "artifacts.sqlite"))
    c = Config.from_env()
    assert c.tmpfs_size_mb == 2048
    assert c.blobstore_dir == (tmp_path / "blobs").resolve()
    assert c.artifacts_db_path == (tmp_path / "artifacts.sqlite").resolve()
