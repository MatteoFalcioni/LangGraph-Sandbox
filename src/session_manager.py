# session_manager.py
import time
import uuid
from typing import Dict, Optional

import docker
import httpx

DEFAULT_IMAGE = "your-sandbox-image:latest"  # build/tag above
REPL_PORT = "9000/tcp"
IDLE_TIMEOUT_SECS = 45 * 60  # 45 minutes, tune as needed

class SessionInfo:
    def __init__(self, container_id: str, host_port: int):
        self.container_id = container_id
        self.host_port = host_port
        self.last_used = time.time()

class SessionManager:
    def __init__(self, image: str = DEFAULT_IMAGE):
        self.client = docker.from_env()
        self.image = image
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

    def start(self, user_id: Optional[str] = None) -> str:
        """Start a long-lived sandbox for this session."""
        self._sweep_idle()
        session_id = f"{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"

        container = self.client.containers.run(
            self.image,
            detach=True,
            mem_limit="8g",                # set sensible caps
            nano_cpus=2_000_000_000,       # ~2 CPUs
            ports={"9000/tcp": None},      # map to random host port
            # volumes={"/absolute/host/data": {"bind": "/data", "mode": "ro"}},
            # network_disabled=True,       # tighten later if you can
            name=f"sbox-{session_id}",
        )
        container.reload()
        host_port = int(container.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])

        # Basic health check
        with httpx.Client(timeout=5.0) as http:
            for _ in range(30):
                try:
                    r = http.get(f"http://127.0.0.1:{host_port}/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    time.sleep(0.2)

        self.sessions[session_id] = SessionInfo(container.id, host_port)
        return session_id

    def exec(self, session_id: str, code: str, timeout: int = 30) -> dict:
        """Execute code inside the existing session; state persists."""
        self._sweep_idle()
        info = self.sessions.get(session_id)
        if not info:
            raise RuntimeError("Unknown or expired session_id.")

        info.last_used = time.time()
        with httpx.Client(timeout=timeout + 5) as http:
            r = http.post(
                f"http://127.0.0.1:{info.host_port}/exec",
                json={"code": code, "timeout": timeout},
            )
            r.raise_for_status()
            return r.json()

    def stop(self, session_id: str) -> None:
        """Stop and remove the session container."""
        info = self.sessions.pop(session_id, None)
        if not info:
            return
        try:
            self.client.containers.get(info.container_id).remove(force=True)
        except Exception:
            pass
