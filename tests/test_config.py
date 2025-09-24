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


def test_local_ro_requires_host_path(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    # Create a temporary env file with LOCAL_RO but no DATASETS_HOST_RO
    env_file = tmp_path / "test.env"
    env_file.write_text("DATASET_ACCESS=LOCAL_RO\n")
    with pytest.raises(ValueError):
        Config.from_env(env_file_path=env_file)


def test_hybrid_requires_hybrid_path(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    # Create a temporary env file with HYBRID but no HYBRID_LOCAL_PATH
    env_file = tmp_path / "test.env"
    env_file.write_text("DATASET_ACCESS=HYBRID\n")
    with pytest.raises(ValueError, match="HYBRID_LOCAL_PATH is required when DATASET_ACCESS=HYBRID"):
        Config.from_env(env_file_path=env_file)


def test_bind_local_ro_ok(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    # Create a temporary env file with BIND + LOCAL_RO
    env_file = tmp_path / "test.env"
    env_file.write_text(f"""SESSION_STORAGE=BIND
DATASET_ACCESS=LOCAL_RO
DATASETS_HOST_RO={tmp_path / "llm_data"}
SESSIONS_ROOT={tmp_path / "sessions"}
""")
    c = Config.from_env(env_file_path=env_file)
    assert c.is_bind
    assert c.uses_local_ro
    assert c.mode_id() == "BIND_LOCAL"
    assert c.datasets_host_ro == (tmp_path / "llm_data").resolve()
    assert c.session_dir("abc123") == (tmp_path / "sessions" / "abc123").resolve()


def test_hybrid_mode_ok(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    # Create a temporary env file with TMPFS + HYBRID
    env_file = tmp_path / "test.env"
    env_file.write_text(f"""SESSION_STORAGE=TMPFS
DATASET_ACCESS=HYBRID
HYBRID_LOCAL_PATH={tmp_path / "hybrid_data"}
""")
    c = Config.from_env(env_file_path=env_file)
    assert c.session_storage == SessionStorage.TMPFS
    assert c.dataset_access == DatasetAccess.HYBRID
    assert c.uses_hybrid_mode
    assert c.mode_id() == "TMPFS_HYBRID"
    assert c.hybrid_local_path == (tmp_path / "hybrid_data").resolve()


@pytest.mark.parametrize(
    "sess,dset,expect_mode,needs_ro,needs_hybrid",
    [
        ("TMPFS", "API", "TMPFS_API", False, False),
        ("BIND",  "API", "BIND_API", False, False),
        ("TMPFS", "LOCAL_RO",  "TMPFS_LOCAL", True, False),
        ("BIND",  "LOCAL_RO",  "BIND_LOCAL", True, False),
        ("TMPFS", "HYBRID", "TMPFS_HYBRID", False, True),
        ("BIND",  "HYBRID", "BIND_HYBRID", False, True),
    ],
)
def test_mode_matrix(monkeypatch, tmp_path, sess, dset, expect_mode, needs_ro, needs_hybrid):
    _clear_env(monkeypatch)
    # Create a temporary env file with the test configuration
    env_file = tmp_path / "test.env"
    env_content = f"SESSION_STORAGE={sess}\nDATASET_ACCESS={dset}\n"
    if needs_ro:
        env_content += f"DATASETS_HOST_RO={tmp_path / 'ro_data'}\n"
    if needs_hybrid:
        env_content += f"HYBRID_LOCAL_PATH={tmp_path / 'hybrid_data'}\n"
    env_file.write_text(env_content)
    c = Config.from_env(env_file_path=env_file)
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
    # Create a temporary env file with overrides
    env_file = tmp_path / "test.env"
    env_file.write_text(f"""TMPFS_SIZE_MB=2048
BLOBSTORE_DIR={tmp_path / "blobs"}
ARTIFACTS_DB={tmp_path / "artifacts.sqlite"}
""")
    c = Config.from_env(env_file_path=env_file)
    assert c.tmpfs_size_mb == 2048
    assert c.blobstore_dir == (tmp_path / "blobs").resolve()
    assert c.artifacts_db_path == (tmp_path / "artifacts.sqlite").resolve()


def test_unified_data_path():
    """Test that both API and LOCAL_RO modes use unified /data/ path."""
    c = Config.from_env()
    assert c.container_data_staged == "/data"
    assert c.container_data_ro == "/data"
