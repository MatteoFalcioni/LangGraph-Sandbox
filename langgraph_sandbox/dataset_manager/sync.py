# langgraph_sandbox/dataset_manager/sync.py
from __future__ import annotations

from typing import Dict, List
from ..config import Config
from .staging import stage_dataset_into_sandbox, container_staged_path, container_ro_path, container_hybrid_path
from .cache import DatasetStatus, update_entry_status

async def load_pending_datasets(
    *,
    cfg: Config,
    session_id: str,
    container,
    fetch_fn,
    ds_ids: List[str],
) -> List[Dict[str, str]]:
    """
    Load datasets with PENDING status into the sandbox and mark them as LOADED.
    
    This function handles the PENDING -> LOADED transition for API mode datasets.
    For RO mode, it just updates the cache status without actual loading.
    
    Args:
        cfg: Config object with environment and path settings
        session_id: The current session identifier
        container: Docker container handle (required for API mode)
        fetch_fn: Function to fetch dataset bytes by ID
        ds_ids: List of dataset IDs to load (should all be PENDING)
        
    Returns:
        List of descriptors, one per dataset, each a dict with:
            - "id": dataset id
            - "path_in_container": absolute path to the dataset file inside the container
            
    Raises:
        Exception: If loading fails for any dataset
    """
    out: List[Dict[str, str]] = []
    
    for ds_id in ds_ids:
        try:
            if cfg.uses_hybrid_mode and cfg.hybrid_local_path:
                # HYBRID mode: check if dataset exists in heavy_llm_data first
                local_file_path = cfg.hybrid_local_path / f"{ds_id}.parquet"
                
                if local_file_path.exists():
                    # Dataset exists locally, use it (like LOCAL_RO mode)
                    path = container_hybrid_path(cfg, ds_id) # it's mounted at /heavy_data so use hybrid path
                    desc = {
                        "id": ds_id,
                        "path_in_container": path,
                    }
                    update_entry_status(cfg, session_id, ds_id, DatasetStatus.LOADED)
                    out.append(desc)
                    continue
            
            if cfg.uses_api_staging:
                # API mode: actually fetch and stage the dataset
                desc = await stage_dataset_into_sandbox(
                    cfg=cfg,
                    session_id=session_id,
                    container=container,
                    ds_id=ds_id,
                    fetch_fn=fetch_fn,
                )
                # Mark as LOADED after successful staging
                update_entry_status(cfg, session_id, ds_id, DatasetStatus.LOADED)
            else:
                # RO mode: just update cache status, assume file exists
                path = container_ro_path(cfg, ds_id) # it's mounted at start so just fetch path
                desc = {
                    "id": ds_id,
                    "path_in_container": path,
                }
                update_entry_status(cfg, session_id, ds_id, DatasetStatus.LOADED)
            
            out.append(desc)
            
        except Exception as e:
            # Mark as FAILED and re-raise
            update_entry_status(cfg, session_id, ds_id, DatasetStatus.FAILED)
            raise Exception(f"Failed to load dataset {ds_id}: {e}")
    
    return out
