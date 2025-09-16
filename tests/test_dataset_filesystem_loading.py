import sys
import tempfile
import shutil
from pathlib import Path

import pytest
import pandas as pd

# Make project importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph_sandbox.config import Config, SessionStorage, DatasetAccess
from langgraph_sandbox.datasets.cache import read_ids, add_id, is_cached
from langgraph_sandbox.datasets.staging import stage_dataset_into_sandbox, container_ro_path


class FakeContainer:
    """Fake container for testing - no actual operations needed for LOCAL_RO mode."""
    def __init__(self):
        pass
    
    def exec_run(self, cmd):
        return (0, b"")
    
    def put_archive(self, path, data):
        return True


def _cfg_local_ro(tmp_path: Path, datasets_host_ro: Path) -> Config:
    """Create config for LOCAL_RO mode with specified datasets directory."""
    return Config(
        session_storage=SessionStorage.BIND,  # Use BIND for easier file access
        dataset_access=DatasetAccess.LOCAL_RO,
        sessions_root=tmp_path / "sessions",
        datasets_host_ro=datasets_host_ro,
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )


def _cfg_tmpfs_local_ro(tmp_path: Path, datasets_host_ro: Path) -> Config:
    """Create config for TMPFS + LOCAL_RO mode."""
    return Config(
        session_storage=SessionStorage.TMPFS,
        dataset_access=DatasetAccess.LOCAL_RO,
        sessions_root=tmp_path / "sessions",
        datasets_host_ro=datasets_host_ro,
        blobstore_dir=tmp_path / "blobs",
        artifacts_db_path=tmp_path / "artifacts.sqlite",
    )


def create_test_parquet_files(datasets_dir: Path) -> dict:
    """Create test parquet files and return mapping of dataset_id to file path."""
    datasets_dir.mkdir(parents=True, exist_ok=True)
    
    # Create test datasets
    test_datasets = {}
    
    # Dataset 1: Simple temperature data
    temp_data = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=10, freq='D'),
        'temperature': [20.5, 22.1, 19.8, 21.3, 23.0, 18.9, 20.2, 22.7, 19.5, 21.8],
        'city': ['Rome'] * 10
    })
    temp_file = datasets_dir / "temperatures.parquet"
    temp_data.to_parquet(temp_file)
    test_datasets["temperatures"] = temp_file
    
    # Dataset 2: Statistical zones data
    zones_data = pd.DataFrame({
        'zone_id': [1, 2, 3, 4, 5],
        'zone_name': ['Zone A', 'Zone B', 'Zone C', 'Zone D', 'Zone E'],
        'population': [1000, 1500, 800, 2000, 1200],
        'area_km2': [2.5, 3.2, 1.8, 4.1, 2.9]
    })
    zones_file = datasets_dir / "statistical_zones.parquet"
    zones_data.to_parquet(zones_file)
    test_datasets["statistical_zones"] = zones_file
    
    # Dataset 3: Air quality data
    air_quality_data = pd.DataFrame({
        'station_id': ['AQ001', 'AQ002', 'AQ003'],
        'pm25': [15.2, 18.7, 12.3],
        'pm10': [25.8, 31.2, 20.1],
        'timestamp': pd.date_range('2024-01-01', periods=3, freq='H')
    })
    air_quality_file = datasets_dir / "air_quality.parquet"
    air_quality_data.to_parquet(air_quality_file)
    test_datasets["air_quality"] = air_quality_file
    
    return test_datasets


def test_local_ro_mode_loads_existing_datasets(tmp_path):
    """Test that LOCAL_RO mode can load datasets from filesystem."""
    # Create test datasets directory
    datasets_dir = tmp_path / "test_datasets"
    test_datasets = create_test_parquet_files(datasets_dir)
    
    # Create config for LOCAL_RO mode
    cfg = _cfg_local_ro(tmp_path, datasets_dir)
    sid = "test_session"
    container = FakeContainer()
    
    # Test loading each dataset
    for dataset_id, file_path in test_datasets.items():
        # Stage the dataset
        desc = stage_dataset_into_sandbox(
            cfg=cfg,
            session_id=sid,
            container=container,
            ds_id=dataset_id,
            skip_if_cached=False
        )
        
        # Verify staging descriptor
        assert desc["id"] == dataset_id
        assert desc["staged"] is False  # No staging needed for LOCAL_RO
        assert desc["mode"] == "BIND_LOCAL"
        assert desc["path_in_container"] == container_ro_path(cfg, dataset_id)
        
        # Verify dataset is cached
        assert is_cached(cfg, sid, dataset_id)
    
    # Verify all datasets are in cache
    cached_ids = read_ids(cfg, sid)
    assert set(cached_ids) == set(test_datasets.keys())


def test_local_ro_mode_skip_if_cached(tmp_path):
    """Test that LOCAL_RO mode respects skip_if_cached parameter."""
    datasets_dir = tmp_path / "test_datasets"
    test_datasets = create_test_parquet_files(datasets_dir)
    
    cfg = _cfg_local_ro(tmp_path, datasets_dir)
    sid = "test_session"
    container = FakeContainer()
    
    dataset_id = "temperatures"
    
    # First load - should not be cached
    desc1 = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id=dataset_id,
        skip_if_cached=True
    )
    assert desc1["staged"] is False
    assert is_cached(cfg, sid, dataset_id)
    
    # Second load with skip_if_cached=True - should skip
    desc2 = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id=dataset_id,
        skip_if_cached=True
    )
    assert desc2["staged"] is False
    assert desc2["id"] == dataset_id
    assert desc2["path_in_container"] == container_ro_path(cfg, dataset_id)


def test_local_ro_mode_with_tmpfs(tmp_path):
    """Test LOCAL_RO mode with TMPFS session storage."""
    datasets_dir = tmp_path / "test_datasets"
    test_datasets = create_test_parquet_files(datasets_dir)
    
    cfg = _cfg_tmpfs_local_ro(tmp_path, datasets_dir)
    sid = "tmpfs_session"
    container = FakeContainer()
    
    dataset_id = "statistical_zones"
    
    desc = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id=dataset_id,
        skip_if_cached=False
    )
    
    # Verify staging descriptor for TMPFS + LOCAL_RO
    assert desc["id"] == dataset_id
    assert desc["staged"] is False
    assert desc["mode"] == "TMPFS_LOCAL"
    assert desc["path_in_container"] == container_ro_path(cfg, dataset_id)
    
    # Verify dataset is cached
    assert is_cached(cfg, sid, dataset_id)


def test_local_ro_mode_multiple_sessions(tmp_path):
    """Test that different sessions can load the same datasets independently."""
    datasets_dir = tmp_path / "test_datasets"
    test_datasets = create_test_parquet_files(datasets_dir)
    
    cfg = _cfg_local_ro(tmp_path, datasets_dir)
    container = FakeContainer()
    
    # Load different datasets in different sessions
    session1_datasets = ["temperatures", "air_quality"]
    session2_datasets = ["statistical_zones", "temperatures"]
    
    # Load datasets in session1
    for dataset_id in session1_datasets:
        stage_dataset_into_sandbox(
            cfg=cfg,
            session_id="session1",
            container=container,
            ds_id=dataset_id,
            skip_if_cached=False
        )
    
    # Load datasets in session2
    for dataset_id in session2_datasets:
        stage_dataset_into_sandbox(
            cfg=cfg,
            session_id="session2",
            container=container,
            ds_id=dataset_id,
            skip_if_cached=False
        )
    
    # Verify each session has its own cache
    assert set(read_ids(cfg, "session1")) == set(session1_datasets)
    assert set(read_ids(cfg, "session2")) == set(session2_datasets)
    
    # Verify individual dataset checks
    assert is_cached(cfg, "session1", "temperatures")
    assert is_cached(cfg, "session1", "air_quality")
    assert not is_cached(cfg, "session1", "statistical_zones")
    
    assert is_cached(cfg, "session2", "statistical_zones")
    assert is_cached(cfg, "session2", "temperatures")
    assert not is_cached(cfg, "session2", "air_quality")


def test_local_ro_mode_nonexistent_dataset(tmp_path):
    """Test LOCAL_RO mode behavior with non-existent dataset files."""
    datasets_dir = tmp_path / "test_datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    
    cfg = _cfg_local_ro(tmp_path, datasets_dir)
    sid = "test_session"
    container = FakeContainer()
    
    # Try to load a dataset that doesn't exist on filesystem
    # This should still work (no error) but the file won't be accessible in container
    desc = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id="nonexistent_dataset",
        skip_if_cached=False
    )
    
    # Should still return a descriptor
    assert desc["id"] == "nonexistent_dataset"
    assert desc["staged"] is False
    assert desc["mode"] == "BIND_LOCAL"
    assert desc["path_in_container"] == container_ro_path(cfg, "nonexistent_dataset")
    
    # Should still be cached
    assert is_cached(cfg, sid, "nonexistent_dataset")


def test_local_ro_mode_empty_datasets_directory(tmp_path):
    """Test LOCAL_RO mode with empty datasets directory."""
    datasets_dir = tmp_path / "empty_datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    
    cfg = _cfg_local_ro(tmp_path, datasets_dir)
    sid = "test_session"
    container = FakeContainer()
    
    # Try to load a dataset from empty directory
    desc = stage_dataset_into_sandbox(
        cfg=cfg,
        session_id=sid,
        container=container,
        ds_id="any_dataset",
        skip_if_cached=False
    )
    
    # Should still work
    assert desc["id"] == "any_dataset"
    assert desc["staged"] is False
    assert desc["mode"] == "BIND_LOCAL"
    assert is_cached(cfg, sid, "any_dataset")


def test_local_ro_mode_verifies_parquet_files(tmp_path):
    """Test that we can actually read the parquet files created for testing."""
    datasets_dir = tmp_path / "test_datasets"
    test_datasets = create_test_parquet_files(datasets_dir)
    
    # Verify that the test files are valid parquet files
    for dataset_id, file_path in test_datasets.items():
        assert file_path.exists(), f"Test file {file_path} should exist"
        
        # Try to read the parquet file
        df = pd.read_parquet(file_path)
        assert not df.empty, f"Dataset {dataset_id} should not be empty"
        
        # Verify specific content based on dataset type
        if dataset_id == "temperatures":
            assert "temperature" in df.columns
            assert "date" in df.columns
            assert len(df) == 10
        elif dataset_id == "statistical_zones":
            assert "zone_id" in df.columns
            assert "zone_name" in df.columns
            assert len(df) == 5
        elif dataset_id == "air_quality":
            assert "pm25" in df.columns
            assert "pm10" in df.columns
            assert len(df) == 3
