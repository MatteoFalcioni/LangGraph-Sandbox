# ---------------------------
# src/session_manager.py
# ---------------------------

import time
import uuid
from typing import Dict, Optional

import docker           # Host-side Docker SDK (controls containers)
import httpx            # Lightweight HTTP client to talk to the in-container REPL
from pathlib import Path

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
    Lightweight record for one live session/container:
    - container_id: the Docker container ID (so we can stop/remove it)
    - host_port: the host port mapped to the in-container REPL (listens on 9000)
    - session_dir: the host path for this session's bind mount (./sessions/<sid>)
    - last_used: unix timestamp to support idle eviction
    """
    def __init__(self, container_id: str, host_port: int, session_dir: Path):
        self.container_id = container_id
        self.host_port = host_port
        self.session_dir = session_dir
        self.last_used = time.time()


class SessionManager:
    """
    One manager object for all sessions. Responsibilities:
      - Start (or reattach to) a long-lived container per session_key.
      - Keep Python state in RAM via the in-container FastAPI REPL (repl_server.py).
      - Mount datasets read-only at /data (if provided).
      - Mount a per-session read-write dir at /session (./sessions/<sid> on host).
      - Execute code by POSTing to /exec on the REPL.
      - Detect new artifacts written under /session/artifacts and return their paths.
      - Clean up idle sessions opportunistically.
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        datasets_path: Optional[Path] = None,
        session_root: Path = Path("sessions"),
    ):
        # Create a Docker client bound to the host's Docker daemon.
        self.client = docker.from_env()
        self.image = image

        # Optional datasets root; mounted read-only at /data inside the container.
        self.datasets_path = Path(datasets_path).resolve() if datasets_path else None

        # Where we keep per-session folders on the host.
        # Each session will have: sessions/<sid>  (bind-mounted to /session)
        self.session_root = Path(session_root).resolve()

        # In-memory registry: session_key -> SessionInfo
        self.sessions: Dict[str, SessionInfo] = {}

    def _sweep_idle(self):
        """
        Opportunistic garbage collection for idle sessions.
        Called at the top of start() and exec() to keep the set tidy
        without a dedicated background thread.
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
        Start (or attach to) a container for this session_key.

        session_key:
          - Use your conversation/thread/user id so each user gets their own sandbox.
          - If None, we generate a random 'anon-<id>'.

        Behavior:
          1) Sweep idle sessions.
          2) If we already know this session, return quickly.
          3) Reuse an existing container named 'sbox-<sid>' if Docker still has it.
          4) Else, run a new container:
             - bind-mount ./sessions/<sid> -> /session (RW)
             - optional datasets_path -> /data (RO)
             - expose REPL on a random host port mapped from container 9000
          5) Probe /health until the REPL is ready.
          6) Register SessionInfo and return sid.
        """
        self._sweep_idle()

        # If we already have a live SessionInfo for this sid, just return it.
        if session_key and session_key in self.sessions:
            return session_key

        # Choose the session id.
        sid = session_key or f"anon-{uuid.uuid4().hex[:8]}"

        # Ensure the host session directory exists (so the bind mount has a target).
        sess_dir = self.session_root / sid
        sess_dir.mkdir(parents=True, exist_ok=True)

        # Stable container name so we can reattach if it survives our process.
        name = f"sbox-{sid}"

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

        # Build volume mapping:
        #   - ./sessions/<sid>  -> /session (RW)
        #   - datasets_path     -> /data (RO)  [optional]
        volumes = {str(sess_dir): {"bind": "/session", "mode": "rw"}}
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
        self.sessions[sid] = SessionInfo(container.id, host_port, sess_dir)
        return sid

    def _list_artifact_files(self, session_dir: Path) -> set[str]:
        """
        Return the set of artifact file paths (relative to session_dir)
        that currently exist under ./sessions/<sid>/artifacts/** on the host.

        Why relative? So we can build both:
          - container path:  /session/<relative>
          - host path:       session_dir / <relative>
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

    def exec(self, session_key: str, code: str, timeout: int = 30) -> dict:
        """
        Execute Python code inside the long-lived container for session_key.

        Steps:
          1) Validate session & update last_used (for idle eviction).
          2) Snapshot the set of artifact files before execution.
          3) POST the code to the REPL's /exec endpoint.
          4) Snapshot again after execution and diff to find newly created files.
          5) Ingest the new files into the artifact store (dedup + metadata).
          6) Return the REPL result enriched with artifacts (descriptors) and session_dir

        Returns dict like:
          {
            "ok": bool,
            "stdout": "...",
            "error": "...",            # present when ok == False
            "artifact_map": [...],     # only new files from this call
            "session_dir": "/abs/path/to/sessions/<sid>"
          }
        """
        info = self.sessions.get(session_key)
        if not info:
            # This is a programmer error in the caller: they must call start() once.
            raise RuntimeError("Unknown or expired session_key. Call start() first.")

        # Mark as used (keeps it alive).
        info.last_used = time.time()

        # --- Snapshot artifacts BEFORE execution.
        before = self._list_artifact_files(info.session_dir)

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
        after = self._list_artifact_files(info.session_dir)
        new_rel_paths = sorted(after - before)

        # --- Build a stable container/host mapping for the caller/UI.
        # --- Convert relative paths to absolute HOST paths for ingest.
        new_host_files = [(info.session_dir / rel).resolve() for rel in new_rel_paths]

        # --- Ingest into the local artifact store (dedup, metadata, delete staging files).
        descriptors = ingest_files(
            new_host_files=new_host_files,
            session_id=session_key,   # reuse your session_key
            run_id=None,              # pass a real run_id if you have it
            tool_call_id=None,        # optional; pass one if you have it
        )

        # Enrich and return the REPL response.
        # Keep legacy keys for one release if you want backward compatibility.
        result["artifacts"] = descriptors          # ✅ new, stable contract
        result["artifact_map"] = []                # optional: keep empty during transition
        result["session_dir"] = str(info.session_dir)
        return result

    def stop(self, session_key: str) -> None:
        """
        Stop and remove the container for session_key and drop it from the registry.
        No-op if the session doesn't exist (idempotent).
        """
        info = self.sessions.pop(session_key, None)
        if not info:
            return
        try:
            self.client.containers.get(info.container_id).remove(force=True)
        except Exception:
            # Best-effort cleanup; if Docker already removed it, we're fine.
            pass
