# Docker Sandbox Agent – Artifact Store Edition

This project provides a **Docker-based sandbox** for executing Python code inside a LangGraph agentic system. It replaces services like E2B by running containers that isolate execution, enforce resource limits, and allow safe interaction with local datasets.

In this version, the sandbox not only keeps state across calls, but also persists produced files in a **database-backed artifact store**. Artifacts are deduplicated, assigned stable IDs, and can be downloaded or read later without exposing raw filesystem paths.

---

## Features

### Mode of execution

**Session-pinned containers**: keep a container alive per conversation. Variables and imports stay in RAM, and files written under `/session` persist across tool calls.

### Capabilities (previous vs now)

**Before:**
- Resource isolation: configurable CPU, memory, and timeout limits.
- Dataset mounting: host datasets (e.g. `src/llm_data/`) mounted read-only at `/data`.
- Persistent session folder: per-session directory mounted at `/session`, used for sharing files across runs.
- Artifact management: user code wrote to `/session/artifacts/`; new files were detected and mapped.
- Artifact mapping: every run returned a mapping `{container_path → host_path}`.
- Separate stdout/stderr capture.

**Now (Artifact Store Edition):**
- ✅ All previous features still apply.
- ✅ **Artifact ingestion:** after each run, new files under `/session/artifacts/` are automatically:
  - Hashed (SHA-256) and stored in a **blobstore/** folder.
  - Indexed in a SQLite database `artifacts.db` with metadata.
  - Deduplicated (same file only stored once).
  - Linked to the session/run/tool call.
  - URL injection into descriptors: tools can directly return ready-to-click download links.
  - Returned as clean **descriptors** with `id`, `name`, `size`, `mime`, `sha256`, `created_at`, `url`.
- ✅ **Download API:** FastAPI endpoints to fetch artifacts by ID with short-lived signed tokens.
- ✅ **Artifact reader:** host-side helpers to load artifacts by ID as bytes, text, or even pandas DataFrames (CSV/Parquet).

---

## Installation

1. Clone the repository.

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
* The tool response will include a clean descriptor with an `id` you can use to download or load the file.

---

## Project Structure

```
project/
├── Dockerfile                     # sandbox image (repl_server inside)
├── blobstore/                     # NEW: deduplicated file storage (by hash)
├── artifacts.db                   # NEW: SQLite DB with artifact metadata
├── sessions/                      # per-session folders (staging before ingest)
├── outputs/                       # per-run artifacts (legacy, ephemeral mode)
├── src/
│   ├── __init__.py
│   ├── llm_data/                  # datasets mounted RO at /data
│   ├── graph/
│   │   ├── code_exec_tool.py      # LangGraph tool (calls SessionManager)
│   │   ├── make_graph.py          # build LangGraph graph
│   │   └── prompt.py              # system prompts
│   ├── artifacts/                 # NEW: artifact store modules
│   │   ├── store.py               # init DB + blobstore
│   │   ├── ingest.py              # move new files into store
│   │   ├── tokens.py              # signed tokens for downloads
│   │   ├── api.py                 # FastAPI routes for downloads
│   │   └── reader.py              # host-side helpers to read artifacts
│   └── sandbox/
│       ├── repl_server.py         # runs INSIDE container (FastAPI REPL)
│       └── session_manager.py     # host-side session lifecycle + ingestion
├── tests/
│   ├── test_session.py            # legacy session tests
│   ├── test_artifact_ingest_smoke.py
│   ├── test_artifact_download_api.py
│   └── test_artifact_reader.py
├── .env
├── .gitignore
├── main.py                        # app entrypoint (starts LangGraph app)
├── README.md
└── requirements.txt               # host deps: docker, httpx, langgraph, etc.

```

---

## Next Steps

- Add **quotas and retention policies** (per-session max size, automatic cleanup of old artifacts).
- Swap SQLite/blobstore to **Postgres + S3/MinIO** for scalability without changing the tool contract.
- Extend the reader to support **image previews or HTML rendering** for richer UI integrations.