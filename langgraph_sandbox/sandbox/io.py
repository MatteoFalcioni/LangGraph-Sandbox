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
      - Preserves the full directory structure in the tar.
      - `mtime` defaults to current time for stable archives if provided.
    """
    if not dst_name:
        raise ValueError("dst_name must include a filename")

    if mtime is None:
        mtime = int(time.time())

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=dst_name)  # Use full path, not just basename
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

    # Create tar with just the filename (no directory structure)
    tar_bytes = _tar_single_file_bytes(name_in_tar, data, mode=mode)

    # Ensure parent directory exists using Python (more reliable than mkdir)
    rc, output = container.exec_run(
        ["python3", "-c", f"import os; os.makedirs('/{parent}', exist_ok=True)"]
    )

    if rc != 0:
        raise RuntimeError(f"Failed to create directory '/{parent}' in container (rc={rc})")

    # Try put_archive first, but fallback to direct write if it fails
    # Always failes btw... maybe could remove it entirely adn go with bytes
    try:
        ok = container.put_archive(path="/data", data=tar_bytes)
        
        # Verify the file was actually written
        rc, output = container.exec_run(["ls", "-la", container_path])
        
        if rc == 0:
            print(f"file written to container")
            return
        else:
            print(f"file not found in container, trying direct write...")
    except Exception as e:
        print(f"put_archive exception: {e}, trying direct write...")
    
    import base64
    data_b64 = base64.b64encode(data).decode('ascii')
    
    # Use larger chunks since we don't download huge files
    chunk_size = 10000  # Base64 characters per chunk
    chunks = [data_b64[i:i+chunk_size] for i in range(0, len(data_b64), chunk_size)]
    
    # Create the file and write chunks
    rc, output = container.exec_run(["bash", "-c", f"echo -n > {container_path}"])
    if rc != 0:
        raise RuntimeError(f"Failed to create file {container_path} (rc={rc}): {output.decode()}")
    
    for i, chunk in enumerate(chunks):
        rc, output = container.exec_run([
            "bash", "-c", 
            f"echo -n '{chunk}' | base64 -d >> {container_path}"
        ])
        if rc != 0:
            raise RuntimeError(f"Failed to write chunk {i+1}/{len(chunks)} to {container_path} (rc={rc}): {output.decode()}")

    
    # Final verification
    rc, output = container.exec_run(["ls", "-la", container_path])
    if rc != 0:
        raise RuntimeError(f"File verification failed after direct write: {output.decode()}")


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
