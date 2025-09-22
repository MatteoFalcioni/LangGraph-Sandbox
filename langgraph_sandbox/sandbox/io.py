from __future__ import annotations

import io
import os
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
    uid: int = 1000,  # Use app user instead of root
    gid: int = 1000,  # Use app user instead of root
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

    # Use chunked method for files that might exceed command line limits
    # Base64 increases size by ~33%, so we need to be more conservative
    base64_size = len(data) * 4 // 3  # Approximate base64 size
    if base64_size > 100 * 1024:  # > 100KB base64 (roughly 75KB original)
        # For potentially large files, use chunked approach
        _write_large_file_chunked(container, container_path, data)
    else:
        # For small files, use base64 method (current approach)
        _write_small_file_base64(container, container_path, data)


def _write_small_file_base64(container, container_path: str, data: bytes) -> None:
    """Write small files using base64 method."""
    import base64
    b64_data = base64.b64encode(data).decode('ascii')
    
    python_code = f"""
import base64
import os

data = '{b64_data}'
file_path = '{container_path}'

# Ensure parent directory exists
os.makedirs(os.path.dirname(file_path), exist_ok=True)

# Write the file
with open(file_path, 'wb') as f:
    f.write(base64.b64decode(data))

print(f"Successfully wrote {{file_path}}")
"""
    
    rc, out = container.exec_run(["/bin/sh", "-lc", f"python3 -c {shlex.quote(python_code)}"])
    if rc != 0:
        raise RuntimeError(f"Failed to write file using base64 method (rc={rc}, output={out})")


def _write_large_file_streaming(container, container_path: str, data: bytes) -> None:
    """Write large files using streaming approach to avoid memory issues."""
    import tempfile
    import os
    
    # Create a temporary file on host
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(data)
        tmp_file.flush()
        tmp_path = tmp_file.name
    
    try:
        # Copy the temporary file to container using exec_run with cat
        # This avoids base64 overhead and command line limits
        with open(tmp_path, 'rb') as f:
            # Use a more efficient method: pipe data directly
            cmd = f"cat > {shlex.quote(container_path)}"
            rc, out = container.exec_run(
                ["/bin/sh", "-c", cmd],
                stdin=True,
                socket=True
            )
            
            # Send data through stdin
            if rc == 0:
                # This is a simplified approach - in practice you'd need to handle the socket properly
                # For now, fall back to chunked base64 for large files
                _write_large_file_chunked(container, container_path, data)
            else:
                raise RuntimeError(f"Failed to write large file (rc={rc}, output={out})")
                
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_path)
        except:
            pass


def _write_large_file_chunked(container, container_path: str, data: bytes) -> None:
    """Write large files in small chunks to avoid command line limits."""
    import base64
    
    # Write file in very small chunks to avoid command line limits
    chunk_size = 4 * 1024  # 4KB chunks (very small for safety)
    chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
    
    # Create directory first
    rc, out = container.exec_run(["/bin/sh", "-lc", f"mkdir -p {shlex.quote(os.path.dirname(container_path))}"])
    if rc != 0:
        raise RuntimeError(f"Failed to create directory (rc={rc}, output={out})")
    
    # Write each chunk separately
    for i, chunk in enumerate(chunks):
        chunk_b64 = base64.b64encode(chunk).decode('ascii')
        
        if i == 0:
            # First chunk: create file
            cmd = f"echo '{chunk_b64}' | base64 -d > {shlex.quote(container_path)}"
        else:
            # Subsequent chunks: append to file
            cmd = f"echo '{chunk_b64}' | base64 -d >> {shlex.quote(container_path)}"
        
        rc, out = container.exec_run(["/bin/sh", "-lc", cmd])
        if rc != 0:
            raise RuntimeError(f"Failed to write chunk {i+1}/{len(chunks)} (rc={rc}, output={out})")


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
