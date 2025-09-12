# ---------------------------
# src/session_manager.py
# ---------------------------

import time
import uuid
from typing import Dict, Optional

import docker           # Host-side Docker SDK (controls containers)
import httpx            # Lightweight HTTP client to talk to the in-container REPL
from pathlib import Path

import io
import tarfile
import tempfile

from src.artifacts.ingest import ingest_files


# Docker exposes port mappings as "<container_port>/tcp" in the attrs.
REPL_PORT = "9000/tcp"

# Default image name for the sandbox container. Build it with your Dockerfile.
DEFAULT_IMAGE = "py-sandbox:latest"

# If a session hasn't been touched for this many seconds, we consider it idle.
# We opportunistically sweep (cleanup) in start/exec calls.
IDLE_TIMEOUT_SECS = 45 * 60  # 45 minutes (tune to your infra)

class SessionInfo:
    """
    Lightweight record for one live session/container.

    Fields:
    - container_id: Docker container ID for the sandbox.
    - host_port: host port mapped to the in-container REPL (container 9000/tcp).
    - session_dir: host path backing the /session bind mount (./sessions/<sid>) when
    using bind-mount mode; None when /session is tmpfs (RAM-backed).
    - use_tmpfs: True if /session is mounted as tmpfs (RAM) inside the container.
    - last_used: unix timestamp, used to evict idle sessions.
    """
    def __init__(self, container_id: str, host_port: int, session_dir: Path | None, use_tmpfs: bool):
        self.container_id = container_id
        self.host_port = host_port
        self.session_dir = session_dir          # None when tmpfs is used
        self.use_tmpfs = use_tmpfs
        self.last_used = time.time()


class SessionManager:
    """
    Manage long-lived sandbox containers (one per conversation), with two storage modes
    for /session and optional legacy dataset mounting:

    - /session storage (choose one):
    1) tmpfs mode (recommended): /session is RAM-backed inside the container.
        Datasets and artifacts live only for the container lifetime and never touch
        host disk. New artifacts created under /session/artifacts are copied out
        after each run and ingested into the artifact store (blob + DB).

    2) bind-mount mode: /session is backed by ./sessions/<sid> on the host.
        Useful for local inspection/debugging; artifacts are detected by diffing
        the host folder and then ingested.

    - Datasets (choose one):
    A) On-demand fetch (current default): dedicated tools fetch datasets and stage
        them into /session/data inside the container before code execution.

    B) Legacy mount: optionally mount a host datasets folder read-only at /data.

    The manager starts/reattaches containers, probes the in-container REPL, executes
    code via HTTP, detects newly created artifacts, and hands those files to the
    artifact ingestion pipeline for deduplication and durable storage.
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        datasets_path: Optional[Path] = None,
        session_root: Path = Path("sessions"),
        use_tmpfs: bool = False,
        tmpfs_size: str = "1g",
    ):
        """
        Args:
            image: Docker image name for the sandbox.
            datasets_path: Optional host path to mount read-only at /data (legacy dataset
                delivery; set to None to disable).
            session_root: Host directory used to create ./sessions/<sid> when using
                bind-mount mode. Ignored when use_tmpfs=True.
            use_tmpfs: If True, mount /session as tmpfs (RAM) inside the container
                (no host session directory; ephemeral by design).
            tmpfs_size: Soft cap for the /session tmpfs (e.g., "1g", "512m"). Only used
                when use_tmpfs=True.
        """

        # Create a Docker client bound to the host's Docker daemon.
        self.client = docker.from_env()
        self.image = image

        # Optional datasets root; mounted read-only at /data inside the container.
        self.datasets_path = Path(datasets_path).resolve() if datasets_path else None

        # Where we keep per-session folders on the host **if not using tmpfs**.
        # Each session will have: sessions/<sid> (bind-mounted to /session)
        self.session_root = Path(session_root).resolve()

        # tmpfs options
        self.use_tmpfs = use_tmpfs
        self.tmpfs_size = tmpfs_size

        # In-memory registry: session_key -> SessionInfo
        self.sessions: Dict[str, SessionInfo] = {}

    def _sweep_idle(self):
        """
        Remove containers that have been idle longer than IDLE_TIMEOUT_SECS and drop their
        SessionInfo entries. Called opportunistically at start() and exec().

        Notes:
        - In tmpfs mode this also discards any in-memory /session contents (expected).
        - Best-effort cleanup: if Docker already removed the container, we still clear
        local bookkeeping.
        """
        now = time.time()
        for sid, info in list(self.sessions.items()):
            if now - info.last_used > IDLE_TIMEOUT_SECS:
                try:
                    # Try to remove the actual container (force kills if needed).
                    self.client.containers.get(info.container_id).remove(force=True)
                except Exception:
                    # Best-effort; if removal fails, still drop local bookkeeping.
                    pass
                self.sessions.pop(sid, None)

    def start(self, session_key: Optional[str] = None) -> str:
        """
        Start (or reattach to) the sandbox container for a given session_key.

        Behavior:
        1) Evict idle sessions.
        2) Reuse the container named 'sbox-<sid>' if it exists; otherwise run a new one.
        3) Mount /session according to the chosen mode:
            - use_tmpfs=True  → /session is tmpfs (RAM) with size=tmpfs_size.
            - use_tmpfs=False → bind mount ./sessions/<sid> → /session (RW).
        4) Optionally mount datasets_path → /data (RO) if provided (legacy mode).
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

        # Stable container name so we can reattach if it survives our process.
        name = f"sbox-{sid}"

        # Prepare host session directory only when NOT using tmpfs.
        sess_dir = None
        if not self.use_tmpfs:
            sess_dir = (self.session_root / sid).resolve()
            sess_dir.mkdir(parents=True, exist_ok=True)

        # --- Fast path: if Docker still has a container with that name, reuse it.
        try:
            existing = self.client.containers.get(name)
            # Make sure it's running (it might be created or exited).
            if existing.status not in ("running",):
                existing.start()
            existing.reload()  # refresh attrs
            # Obtain the host port mapped to container's 9000/tcp.
            host_port = int(existing.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])
            self.sessions[sid] = SessionInfo(existing.id, host_port, sess_dir)
            return sid
        except docker.errors.NotFound:
            # Not there -> fall through to create a brand new container.
            pass

        # Build mounts
        volumes = {}
        tmpfs = {}
        if self.use_tmpfs:
            # /session lives in RAM, limited by tmpfs_size
            # mode=1777 allows all users inside container to write (like /tmp)
            tmpfs["/session"] = f"rw,size={self.tmpfs_size},mode=1777"
        else:
            # Build volume mapping:
            #   - ./sessions/<sid>  -> /session (RW)
            volumes[str(sess_dir)] = {"bind": "/session", "mode": "rw"}
        
        #   - datasets_path     -> /data (RO)  [optional]
        if self.datasets_path and self.datasets_path.exists():
                volumes[str(self.datasets_path)] = {"bind": "/data", "mode": "ro"}

        # Run the container in detached mode. We do NOT fix the host port:
        # 'ports={"9000/tcp": None}' asks Docker to allocate a random free host port,
        # which we read back from the container attrs.
        container = self.client.containers.run(
            self.image,
            detach=True,
            mem_limit="8g",                 # resource caps: tune for your infra/tenancy
            nano_cpus=2_000_000_000,       # ~ 2 vCPU worth of time-slice
            ports={"9000/tcp": None},      # random host port for REPL
            volumes=volumes,               # bind mounts (/session and optional /data)
            tmpfs=tmpfs or None,  # only pass when non-empty
            name=name,                     # stable name so we can reattach later
        )
        container.reload()
        host_port = int(container.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])

        # Wait until the in-container FastAPI REPL responds on /health.
        # Keep this snappy—short polls with a low timeout—and don't crash
        # the process if the service takes a moment to boot.
        with httpx.Client(timeout=5.0) as http:
            for _ in range(50):  # ~5 seconds worst case (50 * 0.1s)
                try:
                    r = http.get(f"http://127.0.0.1:{host_port}/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    # swallow transient connection errors during boot
                    pass
                time.sleep(0.1)

        # Register in-memory and return the key.
        self.sessions[sid] = SessionInfo(container.id, host_port, sess_dir, self.use_tmpfs)
        return sid
    
    def get_session_dir(self, session_key: str) -> Path:
        """
        Return the host directory backing /session (bind-mount mode only).

        Raises:
            RuntimeError: if use_tmpfs=True (no host session directory exists) or the
            session is unknown/expired.
        """
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown or expired session_key. Call start() first.")
        if info.use_tmpfs or not info.session_dir:
            raise RuntimeError("No host session directory when use_tmpfs=True.")
        return info.session_dir

    def _list_artifact_files_host(self, session_dir: Path) -> set[str]:
        """
        [BIND-MOUNT MODE]: list all artifact file paths currently present under
        ./sessions/<sid>/artifacts/** on the host.

        Returns:
            A set of POSIX-style relative paths (relative to the session root), so callers
            can form both container paths (/session/<relative>) and host paths
            (session_dir / <relative>).
        """

        art = session_dir / "artifacts"
        if not art.exists():
            return set()
        return {
            # normalize to POSIX-style for container paths
            str(p.relative_to(session_dir).as_posix())
            for p in art.rglob("*")
            if p.is_file()
        }
    
    def _list_artifact_files_container(self, container) -> set[str]:
        """
        [TMPFS MODE]: list artifact files inside the container by running `find` under
        /sesion/artifacts, and return their relative paths.

        Returns:
            A set of POSIX-style relative paths (relative to /session), e.g.
            {"artifacts/run_123/plot.png", ...}.

        Note:
            The 'base' parameter is unused in the current implementation.
        """

        cmd = ["bash", "-lc", "set -euo pipefail; if [ -d /session/artifacts ]; then find /session/artifacts -type f -printf '%P\\n'; fi"]
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
        [TMPFS MODE]: copy a single file from the container's /session into a temporary
        host file using Docker's get_archive (tar stream). The host file is then suitable
        for ingestion into the artifact store.

        Args:
            container: Docker container object.
            container_path: Absolute path inside the container (e.g., "/session/artifacts/x.png").
            dst_dir: (Unused) Intended host directory for the copy; currently the method
                creates a unique temp directory per file.

        Returns:
            Path to the temporary host file containing the copied data.

        Notes:
            The 'dst_dir' argument is currently not used; consider honoring it or removing
            it from the signature for clarity.
        """
        bits, _ = container.get_archive(container_path)
        bio = io.BytesIO()
        for chunk in bits:
            bio.write(chunk)
        bio.seek(0)
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            member = next((m for m in tar.getmembers() if m.isfile()), None)
            if member is None:
                raise RuntimeError(f"No regular file in archive: {container_path}")
            with tar.extractfile(member) as fsrc:
                tmpdir = Path(tempfile.mkdtemp(prefix="sbox_art_"))
                dst = tmpdir / Path(container_path).name
                with open(dst, "wb") as fdst:
                    fdst.write(fsrc.read())
                return dst

    def exec(self, session_key: str, code: str, timeout: int = 30) -> dict:
        """
        Execute Python code inside the session's container via the in-container REPL.

        Flow:
        1) Validate session and update last_used.
        2) Snapshot artifact files "before" execution:
            - tmpfs mode: scan inside container.
            - bind-mount mode: scan host ./sessions/<sid>/artifacts.
        3) POST code to /exec on the REPL (imports and variables persist in RAM).
        4) Snapshot "after" and diff to find newly created artifacts.
        5) Copy only the new files to the host (tmpfs mode) or read from host
            (bind-mount mode), then ingest into the artifact store (blob + DB).
        6) Return the REPL result plus artifact descriptors.

        Returns:
            dict with keys:
            - ok: bool
            - stdout: str
            - error: str (present when ok == False)
            - artifacts: list[ArtifactDescriptor] (new files ingested this call)
            - session_dir: "" in tmpfs mode, or absolute host path in bind-mount mode

        Notes:
            This method does not retain a host-side session folder when use_tmpfs=True;
            artifacts are exported and persisted via the artifact store only.
        """

        info = self.sessions.get(session_key)
        if not info:
            # This is a programmer error in the caller: they must call start() once.
            raise RuntimeError("Unknown or expired session_key. Call start() first.")

        # Mark as used (keeps it alive).
        info.last_used = time.time()

        container = self.client.containers.get(info.container_id)

        # --- Snapshot BEFORE execution.
        if info.use_tmpfs:
            before = self._list_artifact_files_container(container)
        else:
            before = self._list_artifact_files_host(info.session_dir)

        # --- Execute code by calling the in-container REPL API.
        # The REPL holds a shared GLOBAL_NS dict, so imports and variables persist in RAM.
        with httpx.Client(timeout=timeout + 5) as http:
            r = http.post(
                f"http://127.0.0.1:{info.host_port}/exec",
                json={"code": code, "timeout": timeout},
            )
            r.raise_for_status()              # raise if HTTP-level error
            result = r.json()                 # {ok, stdout, error?}

        # --- Snapshot artifacts AFTER execution and diff to get only new files.
        # --- Snapshot AFTER & diff
        if info.use_tmpfs:
            after = self._list_artifact_files_container(container)
        else:
            after = self._list_artifact_files_host(info.session_dir)
        new_rel_paths = sorted(after - before)

        # --- Build host file list for ingest
        if info.use_tmpfs:
            # Copy new files out of container to temp files on host
            host_files = []
            for rel in new_rel_paths:
                container_abs = f"/session/{rel}"
                host_tmp = self._copy_from_container(container, container_abs, Path(tempfile.gettempdir()))
                host_files.append(host_tmp)
        else:
            host_files = [(info.session_dir / rel).resolve() for rel in new_rel_paths]

        # --- Ingest into the local artifact store (dedup, metadata, delete staging files).
        descriptors = ingest_files(
            new_host_files=host_files,
            session_id=session_key,   # reuse your session_key
            run_id=None,              # pass a real run_id if you have it
            tool_call_id=None,        # optional; pass one if you have it
        )

        # Enrich and return the REPL response.
        # Keep legacy keys for one release if you want backward compatibility.
        result["artifacts"] = descriptors          # ✅ new, stable contract
        # In tmpfs mode, there is no persistent host session dir to return
        result["session_dir"] = "" if info.use_tmpfs else str(info.session_dir)

        return result

    def stop(self, session_key: str) -> None:
        """
        Stop and remove the container for the given session_key and drop it from the
        in-memory registry. Idempotent: no error if the session is unknown.

        Tmpfs mode:
            All /session contents are lost when the container is removed (expected).
        Bind-mount mode:
            The host directory ./sessions/<sid> is left intact.
        """
        info = self.sessions.pop(session_key, None)
        if not info:
            return
        try:
            self.client.containers.get(info.container_id).remove(force=True)
        except Exception:
            # Best-effort cleanup; if Docker already removed it, we're fine.
            pass
