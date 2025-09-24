from __future__ import annotations

from pathlib import Path
from typing import Dict

try:
    # Try relative imports first (when used as a module)
    from ..config import Config
    from ..sandbox.io import put_bytes
except ImportError:
    # Fall back to absolute imports (when run directly)
    from config import Config
    from sandbox.io import put_bytes
from .fetcher import fetch_dataset


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


def container_hybrid_path(cfg: Config, ds_id: str) -> str:
    """
    Return the in-container path for a dataset in HYBRID mode (local datasets).
    """
    return f"/heavy_data/{ds_id}.parquet"


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
    fetch_fn = fetch_dataset,
) -> Dict[str, str]:
    """
    Stage a dataset into the sandbox for API mode.
    
    This function fetches the dataset and writes it to the appropriate location
    in the sandbox (either TMPFS or BIND mount).

    Parameters
    ----------
    cfg : Config
        The configuration object containing environment, path, and mode information.
    session_id : str
        The unique identifier for the current session.
    container : object
        Docker container handle. Required for TMPFS mode.
    ds_id : str
        The dataset identifier.
    fetch_fn : callable
        Function to fetch the dataset bytes given a dataset id.

    Returns
    -------
    dict
        A descriptor dictionary with:
            - "id": The dataset id (str)
            - "path_in_container": The absolute path to the dataset file inside the container (str)
    
    Raises
    ------
    Any exceptions raised by fetch_fn or I/O operations will propagate.
    """
    if not cfg.uses_api_staging:
        raise ValueError("stage_dataset_into_sandbox should only be called in API or HYBRID mode")

    # Fetch the dataset bytes
    data = await fetch_fn(ds_id)

    if cfg.is_tmpfs:
        # Write directly into container using the efficient put_bytes function
        filename = f"{ds_id}.parquet"
        container_path = f"/data/{filename}"
        put_bytes(container, container_path, data)
    else:
        # BIND: write to host, appears in container
        dest = host_bind_data_path(cfg, session_id, ds_id)
        _atomic_write_bytes(dest, data)

    result = {
        "id": ds_id,
        "path_in_container": container_staged_path(cfg, ds_id),
    }
    return result
