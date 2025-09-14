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

### Artifact Environment Variables

The artifact system requires these environment variables for secure download URLs:

* `ARTIFACTS_TOKEN_SECRET`: Long random string for signing download tokens (required)
* `ARTIFACTS_PUBLIC_BASE_URL`: Base URL for artifact downloads (required)
* `ARTIFACTS_TOKEN_TTL_SECONDS`: Token expiration time in seconds (optional, default: 600)

```env
# Artifact security
ARTIFACTS_TOKEN_SECRET=sk-tk123456789098765432112345678900000001111
ARTIFACTS_PUBLIC_BASE_URL=http://localhost:8000
ARTIFACTS_TOKEN_TTL_SECONDS=600
```

---

## Capabilities

* ✅ **Resource isolation**: CPU, memory, timeout limits
* ✅ **Session state persistence**: RAM (TMPFS) or disk (BIND)
* ✅ **Multiple dataset modes**: NONE, LOCAL_RO (read-only mount), API_TMPFS (on-demand staging)
* ✅ **Artifact pipeline**: deduplication, DB metadata, signed download URLs
* ✅ **Simple mode**: NONE mode for general-purpose code execution without datasets

---

## Installation

1. **Clone and build:**
   ```bash
   git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
   cd LangGraph-Sandbox
   docker build -t py-sandbox:latest -f Dockerfile .
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   Required: `docker`, `httpx`, `langgraph`, `langchain-core`, `pydantic` (plus sandbox image packages like `pandas`, `matplotlib`).

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

# --- Artifacts service ---
ARTIFACTS_TOKEN_SECRET=sk-tk123456789098765432112345678900000001111
ARTIFACTS_PUBLIC_BASE_URL=http://localhost:8000
ARTIFACTS_TOKEN_TTL_SECONDS=600
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

**Production API-fed demos (default):**
```env
SESSION_STORAGE=TMPFS
DATASET_ACCESS=API_TMPFS
```

### Variables

**Core Configuration:**
* `SESSION_STORAGE`: `TMPFS` (RAM, ephemeral) or `BIND` (host folder `./sessions/<sid>`).
* `DATASET_ACCESS`: `NONE` (no datasets), `LOCAL_RO` (mount host datasets at `/data`), or `API_TMPFS` (stage datasets into `/session/data`).

**Paths:**
* `SESSIONS_ROOT`: host dir for sessions (BIND mode & logs). Default `./sessions`.
* `BLOBSTORE_DIR`: host blob store root. Default `./blobstore`.
* `ARTIFACTS_DB`: SQLite path for artifact metadata. Default `./artifacts.db`.
* `DATASETS_HOST_RO`: **required only** when `DATASET_ACCESS=LOCAL_RO` (e.g., `./example_llm_data`).

**Docker:**
* `SANDBOX_IMAGE`: Docker image name/tag. Default `sandbox:latest`.
* `TMPFS_SIZE_MB`: tmpfs size for `/session` when using TMPFS. Default `1024`.

**Artifacts Security:**
* `ARTIFACTS_TOKEN_SECRET`: Long random string for signing download tokens (**required**).
* `ARTIFACTS_PUBLIC_BASE_URL`: Base URL for artifact downloads (**required**).
* `ARTIFACTS_TOKEN_TTL_SECONDS`: Token expiration time in seconds (optional, default: 600).

### Usage

* Shell: `export SESSION_STORAGE=TMPFS` … `python main.py`
* Docker: `docker run --env-file ./.env your-image`
* Compose: add `env_file: [.env]` or `environment:` entries.

> Tip: add `.env` / `docker.env` to `.gitignore` if they may contain machine‑specific paths or secrets.

---

## Usage

Run your LangGraph app:
```bash
python main.py
```

The agent can now invoke the code execution tool. User code writes files to `/session/artifacts/` which are automatically ingested into the artifact store with deduplication and signed download URLs.

---

## Repository Layout

```text
src/
  artifacts/                 # artifact store (blob + DB bindings)
  datasets/                  # dataset staging and caching
  sandbox/                   # container lifecycle and I/O
  config.py                  # environment configuration

langgraph_app/               # LangGraph tools and graph assembly
sessions/                    # per-session folders (BIND mode)
blobstore/                   # deduped artifact blobs
artifacts.db                 # artifact metadata
```

---

## Testing

```bash
pytest -q
```
Unit tests cover config, I/O helpers, dataset cache, staging, and end-to-end integration.

---

## Quick Reference

| Use Case | Mode | Environment Variables |
|----------|------|----------------------|
| **Simple coding, algorithms** | `TMPFS_NONE` | `DATASET_ACCESS=NONE` |
| **Local dev with datasets** | `BIND_LOCAL` | `SESSION_STORAGE=BIND` + `DATASET_ACCESS=LOCAL_RO` |
| **Production API demos** | `TMPFS_API` | `DATASET_ACCESS=API_TMPFS` (default) |

```bash
# Simple execution
DATASET_ACCESS=NONE python main.py

# Local development
SESSION_STORAGE=BIND DATASET_ACCESS=LOCAL_RO DATASETS_HOST_RO=./example_llm_data python main.py

# Production (default)
python main.py
```

---

## Next steps

* Add quotas and retention policies (per‑session max size, automatic cleanup).
* Swap SQLite/blobstore to Postgres + S3/MinIO for scalability.
* Extend the fetcher to expose integrity/metadata (e.g., return `(bytes, sha256, version)`), then add a host cache by hash for cross‑session reuse.
