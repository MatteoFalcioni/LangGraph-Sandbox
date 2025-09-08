# sandbox_runner.py
# sandbox_runner.py
import io, os, json, shutil, tempfile, uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
import docker

class DockerSandboxError(Exception):
    pass

def run_python_in_docker(
    code: str,
    *,
    image: str = "py-sandbox:latest",
    files: Optional[Dict[str, bytes]] = None,
    timeout_s: int = 20,
    mem_limit: str = "512m",
    nano_cpus: int = 1_000_000_000,
    extra_ro_mounts: Optional[Dict[str, str]] = None,   # {host_abs: "/data"}
    persist_root: Optional[str] = "outputs",            # host folder for promoted artifacts
    session_id: str | None = None, 
    session_root: str = "sessions",
) -> Dict[str, Any]:
    """
    Execute Python code inside a throwaway Docker container.

    Behavior:
      - Creates a per-run temp directory (mounted at /work).
      - Writes the given `code` to /work/run.py and executes it.
      - Optional: mounts host folders read-only at container paths
        (via `extra_ro_mounts={host_path: "/mountpoint"}`).
      - Optional: if `session_id` is provided, also mounts a persistent
        host folder at /session (sessions/<session_id>/). This lets multiple
        tool calls in the same conversation share files across runs.
      - Artifacts written to /work/artifacts are promoted to
        persist_root/<run_id>/ on the host, and a container→host path map
        is returned.

    Args:
      code (str): Python source code to execute.
      image (str): Docker image to run. Defaults to "py-sandbox:latest".
      files (dict[str, bytes]): Extra files to inject into /work.
      timeout_s (int): Max run time (seconds) before killing container.
      mem_limit (str): Memory limit, e.g. "512m".
      nano_cpus (int): CPU quota (1e9 = ~1 CPU).
      extra_ro_mounts (dict): Additional read-only host mounts.
      persist_root (str|None): Host folder for promoted artifacts.
      session_id (str|None): If set, create/use sessions/<session_id> as /session.
      session_root (str): Root for persistent sessions.

    Returns:
      dict with keys:
        - stdout (str): Captured stdout stream.
        - stderr (str): Captured stderr stream.
        - exit_code (int): Container exit code.
        - workdir (str): Host temp run directory.
        - persist_dir (str|None): Path where artifacts were copied.
        - artifact_map (list): [{container: str, host: str}] for each artifact.
        - run_id (str): Unique ID for this run.
    """

    client = docker.from_env()
    run_dir = Path(tempfile.mkdtemp(prefix="sandbox_run_"))

    try:
        # 1) write code and optional files
        (run_dir / "run.py").write_text(code, encoding="utf-8")
        if files:
            for rel, content in files.items():
                p = run_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
        (run_dir / "artifacts").mkdir(exist_ok=True)

        # 2) compose volumes
        volumes = { str(run_dir): {"bind": "/work", "mode": "rw"} }
        # Add read-only mounts
        if extra_ro_mounts:
            for host_p, ctr_p in extra_ro_mounts.items():
                if not os.path.exists(host_p):
                    raise DockerSandboxError(f"Mount source does not exist: {host_p} -> {ctr_p}")
                if not any(Path(host_p).rglob("*")):
                    print(f"[warn] Host mount is empty: {host_p}")
                volumes[host_p] = {"bind": ctr_p, "mode": "ro"}

        # persistent RW session dir (shared across calls)
        if session_id:
            sess_host = Path(session_root) / session_id
            sess_host.mkdir(parents=True, exist_ok=True)
            volumes[str(sess_host.resolve())] = {"bind": "/session", "mode": "rw"}
            
        # (3) create the container and run code
        container = client.containers.create(
            image=image,
            command=["python", "/work/run.py"],
            working_dir="/work",
            user="1000:1000",
            network_disabled=True,
            mem_limit=mem_limit,
            nano_cpus=nano_cpus,
            pids_limit=128,
            volumes=volumes,
        )

        try:
            container.start()
            # Wait with timeout
            result = container.wait(timeout=timeout_s)
            exit_code = result.get("StatusCode", 137)
        except docker.errors.APIError as e:
            container.kill()
            exit_code = 137
            raise DockerSandboxError(f"Timeout or API error: {e}") from e
        finally:
            # Collect logs regardless
            logs_out = container.logs(stdout=True, stderr=False)
            logs_err = container.logs(stdout=False, stderr=True)
            container.remove(force=True)

        stdout = logs_out.decode("utf-8", errors="replace")
        stderr = logs_err.decode("utf-8", errors="replace")

        # 4) promote artifacts → outputs/<run_id>/
        run_id = uuid.uuid4().hex[:8]
        artifacts_src = run_dir / "artifacts"
        persist_dir = None
        artifact_map: List[Dict[str, str]] = []

        if persist_root is not None:
            persist_dir = Path(persist_root) / run_id
            persist_dir.mkdir(parents=True, exist_ok=True)

            if artifacts_src.exists():
                for f in artifacts_src.rglob("*"):
                    if not f.is_file():
                        continue
                    rel = f.relative_to(artifacts_src)
                    dest = persist_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)

                    # container path is what the code used inside Docker:
                    ctr_path = f"/work/artifacts/{rel.as_posix()}"
                    artifact_map.append({"container": ctr_path, "host": str(dest)})

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "workdir": str(run_dir),
            "persist_dir": str(persist_dir) if persist_dir else None,
            "artifact_map": artifact_map,
            "run_id": run_id,
        }

    finally:
        # If you want automatic cleanup, uncomment this.
        # Be aware you’ll lose artifacts; instead, you can clean up later.
        # shutil.rmtree(run_dir, ignore_errors=True)
        pass
