# Docker Sandbox Agent – Artifact Store Edition

This project provides a **Docker-based sandbox** for executing Python code inside a LangGraph agentic system.
It replaces services like E2B by running containers that isolate execution, enforce resource limits, and allow safe interaction with datasets.

The sandbox keeps Python state across tool calls and persists produced files in a **database-backed artifact store**.
Artifacts are deduplicated, assigned stable IDs, and can be downloaded or read later without exposing raw filesystem paths.

---

## Execution mode

* **Session-pinned containers**: one container per conversation (session).

  * Variables and imports live in RAM.
  * `/session` is mounted as a **tmpfs** (RAM-backed filesystem) so all datasets + artifacts live only in container memory.
  * When the container is destroyed, everything inside it is gone.
  * *Note:* if you prefer the previous implementation with datasets mounted read-only at `/data`, you can still enable it by setting the parameter `datasets_path` to the folder of the data you want to mount read only. 

---

## Datasets

* **Before**: datasets were mounted from host at `/data` (read-only).
* **Now**: datasets are pulled **on demand** by dedicated tools.

  * When the agent chooses a dataset (`download(ds_id)`), the system stages it inside `/session/data/<id>.parquet`.
  * A per-session **registry** of dataset IDs is kept.
  * At each code execution, a pre-exec sync ensures all registered datasets are present in the sandbox.
  * No disk copies are kept on the host (unless you later enable caching or cloud storage).

---

## Artifacts

* User code writes files under `/session/artifacts/`.
* After each execution:

  1. Sandbox diffs the artifact folder (before vs after run).
  2. Any new files are copied **out of the container** (since `/session` is tmpfs).
  3. Files are **ingested into the artifact store**:

     * Saved in `blobstore/` under SHA-256.
     * Metadata logged in `artifacts.db`.
     * Deduplication handled automatically.
  4. Clean **descriptors** returned with `id`, `name`, `size`, `mime`, `sha256`, `created_at`, `url`.

---

## Capabilities

**Before:**

* Resource isolation: CPU, memory, timeout limits.
* Dataset mounting from host at `/data`.
* Per-session host folder at `/session`.
* File mapping returned after each run.
* Separate stdout/stderr capture.

**Now (Artifact Store Edition + tmpfs):**

* ✅ All resource limits still apply.
* ✅ Session state in RAM (variables + datasets + artifacts).
* ✅ **No persistent host session dirs** (tmpfs instead of `./sessions/`).
* ✅ **On-demand datasets** staged into `/session/data`.
* ✅ **Artifact ingestion pipeline** with deduplication and DB-backed metadata.
* ✅ **Download API** with signed URLs.
* ✅ **Artifact reader** helpers to reload artifacts by ID into Python or pandas.


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