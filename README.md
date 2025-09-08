# Docker Sandbox Agent

This project provides a **Docker-based sandbox** for executing Python code inside a LangGraph agentic system. It replaces services like E2B by running ephemeral containers that isolate execution, enforce resource limits, and allow safe interaction with local datasets.

## Features

* **Ephemeral containers**: each tool call spins up a fresh container, ensuring clean state.
* **Resource isolation**: configurable CPU, memory, and timeout limits.
* **Dataset mounting**: host datasets (e.g. `src/llm_data/`) mounted read-only at `/data`.
* **Persistent session folder**: if enabled, `/session` allows sharing intermediate files across tool calls in the same conversation.
* **Artifact management**: code can write outputs (`.txt`, `.png`, `.csv`, etc.) to `/work/artifacts`; these are automatically copied out to a persistent host folder (`outputs/<run_id>/`).
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

   Required: `docker`, `langgraph`, `langchain-core`, `pydantic`, plus any libs you want inside the sandbox image (e.g. `pandas`, `matplotlib`).

## Usage

* Run your LangGraph app:

  ```bash
  python main.py
  ```
* The agent can now invoke the `code_sandbox` tool. Example user code inside the sandbox:

  ```python
  from pathlib import Path
  Path("artifacts").mkdir(exist_ok=True)
  Path("artifacts/output.txt").write_text("hello from sandbox")
  ```
* After execution, artifacts are available on the host under:

  ```
  outputs/<run_id>/output.txt
  ```

## Project Structure

```
project/
├── outputs/              # promoted artifacts per run
├── sandbox/              # Dockerfile for sandbox image
│   └── Dockerfile
├── src/
│   ├── llm_data/         # mounted datasets (RO at /data)
│   ├── __init__.py
│   ├── make_graph.py     # build LangGraph graph
│   ├── prompt.py         # system prompt templates
│   ├── sandbox_runner.py # sandbox execution logic
│   └── tools.py          # LangGraph tool wrapper
├── .env
├── .gitignore
├── main.py               # entrypoint to run the graph
└── README.md
```

## Notes

* Use `/data` inside sandbox code to read host datasets.
* Use `/work/artifacts` to write outputs that will be persisted to `outputs/`.
* Use `/session` if you need to share files across multiple tool calls.
* Each run gets a unique `run_id` to keep artifacts separated.
* Both **stdout** and **stderr** are captured and returned separately for debugging.
