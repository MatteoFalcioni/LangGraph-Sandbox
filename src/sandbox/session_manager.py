# ---------------------------
# src/session_manager.py
# ---------------------------

import time
import uuid
import os
from typing import Dict, Optional, List

import docker            # Host-side Docker SDK (controls containers)
import httpx             # Lightweight HTTP client to talk to the in-container REPL
from pathlib import Path

import io
import tarfile
import tempfile

from src.artifacts.ingest import ingest_files
from src.sandbox.container_utils import cleanup_sandbox_containers

from enum import Enum

class SessionStorage(str, Enum):
    TMPFS = "TMPFS"   # /session is RAM-backed inside the container
    BIND  = "BIND"    # /session is bind-mounted to ./sessions/<sid> on host

class DatasetAccess(str, Enum):
    NONE      = "NONE"        # no datasets - simple sandbox mode
    API = "API"   # datasets fetched via API into /session/data
    LOCAL_RO  = "LOCAL_RO"    # host datasets mounted read-only at /data


# Docker exposes port mappings as "<container_port>/tcp" in the attrs.
REPL_PORT = "9000/tcp"

# Default image name for the sandbox container. Build it with your Dockerfile.
DEFAULT_IMAGE = "sandbox:latest"

# If a session hasn't been touched for this many seconds, we consider it idle.
# We opportunistically sweep (cleanup) in start/exec calls.
IDLE_TIMEOUT_SECS = 45 * 60  # 45 minutes (tune to your infra)


class SessionInfo:
    """
    Lightweight record for one live session/container.

    Fields:
    - container_id: Docker container ID for the sandbox.
    - host_port: host port mapped to the in-container REPL (container 9000/tcp).
    - session_dir: host path backing the /session bind mount (./sessions/<sid>)
      when SessionStorage.BIND; None when SessionStorage.TMPFS.
    - session_storage: which session backing store is used (TMPFS or BIND).
    - last_used: unix timestamp, used to evict idle sessions.
    """
    def __init__(
        self,
        container_id: str,
        host_port: int,
        session_dir: Path | None,
        session_storage: SessionStorage
    ):
        self.container_id = container_id
        self.host_port = host_port
        self.session_dir = session_dir
        self.session_storage = session_storage
        self.last_used = time.time()


class SessionManager:
    """
    Manage long-lived sandbox containers (one per conversation) with two orthogonal
    choices:

    1) **Session storage** (where /session lives):
       - SessionStorage.TMPFS (recommended): /session is RAM-backed inside the container.
         Artifacts created under /session/artifacts/** are copied out after each run
         and ingested into your artifact store (blob + DB). Nothing touches host disk
         unless explicitly exported.
       - SessionStorage.BIND: /session is backed by ./sessions/<sid> on the host.
         Useful for local inspection/debugging. Artifacts are detected by diffing the
         host folder and then ingested.

    2) **Dataset access** (how code sees datasets):
       - DatasetAccess.API (default): your tools fetch datasets and stage them
         into /session/data before code execution. No /data mount is used.
       - DatasetAccess.LOCAL_RO: mount a host datasets directory at /data (read-only).
         No API staging is performed.

    The manager starts/reattaches containers, probes the in-container REPL, executes
    code via HTTP, detects newly created artifacts, and hands those files to the
    artifact ingestion pipeline for deduplication and durable storage.
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        session_storage: SessionStorage = SessionStorage.TMPFS,
        dataset_access: DatasetAccess = DatasetAccess.API,
        datasets_path: Optional[Path] = None,
        session_root: Path = Path("sessions"),
        tmpfs_size: str = "1g",
    ):
        """
        Args:
            image: Docker image name for the sandbox.
            session_storage: Where /session is backed (TMPFS or BIND).
            dataset_access: How datasets are exposed (API or LOCAL_RO).
            datasets_path: Required when dataset_access=LOCAL_RO; mounted at /data (RO).
            session_root: Base host dir for per-session folders when using BIND.
            tmpfs_size: Soft cap (e.g., "1g", "512m") for /session when using TMPFS.
        """
        self.client = docker.from_env()
        self.image = image
        self.session_storage = session_storage
        self.dataset_access = dataset_access

        # Validate dataset invariants
        if self.dataset_access == DatasetAccess.LOCAL_RO:
            if not datasets_path:
                raise ValueError("datasets_path is required when dataset_access=LOCAL_RO")
            self.datasets_path = Path(datasets_path).resolve()
        else:
            # NONE or API -> Do not mount /data
            self.datasets_path = None

        self.session_root = Path(session_root).resolve()
        self.tmpfs_size = tmpfs_size

        # In-memory registry: session_key -> SessionInfo
        self.sessions: Dict[str, SessionInfo] = {}

    def _sweep_idle(self):
        """
        Remove containers that have been idle longer than IDLE_TIMEOUT_SECS and drop their
        SessionInfo entries. Called opportunistically at start() and exec().

        Notes:
        - In TMPFS mode this also discards any in-memory /session contents (expected).
        - Best-effort cleanup: if Docker already removed the container, we still clear
          local bookkeeping.
        """
        now = time.time()
        for sid, info in list(self.sessions.items()):
            if now - info.last_used > IDLE_TIMEOUT_SECS:
                try:
                    self.client.containers.get(info.container_id).remove(force=True)
                except Exception:
                    pass  # Best-effort
                self.sessions.pop(sid, None)

    def start(self, session_key: Optional[str] = None) -> str:
        """
        Start (or reattach to) the sandbox container for a given session_key.

        Behavior:
        1) Evict idle sessions.
        2) Reuse the container named 'sbox-<sid>' if it exists; otherwise run a new one.
        3) Mount /session based on session_storage:
           - TMPFS → tmpfs (RAM) with size=tmpfs_size.
           - BIND  → bind mount ./sessions/<sid> → /session (RW).
        4) Mount datasets at /data (RO) only when dataset_access=LOCAL_RO.
        5) Probe the in-container REPL /health until ready.
        6) Register and return the session_key.

        Returns:
            The resolved session_key (existing or newly created).
        """
        self._sweep_idle()

        # If we already have a live SessionInfo for this sid, just return it.
        if session_key and session_key in self.sessions:
            return session_key

        # Choose the session id.
        sid = session_key or f"anon-{uuid.uuid4().hex[:8]}"
        name = f"sbox-{sid}"

        # Compute host session dir depending on storage mode
        sess_dir: Path | None = None
        if self.session_storage == SessionStorage.BIND:
            sess_dir = (self.session_root / sid).resolve()
            sess_dir.mkdir(parents=True, exist_ok=True)

        # --- Fast path: reattach if container exists
        try:
            existing = self.client.containers.get(name)
            if existing.status not in ("running",):
                existing.start()
            existing.reload()
            host_port = int(existing.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])
            # Ensure session_dir is set correctly based on current storage mode
            if self.session_storage == SessionStorage.BIND:
                sess_dir = (self.session_root / sid).resolve()
                sess_dir.mkdir(parents=True, exist_ok=True)
            self.sessions[sid] = SessionInfo(existing.id, host_port, sess_dir, self.session_storage)
            return sid
        except docker.errors.NotFound:
            pass  # create a new container

        # Build mounts
        volumes: Dict[str, Dict[str, str]] = {}
        tmpfs: Dict[str, str] = {}

        # /session mount
        if self.session_storage == SessionStorage.TMPFS:
            tmpfs["/session"] = f"rw,size={self.tmpfs_size},mode=1777"
        else:
            volumes[str(sess_dir)] = {"bind": "/session", "mode": "rw"}

        # /data (datasets) only if LOCAL_RO
        if self.dataset_access == DatasetAccess.LOCAL_RO:
            volumes[str(self.datasets_path)] = {"bind": "/data", "mode": "ro"}
        # NONE and API modes don't mount /data

        # Run container (random host port for REPL)
        container = self.client.containers.run(
            self.image,
            detach=True,
            mem_limit="8g",                 # tune for your infra/tenancy
            nano_cpus=2_000_000_000,       # ~2 vCPU
            ports={"9000/tcp": None},      # random host port for REPL
            volumes=volumes,
            tmpfs=tmpfs or None,
            name=name,
        )
        container.reload()
        host_port = int(container.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])

        # Wait for /health quickly (best-effort)
        with httpx.Client(timeout=5.0) as http:
            for _ in range(50):  # ~5s worst case
                try:
                    r = http.get(f"http://127.0.0.1:{host_port}/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

        self.sessions[sid] = SessionInfo(container.id, host_port, sess_dir, self.session_storage)
        return sid

    def get_session_dir(self, session_key: str) -> Path:
        """
        Return the host directory backing /session (BIND mode only).

        Raises:
            RuntimeError: if session_storage is TMPFS (no host session directory exists)
            or the session is unknown/expired.
        """
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown or expired session_key. Call start() first.")
        if info.session_storage == SessionStorage.TMPFS or not info.session_dir:
            raise RuntimeError("No host session directory when SessionStorage=TMPFS.")
        return info.session_dir

    def container_for(self, session_key: str):
        """
        Return the Docker container object for the given session.
        
        Args:
            session_key: The session identifier
            
        Returns:
            Docker container object
            
        Raises:
            RuntimeError: if session is unknown/expired
        """
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown or expired session_key. Call start() first.")
        return self.client.containers.get(info.container_id)

    def _list_artifact_files_host(self, session_dir: Path) -> set[str]:
        """
        [BIND MODE] List all artifact file paths currently present under
        ./sessions/<sid>/artifacts/** on the host.

        Returns:
            A set of POSIX-style relative paths (relative to the session root), so callers
            can form both container paths (/session/<relative>) and host paths
            (session_dir / <relative>).
        """
        if session_dir is None:
            return set()
        art = session_dir / "artifacts"
        if not art.exists():
            return set()
        return {
            str(p.relative_to(session_dir).as_posix())  # POSIX-style for container paths
            for p in art.rglob("*")
            if p.is_file()
        }

    def _list_artifact_files_container(self, container) -> set[str]:
        """
        [TMPFS MODE] List artifact files inside the container by running `find` under
        /session/artifacts, and return their relative paths.

        Returns:
            A set of POSIX-style relative paths (relative to /session), e.g.
            {"artifacts/run_123/plot.png", ...}.
        """
        cmd = [
            "bash", "-lc",
            "set -euo pipefail; "
            "if [ -d /session/artifacts ]; then find /session/artifacts -type f -printf '%P\\n'; fi"
        ]
        rc, out = container.exec_run(cmd, demux=True)
        if rc != 0:
            return set()
        stdout = (out[0] or b"").decode("utf-8", errors="ignore")
        rels = set()
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rels.add(f"artifacts/{line}")
        return rels

    def _copy_from_container(self, container, container_path: str, dst_dir: Path) -> Path:
        """
        [TMPFS MODE] Robustly copy a single file from the container's /session to the host.

        Strategy with small retries (to avoid tmpfs timing/metadata races):
        1) Docker API get_archive(file)
        2) Docker API get_archive(parent_dir) and extract 'filename'
        3) In-container: tar to stdout via exec_run('tar -C parent -cf - filename')

        Returns:
            Path to the host file at dst_dir/<filename>.
        Raises:
            RuntimeError if all strategies fail after retries.
        """
        dst_dir.mkdir(parents=True, exist_ok=True)
        filename = os.path.basename(container_path)
        parent   = os.path.dirname(container_path)

        def _extract_one(tar_bytes: bytes, want_name: str, out_path: Path) -> Path:
            bio = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=bio, mode="r:*") as tar:
                # try exact name; else fallback to basename match
                member = tar.getmember(want_name) if want_name in tar.getnames() else None
                if member is None:
                    for m in tar.getmembers():
                        if m.isfile() and os.path.basename(m.name) == want_name:
                            member = m
                            break
                if member is None:
                    raise RuntimeError(f"No regular file '{want_name}' in archive ({container_path})")
                with tar.extractfile(member) as fsrc, open(out_path, "wb") as fdst:
                    fdst.write(fsrc.read())
            return out_path

        # a few quick retries to smooth out FS propagation on tmpfs
        for attempt in range(5):
            # 1) direct get_archive(file)
            try:
                bits, _ = container.get_archive(container_path)
                data = b"".join(bits)
                return _extract_one(data, filename, dst_dir / filename)
            except docker.errors.NotFound:
                pass
            except Exception:
                if attempt == 4:
                    raise

            # 2) get_archive(parent) and extract filename
            try:
                bits, _ = container.get_archive(parent)
                data = b"".join(bits)
                return _extract_one(data, filename, dst_dir / filename)
            except docker.errors.NotFound:
                pass
            except Exception:
                if attempt == 4:
                    raise

            # 3) exec tar in the container and read from stdout
            try:
                rc, out = container.exec_run(
                    ["bash", "-lc", f"set -euo pipefail; cd {parent} && tar -cf - {filename}"],
                    demux=True
                )
                if rc == 0:
                    stdout = out[0] or b""
                    return _extract_one(stdout, filename, dst_dir / filename)
            except Exception:
                if attempt == 4:
                    raise

            time.sleep(0.05)  # brief backoff, then retry

        raise RuntimeError(f"Failed to copy {container_path} from container after retries")
    def exec(self, session_key: str, code: str, timeout: int = 30) -> dict:
        """
        Execute Python code inside the session's container via the in-container REPL.

        Flow:
        1) Validate session and update last_used.
        2) Snapshot artifact files "before" execution:
           - TMPFS: scan inside container.
           - BIND : scan host ./sessions/<sid>/artifacts.
        3) POST code to /exec on the REPL (imports and variables persist in RAM).
        4) Snapshot "after" and diff to find newly created artifacts.
        5) Copy only the new files to the host (TMPFS) or read from host (BIND),
           then ingest into the artifact store (blob + DB).
        6) Return the REPL result plus artifact descriptors.

        Returns:
            dict with keys:
              - ok: bool
              - stdout: str
              - error: str (present when ok == False)
              - artifacts: list[ArtifactDescriptor] (new files ingested this call)
              - session_dir: "" in TMPFS mode, or absolute host path in BIND mode

        Notes:
            In TMPFS mode, there is no persistent host session directory; artifacts are
            exported and persisted via the artifact store only.
        """
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown or expired session_key. Call start() first.")

        # Mark as used (keep alive)
        info.last_used = time.time()

        container = self.client.containers.get(info.container_id)

        # Snapshot BEFORE
        if info.session_storage == SessionStorage.TMPFS:
            before = self._list_artifact_files_container(container)
        else:
            before = self._list_artifact_files_host(info.session_dir)

        # Execute via REPL
        with httpx.Client(timeout=timeout + 5) as http:
            r = http.post(
                f"http://127.0.0.1:{info.host_port}/exec",
                json={"code": code, "timeout": timeout},
            )
            r.raise_for_status()
            result = r.json()  # {ok, stdout, error?}

        # Snapshot AFTER & diff
        if info.session_storage == SessionStorage.TMPFS:
            after = self._list_artifact_files_container(container)
        else:
            after = self._list_artifact_files_host(info.session_dir)
        new_rel_paths = sorted(after - before)

        if info.session_storage == SessionStorage.TMPFS and new_rel_paths:
            time.sleep(0.03)  # give tmpfs a tick to settle before copy-out

        # Materialize new files on host
        if info.session_storage == SessionStorage.TMPFS:
            staging_dir = Path(tempfile.mkdtemp(prefix="sbox_art_batch_"))
            host_files = [
                self._copy_from_container(container, f"/session/{rel}", staging_dir)
                for rel in new_rel_paths
            ]
        else:
            if info.session_dir is None:
                raise RuntimeError("Session directory is None in BIND mode. This should not happen.")
            host_files = [(info.session_dir / rel).resolve() for rel in new_rel_paths]

        # Ingest
        descriptors = ingest_files(
            new_host_files=host_files,
            session_id=session_key,
            run_id=None,
            tool_call_id=None,
        )

        # Response
        result["artifacts"] = descriptors
        result["session_dir"] = "" if info.session_storage == SessionStorage.TMPFS else str(info.session_dir or "")
        return result

    def stop(self, session_key: str) -> None:
        """
        Stop and remove the container for the given session_key and drop it from the
        in-memory registry. Idempotent: no error if the session is unknown.

        TMPFS mode:
            All /session contents are lost when the container is removed (expected).
        BIND mode:
            The host directory ./sessions/<sid> is left intact.
        """
        info = self.sessions.pop(session_key, None)
        if not info:
            return
        try:
            self.client.containers.get(info.container_id).remove(force=True)
        except Exception:
            pass  # Best-effort

    def cleanup_all_containers(self, verbose: bool = True) -> List[str]:
        """
        Clean up all sandbox containers to avoid conflicts.
        
        Args:
            verbose: Whether to print cleanup messages
            
        Returns:
            List of container names that were removed
        """
        return cleanup_sandbox_containers(verbose=verbose)
