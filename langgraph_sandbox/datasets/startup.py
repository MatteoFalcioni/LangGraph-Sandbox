# langgraph_sandbox/datasets/startup.py
"""
Startup script to initialize LOCAL_RO datasets into the cache system.
This runs once at startup to populate the cache with available datasets.
"""

import sys
from pathlib import Path
from typing import List

# Add project root to path for standalone execution
if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

from ..config import Config, DatasetAccess
from .cache import write_ids


def discover_local_datasets(cfg: Config) -> List[str]:
    """
    Discover available datasets in the LOCAL_RO datasets directory.
    
    Args:
        cfg: Configuration object
        
    Returns:
        List of dataset IDs (filenames without .parquet extension)
    """
    if not cfg.uses_local_ro:
        return []
    
    if not cfg.datasets_host_ro or not cfg.datasets_host_ro.exists():
        print(f"Warning: LOCAL_RO datasets directory not found: {cfg.datasets_host_ro}")
        return []
    
    datasets = []
    for file_path in cfg.datasets_host_ro.glob("*.parquet"):
        # Extract dataset ID from filename (remove .parquet extension)
        dataset_id = file_path.stem
        datasets.append(dataset_id)
    
    return sorted(datasets)


def initialize_local_datasets(cfg: Config, session_id: str = "global") -> List[str]:
    """
    Initialize LOCAL_RO datasets by discovering them and writing to cache.
    This should be called once at startup when using LOCAL_RO mode.
    
    Args:
        cfg: Configuration object
        session_id: Session ID to use for cache (default: "global" for startup)
        
    Returns:
        List of discovered dataset IDs
    """
    if cfg.uses_no_datasets:
        print("Skipping dataset initialization (using NONE mode - no datasets)")
        return []
    elif not cfg.uses_local_ro:
        print("Skipping LOCAL_RO dataset initialization (not using LOCAL_RO mode)")
        return []
    
    print(f"Discovering LOCAL_RO datasets in: {cfg.datasets_host_ro}")
    datasets = discover_local_datasets(cfg)
    
    if not datasets:
        print("No datasets found in LOCAL_RO directory")
        return []
    
    # Write discovered datasets to cache
    cache_path = write_ids(cfg, session_id, datasets)
    
    print(f"Initialized {len(datasets)} LOCAL_RO datasets:")
    for dataset in datasets:
        print(f"  - {dataset}")
    print(f"Cache written to: {cache_path}")
    
    return datasets


def get_available_datasets(cfg: Config, session_id: str = "global") -> List[str]:
    """
    Get list of available datasets for the current configuration.
    
    Args:
        cfg: Configuration object
        session_id: Session ID to check
        
    Returns:
        List of available dataset IDs
    """
    if cfg.uses_no_datasets:
        # For NONE mode, no datasets are available
        return []
    elif cfg.uses_local_ro:
        # For LOCAL_RO, return discovered datasets
        return discover_local_datasets(cfg)
    else:
        # For API, return cached datasets (populated by select_datasets)
        from datasets.cache import read_ids
        return read_ids(cfg, session_id)


if __name__ == "__main__":
    # Allow running as standalone script for testing
    try:
        cfg = Config.from_env()
        datasets = initialize_local_datasets(cfg)
        print(f"Discovered {len(datasets)} datasets: {datasets}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
