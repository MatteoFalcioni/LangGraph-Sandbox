from __future__ import annotations

import io
import tarfile
import time
import shlex
from pathlib import Path
from typing import Optional


def _tar_single_file_bytes(
    dst_name: str,
    data: bytes,
    *,
    mode: int = 0o644,
    mtime: Optional[int] = None,
    uid: int = 0,
    gid: int = 0,
) -> bytes:
    """
    Create an in-memory tar archive with a single file entry named `dst_name`.

    Notes:
      - Only the basename of `dst_name` is used (no directories inside the tar).
      - `mtime` defaults to current time for stable archives if provided.
    """
    safe_name = Path(dst_name).name  # drop any directory components
    if not safe_name:
        raise ValueError("dst_name must include a filename")

    if mtime is None:
        mtime = int(time.time())

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=safe_name)
        info.size = len(data)
        info.mode = mode
        info.mtime = mtime
        info.uid = uid
        info.gid = gid
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.getvalue()


def put_bytes(container, container_path: str, data: bytes, *, mode: int = 0o644) -> None:
    """
    Write `data` to `container_path` inside the container by streaming a single-file
    tar to Docker's put_archive. Overwrites any existing file.

    Parameters
    ----------
    container : docker.models.containers.Container (duck-typed here)
    container_path : str   Absolute path to the destination file in the container.
    data : bytes           File content.
    mode : int             File mode for the created file (default 0644).
    """
    if not container_path or container_path.endswith("/"):
        raise ValueError("container_path must be a file path, not a directory")

    parent = str(Path(container_path).parent).lstrip("/")
    name_in_tar = str(Path(container_path).name)
    tar_bytes = _tar_single_file_bytes(name_in_tar, data, mode=mode)

    # Ensure parent directory exists
    rc, _ = container.exec_run(
        ["/bin/sh", "-lc", f"mkdir -p -- {shlex.quote('/' + parent)}"]  # <-- absolute path
        )

    if rc != 0:
        raise RuntimeError(f"Failed to create directory '/{parent}' in container (rc={rc})")

    # Put the tar into the parent dir
    ok = container.put_archive(path="/" + parent, data=tar_bytes)
    # docker-py returns True on success (older versions may not); be lenient but check if False.
    if ok is False:
        raise RuntimeError(f"put_archive returned False for '/{parent}'")


def file_exists_in_container(container, container_path: str) -> bool:
    """
    Check if a file exists in the container at the given path.
    
    Parameters
    ----------
    container : docker.models.containers.Container (duck-typed here)
    container_path : str   Absolute path to the file in the container.
    
    Returns
    -------
    bool
        True if the file exists, False otherwise.
    """
    rc, _ = container.exec_run(
        ["/bin/sh", "-lc", f"test -f {shlex.quote(container_path)}"]
    )
    return rc == 0
