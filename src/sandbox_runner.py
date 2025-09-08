# sandbox_runner.py
import tempfile
from pathlib import Path
from typing import List
import docker 
import os

class DockerSandboxError(Exception):
    pass

def run_python_in_docker(
    code: str,
    *,
    image: str = "py-sandbox:latest",
    files: dict | None = None,
    timeout_s: int = 20,
    mem_limit: str = "512m",
    nano_cpus: int = 1_000_000_000,
    extra_ro_mounts: dict[str, str] | None = None,  # {host_path: "/container/path"}
) -> dict:
    """
    Execute `code` inside an ephemeral Docker container with a mounted /work dir.
    Returns: { stdout, stderr, exit_code, artifacts }
    """
    client = docker.from_env()

    # Per-run temp dir on host
    run_dir = Path(tempfile.mkdtemp(prefix="sandbox_run_"))
    try:
        # Write the user code
        (run_dir / "run.py").write_text(code, encoding="utf-8")

        # Optionally add input files (e.g., CSVs)
        if files:
            for relpath, content in files.items():
                out_path = run_dir / relpath
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(content)

        # Ensure artifacts dir exists (user code can write here)
        (run_dir / "artifacts").mkdir(exist_ok=True)

        volumes = {
        str(run_dir): {"bind": "/work", "mode": "rw"},
        }
        # Add read-only mounts
        if extra_ro_mounts:
            for host_p, ctr_p in extra_ro_mounts.items():
                volumes[host_p] = {"bind": ctr_p, "mode": "ro"}

        for host_p, ctr_p in (extra_ro_mounts or {}).items():
            if not os.path.exists(host_p):
                raise DockerSandboxError(f"Mount source does not exist: {host_p} -> {ctr_p}")
            if not any(Path(host_p).rglob("*")):
                print(f"[warn] Host mount is empty: {host_p}")

        # create the container
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

        # Gather artifacts
        artifacts: List[str] = []
        for p in (run_dir / "artifacts").rglob("*"):
            if p.is_file():
                artifacts.append(str(p))

        return {
            "stdout": stdout,
            "stderr": "",             # Keep simple; you could parse logs if you want
            "exit_code": exit_code,
            "artifacts": artifacts,
            "workdir": str(run_dir),
        }

    finally:
        # If you want automatic cleanup, uncomment this.
        # Be aware you’ll lose artifacts; instead, you can clean up later.
        # shutil.rmtree(run_dir, ignore_errors=True)
        pass
