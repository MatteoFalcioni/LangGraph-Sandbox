# src/session_manager.py
import time
import uuid
from typing import Dict, Optional

import docker
import httpx
from pathlib import Path

REPL_PORT = "9000/tcp"
DEFAULT_IMAGE = "py-sandbox:latest"
IDLE_TIMEOUT_SECS = 45 * 60  # tune

class SessionInfo:
    def __init__(self, container_id: str, host_port: int, session_dir: Path):
        self.container_id = container_id
        self.host_port = host_port
        self.session_dir = session_dir
        self.last_used = time.time()

class SessionManager:
    """
    Manages one long-lived sandbox container per session.
    Keeps Python state in RAM via repl_server.py and mounts:
      - datasets RO at /data
      - a per-session RW dir at /session
    """
    def __init__(self, image: str = DEFAULT_IMAGE, datasets_path: Optional[Path] = None, session_root: Path = Path("sessions")):
        self.client = docker.from_env()
        self.image = image
        self.datasets_path = Path(datasets_path).resolve() if datasets_path else None
        self.session_root = Path(session_root).resolve()
        self.sessions: Dict[str, SessionInfo] = {}

    def _sweep_idle(self):
        now = time.time()
        for sid, info in list(self.sessions.items()):
            if now - info.last_used > IDLE_TIMEOUT_SECS:
                try:
                    self.client.containers.get(info.container_id).remove(force=True)
                except Exception:
                    pass
                self.sessions.pop(sid, None)

    def start(self, session_key: Optional[str] = None) -> str:
        """
        Start (or attach to) a container for this session_key.
        session_key: your conversation/thread/user id. If None, a random one is used.
        """
        self._sweep_idle()
        if session_key and session_key in self.sessions:
            return session_key

        sid = session_key or f"anon-{uuid.uuid4().hex[:8]}"
        sess_dir = self.session_root / sid
        sess_dir.mkdir(parents=True, exist_ok=True)

        name = f"sbox-{sid}"

        # If a container with that name already exists, reuse it.
        try:
            existing = self.client.containers.get(name)
            # Ensure it's running
            if existing.status not in ("running",):
                existing.start()
            existing.reload()
            host_port = int(existing.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])
            self.sessions[sid] = SessionInfo(existing.id, host_port, sess_dir)
            return sid
        except docker.errors.NotFound:
            pass  # create a new one

        volumes = {str(sess_dir): {"bind": "/session", "mode": "rw"}}
        if self.datasets_path and self.datasets_path.exists():
            volumes[str(self.datasets_path)] = {"bind": "/data", "mode": "ro"}

        container = self.client.containers.run(
            self.image,
            detach=True,
            mem_limit="8g",
            nano_cpus=2_000_000_000,  # ~2 CPUs
            ports={"9000/tcp": None},  # random host port
            volumes=volumes,
            name=name,
        )
        container.reload()
        host_port = int(container.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])

        # wait for /health
        with httpx.Client(timeout=5.0) as http:
            for _ in range(50):
                try:
                    r = http.get(f"http://127.0.0.1:{host_port}/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    time.sleep(0.1)

        self.sessions[sid] = SessionInfo(container.id, host_port, sess_dir)
        return sid
    
    def _list_artifact_files(self, session_dir: Path) -> set[str]:
        art = session_dir / "artifacts"
        if not art.exists():
            return set()
        return {
            str(p.relative_to(session_dir).as_posix())
            for p in art.rglob("*") if p.is_file()
        }

    def exec(self, session_key: str, code: str, timeout: int = 30) -> dict:
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown or expired session_key. Call start() first.")
        info.last_used = time.time()

        # Snapshot before
        before = self._list_artifact_files(info.session_dir)

        # Execute in the long-lived REPL
        with httpx.Client(timeout=timeout + 5) as http:
            r = http.post(
                f"http://127.0.0.1:{info.host_port}/exec",
                json={"code": code, "timeout": timeout},
            )
            r.raise_for_status()
            result = r.json()   # {ok, stdout, error?}

        # Snapshot after
        after = self._list_artifact_files(info.session_dir)
        new_rel_paths = sorted(after - before)

        # Build container/host map
        artifact_map = []
        for rel in new_rel_paths:
            host_path = (info.session_dir / rel).resolve()
            # Container path mirrors /session/...
            ctr_path = f"/session/{rel}"
            artifact_map.append({"container": ctr_path, "host": str(host_path)})

        # Return enriched result
        result["artifact_map"] = artifact_map
        result["session_dir"] = str(info.session_dir)
        return result

    def stop(self, session_key: str) -> None:
        info = self.sessions.pop(session_key, None)
        if not info:
            return
        try:
            self.client.containers.get(info.container_id).remove(force=True)
        except Exception:
            pass
