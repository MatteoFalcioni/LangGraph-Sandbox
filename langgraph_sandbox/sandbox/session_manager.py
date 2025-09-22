# ---------------------------
# langgraph_sandbox/sandbox/session_manager.py
# ---------------------------

import time
import uuid
import os
import shlex
import json
import socket
from datetime import datetime
from typing import Dict, Optional, List

import docker            # Host-side Docker SDK (controls containers)
from docker import errors
import httpx             # Lightweight HTTP client to talk to the in-container REPL
from pathlib import Path

import io
import tarfile
import tempfile

try:
    # Try relative imports first (when used as a module)
    from ..artifacts.ingest import ingest_files
    from .container_utils import cleanup_sandbox_containers
except ImportError:
    # Fall back to absolute imports (when run directly)
    from artifacts.ingest import ingest_files
    from sandbox.container_utils import cleanup_sandbox_containers

from enum import Enum

class SessionStorage(str, Enum):
    TMPFS = "TMPFS"   # /session is RAM-backed inside the container
    BIND  = "BIND"    # /session is bind-mounted to ./sessions/<sid> on host

class DatasetAccess(str, Enum):
    NONE      = "NONE"        # no datasets - simple sandbox mode
    API = "API"   # datasets fetched via API into /data
    LOCAL_RO  = "LOCAL_RO"    # host datasets mounted read-only at /data
    HYBRID = "HYBRID"         # local datasets + API datasets, both in /data


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
        hybrid_local_path: Optional[Path] = None,
        session_root: Path = Path("sessions"),
        tmpfs_size: str = "1g",
        address_strategy: str = "container",
        compose_network: Optional[str] = None,
        host_gateway: str = "host.docker.internal",
    ):
        """
        Args:
            image: Docker image name for the sandbox.
            session_storage: Where /session is backed (TMPFS or BIND).
            dataset_access: How datasets are exposed (API, LOCAL_RO, or HYBRID).
            datasets_path: Required when dataset_access=LOCAL_RO; mounted at /data (RO).
            hybrid_local_path: Required when dataset_access=HYBRID; mounted at /data (RO).
            session_root: Base host dir for per-session folders when using BIND.
            tmpfs_size: Soft cap (e.g., "1g", "512m") for /session when using TMPFS.
            address_strategy: "container" for Docker network DNS, "host" for port mapping.
            compose_network: Docker network name for container strategy.
            host_gateway: Gateway hostname for host strategy (default: host.docker.internal).
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
            self.hybrid_local_path = None
        elif self.dataset_access == DatasetAccess.HYBRID:
            if not hybrid_local_path:
                raise ValueError("hybrid_local_path is required when dataset_access=HYBRID")
            self.hybrid_local_path = Path(hybrid_local_path).resolve()
            self.datasets_path = None
        else:
            # NONE or API -> Do not mount /data
            self.datasets_path = None
            self.hybrid_local_path = None

        self.session_root = Path(session_root).resolve()
        self.tmpfs_size = tmpfs_size
        
        # Network configuration
        self.address_strategy = address_strategy
        self.compose_network = compose_network
        self.host_gateway = host_gateway

        # In-memory registry: session_key -> SessionInfo
        self.sessions: Dict[str, SessionInfo] = {}

    def _get_repl_url(self, session_key: str) -> str:
        """
        Get the REPL URL for a session based on address strategy.
        
        Args:
            session_key: Session identifier
            
        Returns:
            Base URL for the REPL (e.g., "http://container-name:9000" or "http://host.docker.internal:12345")
        """
        info = self.sessions.get(session_key)
        if not info:
            raise RuntimeError("Unknown session_key. Call start() first.")
        
        if self.address_strategy == "container":
            # Use container name for DNS resolution
            container_name = f"sbox-{session_key}"
            return f"http://{container_name}:9000"
        else:
            # Use host gateway with mapped port
            # Auto-detect the right host gateway for the environment
            host_gateway = self._detect_host_gateway()
            return f"http://{host_gateway}:{info.host_port}"

    def _detect_host_gateway(self) -> str:
        """
        Detect the appropriate host gateway based on the environment.
        
        Returns:
            The host gateway to use for connecting to containers.
        """
        # If explicitly configured, use that
        if self.host_gateway != "host.docker.internal":
            return self.host_gateway
        
        # Auto-detect environment
        import platform
        import os
        
        # Check if we're in WSL2
        if "microsoft" in platform.uname().release.lower():
            return "localhost"
        
        # Check if we're in a container (Docker-in-Docker)
        if os.path.exists("/.dockerenv"):
            return "host.docker.internal"
        
        # Check if host.docker.internal is reachable
        try:
            socket.gethostbyname("host.docker.internal")
            return "host.docker.internal"
        except socket.gaierror:
            # Fallback to localhost
            return "localhost"
        
        # Default fallback
        return "localhost"

    def _write_session_log(self, session_key: str, log_entry: dict) -> None:
        """
        Write a log entry to the session's log file (BIND mode only).
        
        Args:
            session_key: Session identifier
            log_entry: Dictionary containing log data (timestamp, code, result, etc.)
        """
        if self.session_storage != SessionStorage.BIND:
            return
            
        info = self.sessions.get(session_key)
        if not info or not info.session_dir:
            return
            
        log_file = info.session_dir / "session.log"
        
        # Add timestamp if not present
        if "timestamp" not in log_entry:
            log_entry["timestamp"] = datetime.now().isoformat()
            
        # Append to log file
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

    def _write_session_metadata(self, session_key: str, metadata: dict) -> None:
        """
        Write session metadata to a JSON file (BIND mode only).
        
        Args:
            session_key: Session identifier
            metadata: Dictionary containing session metadata
        """
        if self.session_storage != SessionStorage.BIND:
            return
            
        info = self.sessions.get(session_key)
        if not info or not info.session_dir:
            return
            
        metadata_file = info.session_dir / "session_metadata.json"
        
        # Update existing metadata or create new
        if metadata_file.exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    existing_metadata = json.load(f)
                existing_metadata.update(metadata)
                metadata = existing_metadata
            except (json.JSONDecodeError, FileNotFoundError):
                pass  # Start fresh if file is corrupted
                
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

    def _get_execution_count(self, session_key: str) -> int:
        """
        Get the current execution count for a session (BIND mode only).
        
        Args:
            session_key: Session identifier
            
        Returns:
            Current execution count, or 0 if not available
        """
        if self.session_storage != SessionStorage.BIND:
            return 0
            
        info = self.sessions.get(session_key)
        if not info or not info.session_dir:
            return 0
            
        metadata_file = info.session_dir / "session_metadata.json"
        if not metadata_file.exists():
            return 0
            
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            return metadata.get("execution_count", 0)
        except (json.JSONDecodeError, FileNotFoundError):
            return 0

    def _save_python_state(self, session_key: str) -> None:
        """
        Save current Python state (variables and imports) to session directory (BIND mode only).
        
        Args:
            session_key: Session identifier
        """
        if self.session_storage != SessionStorage.BIND:
            return
            
        info = self.sessions.get(session_key)
        if not info or not info.session_dir:
            return
            
        # Code to extract Python state
        state_code = """
import sys
import json
from datetime import datetime

# Get current variables (excluding builtins and modules)
current_vars = {}
for name, value in globals().items():
    if not name.startswith('_') and name not in ['sys', 'json', 'datetime']:
        try:
            # Try to serialize the value
            json.dumps(value, default=str)
            current_vars[name] = {
                'type': type(value).__name__,
                'value': str(value)[:1000]  # Truncate long values
            }
        except:
            current_vars[name] = {
                'type': type(value).__name__,
                'value': '<non-serializable>'
            }

# Get imported modules
imported_modules = list(sys.modules.keys())
imported_modules = [m for m in imported_modules if not m.startswith('_')]

state = {
    'timestamp': datetime.now().isoformat(),
    'variables': current_vars,
    'imported_modules': imported_modules
}

# Write to file
with open('/session/python_state.json', 'w') as f:
    json.dump(state, f, indent=2)
"""
        
        try:
            with httpx.Client(timeout=10) as http:
                base_url = self._get_repl_url(session_key)
                r = http.post(
                    f"{base_url}/exec",
                    json={"code": state_code, "timeout": 10},
                )
                if r.status_code == 200:
                    # Copy the state file to host
                    state_file = info.session_dir / "python_state.json"
                    if (info.session_dir / "python_state.json").exists():
                        # File already copied by bind mount
                        pass
        except Exception:
            # Don't fail if state saving fails
            pass

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
            
            # Get port info based on strategy
            if self.address_strategy == "container":
                host_port = 9000  # Container internal port
            else:
                host_port = int(existing.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])
                
            # Ensure session_dir is set correctly based on current storage mode
            if self.session_storage == SessionStorage.BIND:
                sess_dir = (self.session_root / sid).resolve()
                sess_dir.mkdir(parents=True, exist_ok=True)
            self.sessions[sid] = SessionInfo(existing.id or "", host_port, sess_dir, self.session_storage)
            return sid
        except errors.NotFound:
            pass  # create a new container
        except Exception as e:
            # If there's any other issue with the existing container, remove it and create a new one
            try:
                existing = self.client.containers.get(name)
                existing.stop()
                existing.remove()
            except:
                pass  # Ignore errors when removing problematic container

        # Build mounts
        volumes: Dict[str, Dict[str, str]] = {}
        tmpfs: Dict[str, str] = {}

        # /session mount
        if self.session_storage == SessionStorage.TMPFS:
            # Convert MB to Docker size format
            if isinstance(self.tmpfs_size, int):
                size_opt = f"{self.tmpfs_size}m"   # MB → Docker option
            else:
                size_opt = str(self.tmpfs_size)
            tmpfs["/session"] = f"rw,size={size_opt},mode=1777"
        else:
            volumes[str(sess_dir)] = {"bind": "/session", "mode": "rw"}

        # /data (datasets) mount based on dataset access mode
        if self.dataset_access == DatasetAccess.LOCAL_RO:
            volumes[str(self.datasets_path)] = {"bind": "/data", "mode": "ro"}
        elif self.dataset_access == DatasetAccess.HYBRID:
            volumes[str(self.hybrid_local_path)] = {"bind": "/data", "mode": "ro"}
        # NONE and API modes don't mount /data (API datasets are staged to /data)

        # Configure networking based on strategy
        if self.address_strategy == "container":
            # Container strategy: no port mapping, use Docker network
            ports = {}  # No port mapping
            network = self.compose_network
        else:
            # Host strategy: port mapping for external access
            ports = {"9000/tcp": None}  # random host port for REPL
            network = None

        # Ensure no container with this name exists before creating
        try:
            existing_container = self.client.containers.get(name)
            # If we get here, a container with this name exists
            existing_container.stop()
            existing_container.remove()
        except errors.NotFound:
            # No existing container, which is what we want
            pass
        except Exception as e:
            # If there's any issue removing the existing container, log it but continue
            print(f"Warning: Could not remove existing container {name}: {e}")

        # Run container
        container = self.client.containers.run(
            self.image,
            detach=True,
            mem_limit="8g",                 # tune for your infra/tenancy
            nano_cpus=2_000_000_000,       # ~2 vCPU
            ports=ports,
            volumes=volumes,
            tmpfs=tmpfs or None,
            name=name,
            network=network,
        )
        container.reload()
        
        # Get port info based on strategy
        if self.address_strategy == "container":
            host_port = 9000  # Container internal port
        else:
            host_port = int(container.attrs["NetworkSettings"]["Ports"][REPL_PORT][0]["HostPort"])

        # Wait for /health quickly (best-effort)
        # Register session first so we can use _get_repl_url
        self.sessions[sid] = SessionInfo(container.id or "", host_port, sess_dir, self.session_storage)
        
        with httpx.Client(timeout=5.0) as http:
            for _ in range(50):  # ~5s worst case
                try:
                    base_url = self._get_repl_url(sid)
                    r = http.get(f"{base_url}/health")
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
        
        # Write initial session metadata (BIND mode only)
        if self.session_storage == SessionStorage.BIND:
            initial_metadata = {
                "session_id": sid,
                "created_at": datetime.now().isoformat(),
                "container_id": container.id,
                "host_port": host_port,
                "session_storage": self.session_storage.value,
                "dataset_access": self.dataset_access.value,
                "image": self.image,
                "execution_count": 0,
                "last_used": datetime.now().isoformat()
            }
            self._write_session_metadata(sid, initial_metadata)
            
            # Log session start
            self._write_session_log(sid, {
                "event": "session_started",
                "container_id": container.id,
                "host_port": host_port
            })
        
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
                fsrc = tar.extractfile(member)
                if fsrc is None:
                    raise RuntimeError(f"Could not extract file '{want_name}' from archive")
                with fsrc, open(out_path, "wb") as fdst:
                    fdst.write(fsrc.read())
            return out_path

        # a few quick retries to smooth out FS propagation on tmpfs
        for attempt in range(5):
            # 1) direct get_archive(file)
            try:
                bits, _ = container.get_archive(container_path)
                data = b"".join(bits)
                return _extract_one(data, filename, dst_dir / filename)
            except errors.NotFound:
                pass
            except Exception:
                if attempt == 4:
                    raise

            # 2) get_archive(parent) and extract filename
            try:
                bits, _ = container.get_archive(parent)
                data = b"".join(bits)
                return _extract_one(data, filename, dst_dir / filename)
            except errors.NotFound:
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

    def _cleanup_session_memory(self, session_key: str) -> None:
        """
        Clean up memory in the sandbox to prevent 'No space left on device' errors.
        This method runs after each code execution and focuses on the main memory hogs:
        - Matplotlib figures (biggest memory consumer)
        - Python garbage collection
        - Old artifacts (after they're ingested)
        
        Does NOT clean /tmp or /var/tmp to preserve user files.
        """
        info = self.sessions.get(session_key)
        if not info:
            return

        container = self.client.containers.get(info.container_id)
        
        # Targeted cleanup code - only clean what causes space issues
        cleanup_code = """
import gc
from pathlib import Path

# Clear Python garbage collection
gc.collect()

# Clear matplotlib figures (main memory hog)
try:
    import matplotlib
    matplotlib.pyplot.close('all')
    matplotlib.pyplot.clf()
    matplotlib.pyplot.cla()
    # Also clear any cached figures
    if hasattr(matplotlib.pyplot, 'get_fignums'):
        for fig_num in matplotlib.pyplot.get_fignums():
            matplotlib.pyplot.close(fig_num)
except:
    pass

# Clear old artifacts (after they're ingested, preserve structure)
session_artifacts = Path('/session/artifacts')
if session_artifacts.exists():
    for item in session_artifacts.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                # Only remove empty directories, preserve structure
                try:
                    item.rmdir()
                except OSError:
                    # Directory not empty, leave it
                    pass
        except:
            pass
"""

        # Execute cleanup code in the container
        try:
            with httpx.Client(timeout=10) as http:
                base_url = self._get_repl_url(session_key)
                r = http.post(
                    f"{base_url}/exec",
                    json={"code": cleanup_code, "timeout": 10},
                )
                r.raise_for_status()
        except Exception:
            # Don't fail the main execution if cleanup fails
            pass

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
            before = self._list_artifact_files_host(info.session_dir) if info.session_dir else set()

        # Execute via REPL
        with httpx.Client(timeout=timeout + 5) as http:
            base_url = self._get_repl_url(session_key)
            r = http.post(
                f"{base_url}/exec",
                json={"code": code, "timeout": timeout},
            )
            r.raise_for_status()
            result = r.json()  # {ok, stdout, error?}
            
        # Log execution (BIND mode only)
        if self.session_storage == SessionStorage.BIND:
            execution_log = {
                "event": "code_execution",
                "code": code,
                "success": result.get("ok", False),
                "stdout": result.get("stdout", ""),
                "error": result.get("error", ""),
                "timeout": timeout
            }
            self._write_session_log(session_key, execution_log)
            
            # Update execution count in metadata
            self._write_session_metadata(session_key, {
                "execution_count": self._get_execution_count(session_key) + 1,
                "last_used": datetime.now().isoformat()
            })

        # Snapshot AFTER & diff
        if info.session_storage == SessionStorage.TMPFS:
            after = self._list_artifact_files_container(container)
        else:
            after = self._list_artifact_files_host(info.session_dir) if info.session_dir else set()
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
        
        # Log artifact creation (BIND mode only)
        if self.session_storage == SessionStorage.BIND and descriptors:
            artifact_log = {
                "event": "artifacts_created",
                "artifact_count": len(descriptors),
                "artifacts": [
                    {
                        "id": desc.get("id"),
                        "filename": desc.get("name"),
                        "content_type": desc.get("mime"),
                        "size_bytes": desc.get("size")
                    }
                    for desc in descriptors
                ]
            }
            self._write_session_log(session_key, artifact_log)

        # Clean up memory after artifacts are processed to prevent space issues
        self._cleanup_session_memory(session_key)
        
        # Save Python state for debugging (BIND mode only)
        if self.session_storage == SessionStorage.BIND:
            self._save_python_state(session_key)

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
            
        # Log session stop (BIND mode only)
        if self.session_storage == SessionStorage.BIND:
            self._write_session_log(session_key, {
                "event": "session_stopped",
                "container_id": info.container_id
            })
            
            # Update final metadata
            self._write_session_metadata(session_key, {
                "stopped_at": datetime.now().isoformat(),
                "final_execution_count": self._get_execution_count(session_key)
            })
            
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

    def export_file(self, session_key: str, container_path: str) -> dict:
        """
        Export a file from the container's /data/ directory to the host.
        
        Parameters:
            session_key: Session identifier
            container_path: Path to file inside container (must start with /data/)
            
        Returns:
            dict with keys:
              - success: bool
              - host_path: str (path on host filesystem)
              - download_url: str (URL to access the file)
              - error: str (present when success == False)
        """
        # Validate session exists
        if session_key not in self.sessions:
            return {
                "success": False,
                "error": f"Session '{session_key}' not found"
            }
        
        info = self.sessions[session_key]
        
        # Validate container path
        if not container_path.startswith("/data/"):
            return {
                "success": False,
                "error": "Path must be in /data/ directory"
            }
        
        # Check if file exists in container
        try:
            container = self.container_for(session_key)
            rc, _ = container.exec_run(
                ["/bin/sh", "-c", f"test -f {shlex.quote(container_path)}"]
            )
            if rc != 0:
                return {
                    "success": False,
                    "error": f"File '{container_path}' does not exist in container"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to check file existence: {str(e)}"
            }
        
        # Generate host path with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = Path(container_path).name
        host_filename = f"{timestamp}_{filename}"
        host_dir = Path("./exports/modified_datasets")
        host_dir.mkdir(parents=True, exist_ok=True)
        host_path = host_dir / host_filename
        
        try:
            # Extract file from container using robust method
            host_file = self._copy_from_container(container, container_path, host_dir)
            
            # Move to final location with timestamp
            host_file.rename(host_path)
            
            # Create a temporary copy for artifact ingestion (since ingest_files deletes the original)
            import tempfile
            import shutil
            temp_copy = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
            shutil.copy2(host_path, temp_copy.name)
            temp_copy.close()
            
            # Ingest the temporary copy into the artifact system to get proper download URL
            descriptors = ingest_files(
                new_host_files=[Path(temp_copy.name)],
                session_id=session_key,
                run_id=None,
                tool_call_id=None,
            )
            
            # Clean up the temporary file (ingest_files already deleted it, but just to be safe)
            try:
                Path(temp_copy.name).unlink(missing_ok=True)
            except:
                pass
            
            # Get the download URL from the artifact descriptor
            download_url = f"./exports/modified_datasets/{host_filename}"  # fallback
            if descriptors and len(descriptors) > 0:
                artifact_desc = descriptors[0]
                artifact_url = artifact_desc.get("url")
                if artifact_url:
                    download_url = artifact_url
            
            return {
                "success": True,
                "host_path": str(host_path.absolute()),
                "download_url": download_url
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to export file: {str(e)}"
            }
