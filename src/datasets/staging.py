from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from src.config import Config
from src.datasets.cache import is_cached, add_id
from src.sandbox.io import put_bytes
from src.datasets.fetcher import fetch_dataset


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def container_staged_path(cfg: Config, ds_id: str) -> str:
    """
    Return the expected in-container path for a dataset id when staged.
    (Used for API mode.)
    """
    return f"{cfg.container_data_staged}/{ds_id}.parquet"


def container_ro_path(cfg: Config, ds_id: str) -> str:
    """
    Return a best-effort in-container RO path for LOCAL_RO mode.
    NOTE: This assumes <id>.parquet naming in the RO mount.
    Adjust later if your LOCAL_RO naming differs.
    """
    return f"{cfg.container_data_ro}/{ds_id}.parquet"


def host_bind_data_path(cfg: Config, session_id: str, ds_id: str) -> Path:
    """
    Host-side path that the container sees at /session/data in BIND mode.
    """
    return cfg.session_dir(session_id) / "data" / f"{ds_id}.parquet"


def stage_dataset_into_sandbox(
    *,
    cfg: Config,
    session_id: str,
    container,               # docker container handle (only needed for TMPFS+API)
    ds_id: str,
    skip_if_cached: bool = True,
    fetch_fn = fetch_dataset,
) -> Dict[str, Optional[str]]:
    """
    Stage a dataset into the sandbox according to current mode.
    - If DATASET_ACCESS=API:
        - TMPFS: push bytes into container:/session/data/<id>.parquet
        - BIND:  write bytes to host ./sessions/<sid>/data/<id>.parquet (bind mount)
    - If DATASET_ACCESS=LOCAL_RO:
        - Do NOT fetch; dataset is assumed available at /data (RO mount).
    - Always update the host-side cache list with ds_id (idempotent).
    - If skip_if_cached=True and ds_id is already in cache, do nothing (early return).

    Returns a small descriptor:
      {
        "id": ds_id,
        "path_in_container": "<container path to use>",
        "mode": "<BIND_LOCAL|TMPFS_LOCAL|TMPFS_API|BIND_API>",
        "staged": true|false,   # whether bytes were written by this call
      }
    """
    # Early exit if cached (even if TMPFS got wiped - should not happen since we have a session per convo)
    # but needs to implement session retrieved in previous convo - then becomes a problem
    if skip_if_cached and is_cached(cfg, session_id, ds_id):
        path = (
            container_staged_path(cfg, ds_id)
            if cfg.uses_api_staging
            else container_ro_path(cfg, ds_id)
        )
        return {
            "id": ds_id,
            "path_in_container": path,
            "mode": cfg.mode_id(),
            "staged": False,
        }

    staged_now = False

    if cfg.uses_api_staging:
        # We actually need the bytes
        data = fetch_fn(ds_id)

        if cfg.is_tmpfs:
            # Write directly into container tmpfs
            put_bytes(container, container_staged_path(cfg, ds_id), data)
            staged_now = True
        else:
            # BIND: write to host, appears in container
            dest = host_bind_data_path(cfg, session_id, ds_id)
            _atomic_write_bytes(dest, data)
            staged_now = True

        # After successful stage, record in host cache
        add_id(cfg, session_id, ds_id)
        path = container_staged_path(cfg, ds_id)

    else:
        # LOCAL_RO: nothing to fetch; just record intent for transparency
        add_id(cfg, session_id, ds_id)
        path = container_ro_path(cfg, ds_id)

    return {
        "id": ds_id,
        "path_in_container": path,
        "mode": cfg.mode_id(),
        "staged": staged_now,
    }
