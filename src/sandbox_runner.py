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
) -> Dict[str, Any]:
    """
    Execute code in a throwaway container. Promote /work/artifacts to host
    persist_root/<run_id>/ and return a container→host artifact map.

    Returns:
      {
        "stdout": str,
        "exit_code": int,
        "workdir": str,                # host temp run dir
        "persist_dir": Optional[str],  # host promoted dir
        "artifact_map": List[{"container": str, "host": str}],
        "run_id": str,
      }
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
            logs = container.logs(stdout=True, stderr=True)
            container.remove(force=True)

        # Split logs (stdout/stderr are interleaved; we just return combined + raw files)
        stdout = logs.decode("utf-8", errors="replace")

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
