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


async def stage_dataset_into_sandbox(
    *,
    cfg: Config,
    session_id: str,
    container,               # docker container handle (only needed for TMPFS+API)
    ds_id: str,
    skip_if_cached: bool = True,
    fetch_fn = fetch_dataset,
) -> Dict[str, Optional[str]]:
    """
    Stage a dataset into the sandbox according to the current dataset access mode.

    This function ensures that the specified dataset is available in the sandbox
    (container or host bind mount) for the current session, handling all supported
    dataset access modes (API, LOCAL_RO) and storage backends (TMPFS, BIND).

    Parameters
    ----------
    cfg : Config
        The configuration object containing environment, path, and mode information.
        Must provide access to mode flags (e.g., uses_api_staging, is_tmpfs), and
        path templates for container and host data locations.

    session_id : str
        The unique identifier for the current session. Used to determine the correct
        host-side directory for dataset staging and cache management.

    container : object
        Docker container handle. Required only if using TMPFS+API mode, where bytes
        must be pushed directly into the running container's filesystem. In BIND or
        LOCAL_RO modes, this parameter is ignored.

    ds_id : str
        The dataset identifier (typically a string, e.g., "temperatures" or a UUID).
        Used to locate, fetch, and name the dataset file.

    skip_if_cached : bool, optional (default=True)
        If True, the function will check the host-side cache to see if the dataset
        has already been staged for this session. If so, it will return immediately
        without re-fetching or re-copying the dataset. If False, the dataset will
        always be (re)staged, regardless of cache state.

    fetch_fn : callable, optional (default=fetch_dataset)
        Function to fetch the dataset bytes given a dataset id. Must have the signature
        `fetch_fn(ds_id: str) -> bytes`. Used only in API modes. In LOCAL_RO mode,
        this is ignored.

    Returns
    -------
    dict
        A descriptor dictionary with the following keys:
            - "id": The dataset id (str)
            - "path_in_container": The absolute path to the dataset file inside the container (str)

    Notes
    -----
    - In API mode:
        - TMPFS: The dataset is fetched and written directly into the container's /data directory.
        - BIND:  The dataset is fetched and written to the host-side session directory, which is bind-mounted into the container.
    - In LOCAL_RO mode:
        - No fetching or copying is performed. The dataset is assumed to be available in the container's read-only /data mount.
    - The function always updates the host-side cache list with ds_id (idempotent).
    
    Raises
    ------
    Any exceptions raised by fetch_fn or I/O operations will propagate.

    Examples
    --------
    >>> desc = stage_dataset_into_sandbox(
    ...     cfg=my_cfg,
    ...     session_id="abc123",
    ...     container=my_container,
    ...     ds_id="temperatures",
    ... )
    >>> print(desc["path_in_container"])
    /data/temperatures.parquet
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
        }

    if cfg.uses_api_staging:
        # We actually need the bytes
        data = await fetch_fn(ds_id)

        if cfg.is_tmpfs:
            # Write directly into container tmpfs
            put_bytes(container, container_staged_path(cfg, ds_id), data)
        else:
            # BIND: write to host, appears in container
            dest = host_bind_data_path(cfg, session_id, ds_id)
            _atomic_write_bytes(dest, data)

        # After successful stage, record in host cache with LOADED status
        from src.datasets.cache import update_entry_status, DatasetStatus
        update_entry_status(cfg, session_id, ds_id, DatasetStatus.LOADED)
        path = container_staged_path(cfg, ds_id)

    else:
        # LOCAL_RO: nothing to fetch; just record intent for transparency
        from src.datasets.cache import update_entry_status, DatasetStatus
        update_entry_status(cfg, session_id, ds_id, DatasetStatus.LOADED)
        path = container_ro_path(cfg, ds_id)

    return {
        "id": ds_id,
        "path_in_container": path,
    }
