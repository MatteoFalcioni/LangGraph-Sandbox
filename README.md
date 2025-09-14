# Docker Sandbox Agent – Artifact Store Edition

This project provides a **Docker‑based sandbox** for executing Python code inside a LangGraph agentic system. It replaces services like E2B by running containers that isolate execution, enforce resource limits, and allow safe interaction with datasets.

The sandbox keeps Python state across tool calls and persists produced files in a **database‑backed artifact store**. Artifacts are deduplicated, assigned stable IDs, and can be downloaded or read later without exposing raw filesystem paths.

---

## Execution Mode

* **Session‑pinned containers**: one container per conversation (session).

  * Variables and imports live in RAM.
  * `/session` can be backed by either **tmpfs (RAM)** or a **bind mount** on the host (`./sessions/<sid>`).
  * With tmpfs, all data lives in memory and is discarded on container removal.
  * With bind mount, a host folder persists session state for local inspection.

---

## Storage & Dataset Modes

Two independent knobs define runtime behavior:

* **SessionStorage**: `BIND` (disk) vs `TMPFS` (RAM)
* **DatasetAccess**: `NONE` (no datasets) vs `LOCAL_RO` (host datasets at `/data`) vs `API_TMPFS` (datasets staged into `/session/data`)

### The Six Modes

| ID    | SessionStorage | DatasetAccess  | Description                                                                 | When to use                                                    |
| ----- | -------------- | -------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| **TMPFS_NONE** | **TMPFS**      | **NONE**       | Simple sandbox in RAM, no datasets                                         | General code execution, algorithms, lightweight demos          |
| **BIND_NONE** | **BIND**       | **NONE**       | Simple sandbox on disk, no datasets                                        | Persistent code execution, debugging without data              |
| **TMPFS_LOCAL** | **TMPFS**      | **LOCAL\_RO**  | Session in RAM, datasets from host RO at `/data`                            | Big/static datasets + fast ephemeral scratch; immutable inputs |
| **BIND_LOCAL** | **BIND**       | **LOCAL\_RO**  | Session on disk (`./sessions/<sid>`), datasets mounted RO at `/data`        | Super local dev, debugging, persistent session files           |
| **TMPFS_API** | **TMPFS**      | **API\_TMPFS** | Fully ephemeral: datasets staged into `/session/data` (RAM), session in RAM | Lightweight, multi‑tenant, API‑fed demos (default)            |
| **BIND_API** | **BIND**       | **API\_TMPFS** | Datasets staged into `/session/data`, session on disk                       | Persistent session folder but API‑fetched datasets (rare)      |

### Recommended Defaults

* **Simple code execution:** **TMPFS_NONE** - Perfect for general-purpose coding without datasets
* **Production / multi‑tenant demos:** **TMPFS_API** - If datasets are huge & stable, prefer **TMPFS_LOCAL**
* **Local dev/debug:** **BIND_LOCAL** - For persistent development with local datasets

---

## Datasets

* **NONE:** No datasets - simple code execution environment. Perfect for general-purpose coding, algorithms, and demos without data dependencies.
* **LOCAL\_RO:** Mount a host datasets directory read‑only at `/data`. Good for large/static inputs.
* **API\_TMPFS:** Fetch datasets on demand into `/session/data/<id>.parquet`. Cleanest for ephemeral runs.

### Dataset staging flow (API\_TMPFS)

1. The agent calls the **download tool** with `ds_id`.
2. `src/datasets/staging.py::stage_dataset_into_sandbox(...)` decides how to stage:

   * **TMPFS** → pushes bytes into the running container at `/session/data/<id>.parquet`.
   * **BIND**  → writes bytes on host at `./sessions/<sid>/data/<id>.parquet` (bind‑mounted into the container).
3. The host cache list `./sessions/<sid>/cache_datasets.txt` is updated with `ds_id` (idempotent, no pre‑exec sync at this stage by design).

> **Fetcher is FAKE for now. Replace it in production.**
> `src/datasets/fetcher.py` currently returns placeholder bytes. Swap it with a function that calls your real API and returns raw **Parquet bytes**:
>
> ```python
> # src/datasets/fetcher.py
> def fetch_dataset(ds_id: str) -> bytes:
>     """Return the Parquet file content for `ds_id` as bytes (raise on failure)."""
>     ...
> ```
>
> You can also inject a custom fetcher via the `fetch_fn` argument of `stage_dataset_into_sandbox(...)` (useful for testing or multiple backends).

---

## Artifacts

* User code writes files under `/session/artifacts/`.
* After each execution:

  1. Sandbox diffs the artifact folder (before vs after run).
  2. New files are copied out of the container (TMPFS) or read from host (BIND).
  3. Files are ingested into the artifact store:

     * Saved in `blobstore/` under SHA‑256.
     * Metadata logged in `artifacts.db`.
     * Deduplication handled automatically.
     * Removed from `/session/artifacts/` after ingestion.
  4. Descriptors returned with `id`, `name`, `size`, `mime`, `sha256`, `created_at`, `url`.

---

## Capabilities

* ✅ **Resource isolation**: CPU, memory, timeout limits
* ✅ **Session state persistence**: RAM (TMPFS) or disk (BIND)
* ✅ **Multiple dataset modes**: NONE (no datasets), LOCAL_RO (read-only mount), API_TMPFS (on-demand staging)
* ✅ **Artifact ingestion pipeline**: deduplication and DB-backed metadata
* ✅ **Download API**: signed URLs for artifact access
* ✅ **Artifact reader helpers**: reload artifacts by ID
* ✅ **Simple mode**: NONE mode for general-purpose code execution without datasets

---

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
   cd LangGraph-Sandbox
   ```

2. Build the sandbox image (root `Dockerfile`):

   ```bash
   docker build -t py-sandbox:latest -f Dockerfile .
   ```

3. Install Python dependencies (host):

   ```bash
   pip install -r requirements.txt
   ```

   Required: `docker`, `httpx`, `langgraph`, `langchain-core`, `pydantic` (plus whatever you bake into the sandbox image, e.g. `pandas`, `matplotlib`).

---

## Environment configuration

The app reads its configuration from environment variables (no special file required). Defaults target **TMPFS_API**: `SESSION_STORAGE=TMPFS` + `DATASET_ACCESS=API_TMPFS`.

### example.env

```env
# example.env — rename to .env or pass with --env-file

# --- Core knobs ---
SESSION_STORAGE=TMPFS        # TMPFS | BIND
DATASET_ACCESS=API_TMPFS     # NONE | LOCAL_RO | API_TMPFS

# --- Host paths ---
SESSIONS_ROOT=./sessions
BLOBSTORE_DIR=./blobstore
ARTIFACTS_DB=./artifacts.db

# Required ONLY if DATASET_ACCESS=LOCAL_RO
# DATASETS_HOST_RO=./example_llm_data

# --- Docker / runtime ---
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=1024
```

### Quick Start Examples

**Simple code execution (no datasets):**
```env
DATASET_ACCESS=NONE
```

**Local development with datasets:**
```env
SESSION_STORAGE=BIND
DATASET_ACCESS=LOCAL_RO
DATASETS_HOST_RO=./example_llm_data
```

**Production API-fed demos:**
```env
SESSION_STORAGE=TMPFS
DATASET_ACCESS=API_TMPFS
```

### Variables

* `SESSION_STORAGE`: `TMPFS` (RAM, ephemeral) or `BIND` (host folder `./sessions/<sid>`).
* `DATASET_ACCESS`: `NONE` (no datasets), `LOCAL_RO` (mount host datasets at `/data`), or `API_TMPFS` (stage datasets into `/session/data`).
* `SESSIONS_ROOT`: host dir for sessions (BIND mode & logs). Default `./sessions`.
* `BLOBSTORE_DIR`: host blob store root. Default `./blobstore`.
* `ARTIFACTS_DB`: SQLite path for artifact metadata. Default `./artifacts.db`.
* `DATASETS_HOST_RO`: **required only** when `DATASET_ACCESS=LOCAL_RO` (e.g., `./example_llm_data`).
* `SANDBOX_IMAGE`: Docker image name/tag. Default `sandbox:latest`.
* `TMPFS_SIZE_MB`: tmpfs size for `/session` when using TMPFS. Default `1024`.

### Usage

* Shell: `export SESSION_STORAGE=TMPFS` … `python main.py`
* Docker: `docker run --env-file ./.env your-image`
* Compose: add `env_file: [.env]` or `environment:` entries.

> Tip: add `.env` / `docker.env` to `.gitignore` if they may contain machine‑specific paths or secrets.

---

## NONE Mode - Simple Code Execution

The **NONE** dataset mode provides a clean, simple code execution environment without any dataset functionality. This is perfect for:

* **General-purpose coding** and algorithm development
* **Educational demos** that don't require data
* **Lightweight experimentation** and prototyping
* **Testing and debugging** without data dependencies

### Using NONE Mode

**Environment variable:**
```bash
export DATASET_ACCESS=NONE
python main.py
```

**Programmatic:**
```python
from src.config import Config, DatasetAccess, SessionStorage

cfg = Config(
    session_storage=SessionStorage.TMPFS,  # or BIND for persistence
    dataset_access=DatasetAccess.NONE
)
```

### What's Available in NONE Mode

* ✅ **Full Python environment** with all installed packages
* ✅ **Session persistence** - variables and imports persist across calls
* ✅ **Artifact creation** - save files to `/session/artifacts/`
* ✅ **Resource limits** - CPU, memory, and timeout controls
* ❌ **No datasets** - no `/data` mount or dataset syncing
* ❌ **No dataset tools** - no dataset selection or staging

### Example Usage

```python
# This code works in NONE mode
import math
import matplotlib.pyplot as plt
import numpy as np

# Create a plot
x = np.linspace(0, 2*math.pi, 100)
y = np.sin(x)

plt.figure(figsize=(10, 6))
plt.plot(x, y)
plt.savefig('/session/artifacts/sine_wave.png')
print("Plot saved!")

# Variables persist across calls
result = sum(math.sqrt(i) for i in range(1, 101))
print(f"Sum: {result:.2f}")
```

---

## Usage

Run your LangGraph app:

```bash
python main.py
```

The agent can now invoke the code execution tool.

### Example inside the sandbox

```python
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# RAM state persists across calls in session‑pinned mode
x = np.linspace(-2, 2, 100)
y = np.sin(x)

# Write an artifact (plot)
Path("/session/artifacts").mkdir(parents=True, exist_ok=True)
plt.plot(x, y)
plt.savefig("/session/artifacts/sin.png")
print("Plot saved to /session/artifacts/sin.png")
```

After execution, the file is ingested into the artifact store. The tool response includes a descriptor with an `id` for downloading or re‑loading the file.

---

## Repository layout & dataset fetching

```text
src/
  artifacts/                 # artifact store (blob + DB bindings)
  datasets/
    cache.py                 # host-side cache list: ./sessions/<sid>/cache_datasets.txt
    fetcher.py               # **FAKE** fetcher → replace with real API returning bytes
    staging.py               # mode-aware staging into the sandbox
  sandbox/
    io.py                    # push bytes into container (/session/...)
    repl_server.py           # in-container REPL
    session_manager.py       # session lifecycle (TMPFS/BIND, artifacts, etc.)
  config.py                  # env-driven config (SESSION_STORAGE, DATASET_ACCESS, ...)

langgraph_app/
  code_exec_tool.py          # LangGraph tool that calls the session manager
  make_graph.py              # graph assembly
  prompt.py                  # system prompts

sessions/                    # per-session folders (BIND mode & logs)
blobstore/                   # deduped artifact blobs
artifacts.db                 # artifact metadata
```

---

## Testing

We ship unit tests for config, I/O helpers, dataset cache, staging, and an end‑to‑end TMPFS + API\_TMPFS integration test with fakes.

```bash
pytest -q
```

---

## Quick Reference

### Mode Selection Guide

| Use Case | Recommended Mode | Environment Variables |
|----------|------------------|----------------------|
| **Simple coding, algorithms, demos** | `TMPFS_NONE` | `DATASET_ACCESS=NONE` |
| **Local development with datasets** | `BIND_LOCAL` | `SESSION_STORAGE=BIND` + `DATASET_ACCESS=LOCAL_RO` |
| **Production API-fed demos** | `TMPFS_API` | `DATASET_ACCESS=API_TMPFS` (default) |
| **Persistent coding without data** | `BIND_NONE` | `SESSION_STORAGE=BIND` + `DATASET_ACCESS=NONE` |

### Common Commands

```bash
# Simple code execution (no datasets)
DATASET_ACCESS=NONE python main.py

# Local development with datasets
SESSION_STORAGE=BIND DATASET_ACCESS=LOCAL_RO DATASETS_HOST_RO=./example_llm_data python main.py

# Production mode (default)
python main.py
```

---

## Next steps

* Add quotas and retention policies (per‑session max size, automatic cleanup).
* Swap SQLite/blobstore to Postgres + S3/MinIO for scalability.
* Extend the fetcher to expose integrity/metadata (e.g., return `(bytes, sha256, version)`), then add a host cache by hash for cross‑session reuse.
* Optional pre‑exec sync for deterministic recovery after tmpfs container restarts.
