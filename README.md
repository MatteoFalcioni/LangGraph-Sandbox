# Docker Sandbox Agent

This project provides a **Docker-based sandbox** for executing Python code inside a LangGraph agentic system. It replaces services like E2B by running containers that isolate execution, enforce resource limits, and allow safe interaction with local datasets.

## Features

### Modes of execution

* **Ephemeral containers**: each tool call spins up a fresh container, ensuring clean state.
* **Session-pinned containers**: optionally keep a container alive per conversation. Variables and imports stay in RAM, and files written under `/session` persist across tool calls.

### Capabilities

* **Resource isolation**: configurable CPU, memory, and timeout limits.
* **Dataset mounting**: host datasets (e.g. `src/llm_data/`) mounted read-only at `/data`.
* **Persistent session folder**: per-session directory mounted at `/session`, used for sharing files across runs.
* **Artifact management**: user code writes to `/session/artifacts/`; new files are automatically detected and mapped.
* **Artifact mapping**: every run returns a mapping `{container_path → host_path}` so the agent/UI can reference both.
* **Separate stdout/stderr capture**: logs from the sandbox are returned split into stdout and stderr for easier debugging.

## Installation

1. Clone the repository.
2. Build the sandbox image:

   ```bash
   docker build -t py-sandbox:latest -f sandbox/Dockerfile sandbox/
   ```
3. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   Required: `docker`, `httpx`, `langgraph`, `langchain-core`, `pydantic`, plus any libs you want inside the sandbox image (e.g. `pandas`, `matplotlib`).

## Usage

* Run your LangGraph app:

  ```bash
  python main.py
  ```

* The agent can now invoke the `code_sandbox` tool.

### Example inside the sandbox

```python
from pathlib import Path

# RAM state persists across calls in session-pinned mode
x = 42

# Write an artifact
Path("/session/artifacts").mkdir(parents=True, exist_ok=True)
(Path("/session/artifacts/output.txt")).write_text("hello from sandbox")
```

* After execution, artifacts are available on the host under:

```
sessions/<session_id>/artifacts/output.txt
```

## Project Structure

```
project/
├── outputs/              # per-run artifacts (ephemeral mode)
├── sessions/             # per-session folders (session-pinned mode)
├── sandbox/              # Dockerfile for sandbox image
│   └── Dockerfile
├── src/
│   ├── llm_data/         # mounted datasets (RO at /data)
│   ├── __init__.py
│   ├── make_graph.py     # build LangGraph graph
│   ├── prompt.py         # system prompt templates
│   ├── repl_server.py    # REPL server running inside container
│   ├── session_manager.py# host-side session lifecycle manager
│   ├── sandbox_runner.py # legacy ephemeral execution path
│   └── tools.py          # LangGraph tool wrapper
├── .env
├── .gitignore
├── main.py               # entrypoint to run the graph
└── README.md
```

## Notes

* Use `/data` inside sandbox code to read host datasets.
* Use `/session/artifacts` to write outputs that persist and are pulled out.
* In ephemeral mode, use `/work/artifacts` → artifacts will be promoted under `outputs/<run_id>/`.
* Each session or run returns an `artifact_map` so the UI can link container paths to host paths.
* Both **stdout** and **stderr** are captured and returned separately for debugging.
* Use `reset_sandbox` tool (if enabled) to stop a running session and clean up its container.
