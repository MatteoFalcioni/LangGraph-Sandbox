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
    Ensure datasets are usable for this run and return their in-container paths.
    Returns a list of descriptors: {"id", "path_in_container", "mode", "staged"}.
    Main tool script already checks if the system uses API staging -> no need to check here.
    """
    out: List[Dict[str, str]] = []

    for ds_id in ds_ids:

        # API_TMPFS
        target_in_container = container_staged_path(cfg, ds_id)

        # check if the dataset already exists in the container
        need_stage = not _container_file_exists(container, target_in_container) # already exists in container -> do not stage

        if need_stage:
            desc = stage_dataset_into_sandbox(
                cfg=cfg,
                session_id=session_id,
                container=container,
                ds_id=ds_id,
                skip_if_cached=False,      # force (re)stage when needed
                fetch_fn=fetch_fn,
            )
        else:
            # Already present; just mirror the descriptor shape
            desc = {
                "id": ds_id,
                "path_in_container": target_in_container,
                "mode": cfg.mode_id(),
                "staged": False,
            }

        out.append(desc)

    return out
