# Docker Sandbox Agent – Artifact Store Edition

This project provides a **Docker-based sandbox** for executing Python code inside a LangGraph agentic system.
It replaces services like E2B by running containers that isolate execution, enforce resource limits, and allow safe interaction with datasets.

The sandbox keeps Python state across tool calls and persists produced files in a **database-backed artifact store**.
Artifacts are deduplicated, assigned stable IDs, and can be downloaded or read later without exposing raw filesystem paths.

---

## Execution Mode

* **Session-pinned containers**: one container per conversation (session).

  * Variables and imports live in RAM.
  * `/session` can be backed by either **tmpfs (RAM)** or a **bind mount** on the host (`./sessions/<sid>`).
  * When using tmpfs, all data lives in memory and is discarded on container removal.
  * When using bind mount, a host folder persists session state for local inspection.

---

## Storage & Dataset Modes

Two independent knobs define runtime behavior:

* **SessionStorage**: `BIND` (disk) vs `TMPFS` (RAM)
* **DatasetAccess**: `LOCAL_RO` (host datasets at `/data`) vs `API_TMPFS` (datasets staged into `/session/data`)

### The Four Paths

| ID    | SessionStorage | DatasetAccess  | Description                                                                 | When to use                                                    |
| ----- | -------------- | -------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| **A** | **BIND**       | **LOCAL\_RO**  | Session on disk (`./sessions/<sid>`), datasets mounted RO at `/data`        | Super local dev, debugging, persistent session files           |
| **B** | **TMPFS**      | **LOCAL\_RO**  | Session in RAM, datasets from host RO at `/data`                            | Big/static datasets + fast ephemeral scratch; immutable inputs |
| **C** | **TMPFS**      | **API\_TMPFS** | Fully ephemeral: datasets staged into `/session/data` (RAM), session in RAM | Lightweight, multi-tenant, API-fed demos                       |
| **D** | **BIND**       | **API\_TMPFS** | Datasets staged into `/session/data`, session on disk                       | Persistent session folder but API-fetched datasets (rare)      |

### Recommended Defaults

* **Production / multi-tenant demos:** **C (TMPFS + API\_TMPFS)**. If datasets are huge & stable, prefer **B**.
* **Local dev/debug:** **A (BIND + LOCAL\_RO)**.

---

## Datasets

* **LOCAL\_RO:** Mount a host datasets directory read-only at `/data`. Good for large/static inputs.
* **API\_TMPFS:** Fetch datasets on demand into `/session/data/<id>.parquet`. Cleanest for ephemeral runs.

---

## Artifacts

* User code writes files under `/session/artifacts/`.
* After each execution:

  1. Sandbox diffs the artifact folder (before vs after run).
  2. Any new files are copied out of the container (if TMPFS) or read from host (if BIND).
  3. Files are ingested into the artifact store:

     * Saved in `blobstore/` under SHA-256.
     * Metadata logged in `artifacts.db`.
     * Deduplication handled automatically.
     * Deleted from `/session/artifacts/`.

  4. Descriptors returned with `id`, `name`, `size`, `mime`, `sha256`, `created_at`, `url`.

---

## Capabilities

* ✅ Resource isolation: CPU, memory, timeout limits.
* ✅ Session state persisted in RAM (TMPFS) or on disk (BIND).
* ✅ Dataset access via on-demand API staging or local read-only mount.
* ✅ Artifact ingestion pipeline with deduplication and DB-backed metadata.
* ✅ Download API with signed URLs.
* ✅ Artifact reader helpers to reload artifacts by ID.

---

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
   ```

2. Build the sandbox image:

   ```bash
   docker build -t py-sandbox:latest -f sandbox/Dockerfile sandbox/
   ```

3. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   Required: `docker`, `httpx`, `langgraph`, `langchain-core`, `pydantic`, plus any libs you want inside the sandbox image (e.g. `pandas`, `matplotlib`).

---

## Usage

* Run your LangGraph app:

  ```bash
  python main.py
  ```

* The agent can now invoke the `code_sandbox` tool.

### Example inside the sandbox

```python
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# RAM state persists across calls in session-pinned mode
x = np.linspace(-2, 2, 100)
y = np.sin(x)

# Write an artifact (plot)
Path("/session/artifacts").mkdir(parents=True, exist_ok=True)
plt.plot(x, y)
plt.savefig("/session/artifacts/sin.png")
print("Plot saved to /session/artifacts/sin.png")
```

* After execution, the file will be ingested into the artifact store.
* The tool response will include a descriptor with an `id` you can use to download or load the file.

---

## Project Structure

```
project/
├── Dockerfile                     # sandbox image (repl_server inside)
├── blobstore/                     # deduplicated file storage (by hash)
├── artifacts.db                   # SQLite DB with artifact metadata
├── sessions/                      # per-session folders (if BIND mode)
├── outputs/                       # legacy per-run artifacts (ephemeral)
├── src/
│   ├── __init__.py
│   ├── llm_data/                  # datasets (if LOCAL_RO)
│   ├── graph/
│   │   ├── code_exec_tool.py      # LangGraph tool (calls SessionManager)
│   │   ├── make_graph.py          # build LangGraph graph
│   │   └── prompt.py              # system prompts
│   ├── artifacts/
│   │   ├── store.py               # init DB + blobstore
│   │   ├── ingest.py              # move new files into store
│   │   ├── tokens.py              # signed tokens for downloads
│   │   ├── api.py                 # FastAPI routes for downloads
│   │   └── reader.py              # host-side helpers to read artifacts
│   └── sandbox/
│       ├── repl_server.py         # runs INSIDE container (FastAPI REPL)
│       └── session_manager.py     # host-side session lifecycle + ingestion
├── tests/
│   ├── test_session.py
│   ├── test_artifact_ingest_smoke.py
│   ├── test_artifact_download_api.py
│   └── test_artifact_reader.py
├── .env
├── .gitignore
├── main.py                        # app entrypoint
├── README.md
└── requirements.txt               # host deps
```

---

## Next Steps

* Add quotas and retention policies (per-session max size, automatic cleanup).
* Swap SQLite/blobstore to Postgres + S3/MinIO for scalability.
* Extend the reader to support image previews or HTML rendering for richer UI integrations.
