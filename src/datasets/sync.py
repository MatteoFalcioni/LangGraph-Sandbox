# SRC/datasets/sync.py
from __future__ import annotations

from typing import Dict, Iterable, List

from src.config import Config
from src.datasets.staging import (
    stage_dataset_into_sandbox,
    container_ro_path,
    container_staged_path,
    host_bind_data_path,
)
# src/datasets/sync.py
from src.datasets.fetcher import fetch_dataset as _default_fetch

async def sync_datasets(
    *,
    cfg: Config,
    session_id: str,
    fetch_fn=_default_fetch,
    container,
    ds_ids: Iterable[str],
) -> List[Dict[str, str]]:
    """
    Ensure that all requested datasets are available and accessible inside the container
    for the current session. This function is typically used in API dataset access mode,
    where datasets must be explicitly staged (copied) into the container's filesystem.

    For each dataset ID in `ds_ids`:
      - Check if the dataset file already exists in the container at the expected path.
      - If it does not exist, call `stage_dataset_into_sandbox` to fetch and copy the dataset
        into the container (or host bind mount), making it available for use.
      - If it already exists, just record its descriptor (no need to copy again).

    Args:
        cfg: Config object with environment and path settings.
        session_id: The current session identifier.
        fetch_fn: Function to fetch dataset bytes by ID (default: fetch_dataset).
        container: Docker container handle where datasets should be staged.
        ds_ids: Iterable of dataset IDs to ensure are available.

    Returns:
        List of descriptors, one per dataset, each a dict with:
            - "id": dataset id
            - "path_in_container": absolute path to the dataset file inside the container

    Notes:
        - This function does not check or care about dataset access mode (API/LOCAL_RO/etc);
          it assumes the caller has already determined that staging is needed.
        - The cache is used to skip staging; stage_dataset_into_sandbox will check cache internally.
    """
    out: List[Dict[str, str]] = []

    for ds_id in ds_ids:
        # Compute the expected in-container path for this dataset
        target_in_container = container_staged_path(cfg, ds_id)

        # Stage the dataset - stage_dataset_into_sandbox will check cache internally
        desc = await stage_dataset_into_sandbox(
            cfg=cfg,
            session_id=session_id,
            container=container,
            ds_id=ds_id,
            skip_if_cached=True,   # Skip if already loaded - we only sync pending datasets
            fetch_fn=fetch_fn,
        )

        out.append(desc)

    return out
