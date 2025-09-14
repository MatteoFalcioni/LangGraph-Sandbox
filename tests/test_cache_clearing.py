import sys
from pathlib import Path

import pytest

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config, SessionStorage, DatasetAccess
from src.datasets.cache import (
    cache_file_path, read_ids, write_ids, add_id, is_cached, clear_cache
)


def _cfg(tmp_path: Path) -> Config:
    return Config(
        session_storage=SessionStorage.TMPFS,
        dataset_access=DatasetAccess.API,
        sessions_root=tmp_path / "sessions",
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )


def test_clear_cache_removes_all_entries(tmp_path):
    """Test that clear_cache removes all cached dataset IDs."""
    cfg = _cfg(tmp_path)
    sid = "test_session"
    
    # Add some datasets to cache
    add_id(cfg, sid, "dataset1")
    add_id(cfg, sid, "dataset2")
    add_id(cfg, sid, "dataset3")
    
    # Verify they are cached
    assert is_cached(cfg, sid, "dataset1")
    assert is_cached(cfg, sid, "dataset2")
    assert is_cached(cfg, sid, "dataset3")
    assert read_ids(cfg, sid) == ["dataset1", "dataset2", "dataset3"]
    
    # Clear the cache
    cache_path = clear_cache(cfg, sid)
    
    # Verify cache is empty
    assert read_ids(cfg, sid) == []
    assert not is_cached(cfg, sid, "dataset1")
    assert not is_cached(cfg, sid, "dataset2")
    assert not is_cached(cfg, sid, "dataset3")
    
    # Verify cache file exists but is empty
    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8").strip() == ""


def test_clear_cache_creates_empty_file_if_not_exists(tmp_path):
    """Test that clear_cache creates an empty cache file even if none existed."""
    cfg = _cfg(tmp_path)
    sid = "new_session"
    
    # Verify no cache file exists initially
    cache_path = cache_file_path(cfg, sid)
    assert not cache_path.exists()
    
    # Clear cache (should create empty file)
    result_path = clear_cache(cfg, sid)
    
    # Verify cache file was created and is empty
    assert result_path == cache_path
    assert cache_path.exists()
    assert read_ids(cfg, sid) == []


def test_clear_cache_works_with_mixed_content(tmp_path):
    """Test that clear_cache works with various content in cache file."""
    cfg = _cfg(tmp_path)
    sid = "mixed_session"
    
    # Create cache with mixed content (duplicates, empty lines, etc.)
    test_ids = ["ds1", "ds2", "ds1", "", "ds3", "ds2", "  ", "ds4"]
    write_ids(cfg, sid, test_ids)
    
    # Verify initial state (should be deduplicated and cleaned)
    assert read_ids(cfg, sid) == ["ds1", "ds2", "ds3", "ds4"]
    
    # Clear cache
    clear_cache(cfg, sid)
    
    # Verify cache is completely empty
    assert read_ids(cfg, sid) == []
    assert not is_cached(cfg, sid, "ds1")
    assert not is_cached(cfg, sid, "ds2")
    assert not is_cached(cfg, sid, "ds3")
    assert not is_cached(cfg, sid, "ds4")


def test_clear_cache_preserves_other_sessions(tmp_path):
    """Test that clearing cache for one session doesn't affect other sessions."""
    cfg = _cfg(tmp_path)
    sid1 = "session1"
    sid2 = "session2"
    
    # Add datasets to both sessions
    add_id(cfg, sid1, "dataset1")
    add_id(cfg, sid1, "dataset2")
    add_id(cfg, sid2, "dataset3")
    add_id(cfg, sid2, "dataset4")
    
    # Verify both sessions have their datasets
    assert read_ids(cfg, sid1) == ["dataset1", "dataset2"]
    assert read_ids(cfg, sid2) == ["dataset3", "dataset4"]
    
    # Clear cache for session1 only
    clear_cache(cfg, sid1)
    
    # Verify session1 is empty but session2 is unaffected
    assert read_ids(cfg, sid1) == []
    assert read_ids(cfg, sid2) == ["dataset3", "dataset4"]
    
    # Verify individual dataset checks
    assert not is_cached(cfg, sid1, "dataset1")
    assert not is_cached(cfg, sid1, "dataset2")
    assert is_cached(cfg, sid2, "dataset3")
    assert is_cached(cfg, sid2, "dataset4")


def test_clear_cache_returns_correct_path(tmp_path):
    """Test that clear_cache returns the correct cache file path."""
    cfg = _cfg(tmp_path)
    sid = "path_test"
    
    # Clear cache and verify returned path
    result_path = clear_cache(cfg, sid)
    expected_path = cache_file_path(cfg, sid)
    
    assert result_path == expected_path
    assert result_path.name == "cache_datasets.txt"
    assert result_path.parent.name == sid


def test_clear_cache_after_adding_new_datasets(tmp_path):
    """Test that cache can be used normally after clearing."""
    cfg = _cfg(tmp_path)
    sid = "reuse_test"
    
    # Add some datasets
    add_id(cfg, sid, "original1")
    add_id(cfg, sid, "original2")
    assert read_ids(cfg, sid) == ["original1", "original2"]
    
    # Clear cache
    clear_cache(cfg, sid)
    assert read_ids(cfg, sid) == []
    
    # Add new datasets after clearing
    add_id(cfg, sid, "new1")
    add_id(cfg, sid, "new2")
    add_id(cfg, sid, "new3")
    
    # Verify new datasets are properly cached
    assert read_ids(cfg, sid) == ["new1", "new2", "new3"]
    assert is_cached(cfg, sid, "new1")
    assert is_cached(cfg, sid, "new2")
    assert is_cached(cfg, sid, "new3")
    assert not is_cached(cfg, sid, "original1")
    assert not is_cached(cfg, sid, "original2")
