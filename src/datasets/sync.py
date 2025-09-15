# SRC/datasets/sync.py
from __future__ import annotations

import shlex
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


def _container_file_exists(container, abs_path: str) -> bool:
    rc, _ = container.exec_run(
        ["/bin/sh", "-lc", f"test -f {shlex.quote(abs_path)}"]
    )
    return rc == 0


def sync_datasets(
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
            - "mode": string describing the staging mode (e.g., TMPFS_API, BIND_API)
            - "staged": True if the dataset was copied/staged during this call, False if already present

    Notes:
        - This function does not check or care about dataset access mode (API/LOCAL_RO/etc);
          it assumes the caller has already determined that staging is needed.
        - The cache is not used to skip staging; presence in the container is checked directly.
    """
    out: List[Dict[str, str]] = []

    for ds_id in ds_ids:
        # Compute the expected in-container path for this dataset
        target_in_container = container_staged_path(cfg, ds_id)

        # Check if the dataset file already exists in the container
        need_stage = not _container_file_exists(container, target_in_container)

        if need_stage:
            # Dataset is not present in the container, so fetch and stage it
            desc = stage_dataset_into_sandbox(
                cfg=cfg,
                session_id=session_id,
                container=container,
                ds_id=ds_id,
                skip_if_cached=True,   # Skip if already loaded - we only sync pending datasets
                fetch_fn=fetch_fn,
            )
        else:
            # Dataset is already present in the container; just record its info
            desc = {
                
                "id": ds_id,
                "path_in_container": target_in_container,
                "mode": cfg.mode_id(),
                "staged": False,
            }

        out.append(desc)

    return out
