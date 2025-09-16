# LangGraph Sandbox – Docker-Based Code Execution Environment

A production-ready Docker sandbox for executing Python code within LangGraph agentic systems. Provides secure, isolated code execution with persistent state, dataset management, and automatic artifact storage.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Execution Modes](#execution-modes)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Artifact System](#artifact-system)
- [Session Management](#session-management)
- [Development & Debugging](#development--debugging)
- [Installation](#installation)
- [API Reference](#api-reference)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Overview

This sandbox replaces services like E2B by running isolated Docker containers for each conversation session. It provides:

- **Session-pinned containers**: One container per conversation with persistent Python state
- **Multiple storage modes**: RAM (TMPFS) or disk (BIND) for session data
- **Flexible dataset access**: No datasets, local read-only mounts, or API-based staging
- **Automatic artifact management**: Files are deduplicated, stored securely, and accessible via signed URLs
- **Enhanced debugging**: Complete execution logs and state inspection in BIND mode

## Key Features

- ✅ **Resource isolation**: CPU, memory, and timeout limits
- ✅ **Session state persistence**: Variables and imports persist across tool calls
- ✅ **Six execution modes**: From simple code execution to full dataset analysis
- ✅ **Automatic artifact pipeline**: Deduplication, metadata tracking, and secure downloads
- ✅ **Enhanced debugging**: Complete execution logs and state snapshots (BIND mode)
- ✅ **Production-ready**: Secure token system, configurable timeouts, and error handling

## Execution Modes

The system offers six execution modes based on two independent configuration knobs:

| Mode | Session Storage | Dataset Access | Description | Best For |
|------|----------------|----------------|-------------|----------|
| **TMPFS_NONE** | RAM (TMPFS) | None | Simple sandbox in memory | Algorithms, calculations, demos |
| **BIND_NONE** | Disk (BIND) | None | Persistent sandbox on disk | Debugging, persistent development |
| **TMPFS_LOCAL** | RAM (TMPFS) | Local RO | Memory + host datasets | Fast analysis with large datasets |
| **BIND_LOCAL** | Disk (BIND) | Local RO | Persistent + host datasets | Full development with datasets |
| **TMPFS_API** | RAM (TMPFS) | API | Memory + API datasets | Multi-tenant, cloud datasets |
| **BIND_API** | Disk (BIND) | API | Persistent + API datasets | Development with API datasets |

### Recommended Defaults

- **Simple coding**: `TMPFS_NONE` - Perfect for general-purpose coding without datasets
- **Production demos**: `TMPFS_API` - Multi-tenant with dynamic dataset loading
- **Local development**: `BIND_LOCAL` - Full debugging with local datasets

## Quick Start

### Option 1: Python Package Installation (Recommended)

```bash
# Clone and install the package
git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
cd LangGraph-Sandbox
pip install -e .

# Build the Docker image
docker build -t sandbox:latest -f Dockerfile .
```

Set your OpenAI API key by modifying the [`simple_sandbox.env`](usage_examples\simple_sandbox\simple_sandbox.env) file, and run a the example:

```bash
# Run the simple sandbox
langgraph-sandbox
```

This will start a simple LangGraph agent with sandbox-coding capabilities. 

### Option 2: Manual Installation

```bash
# Clone the repository and build the Docker Image
git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
cd LangGraph-Sandbox
docker build -t sandbox:latest -f Dockerfile .

# Install Dependencies
pip install -r requirements.txt
```

Then set your OpenAI API key by modifying the [`simple_sandbox.env`](usage_examples\simple_sandbox\simple_sandbox.env) file and run a simple example:

```bash
# Run Simple Example
python main.py
```

## Configuration

Configuration is managed through environment variables with sensible defaults:

### Core Settings

```env
# Session storage: TMPFS (RAM) or BIND (disk)
SESSION_STORAGE=TMPFS

# Dataset access: NONE, LOCAL_RO, or API
DATASET_ACCESS=API

# Paths (optional - defaults provided)
SESSIONS_ROOT=./sessions
BLOBSTORE_DIR=./blobstore
ARTIFACTS_DB=./artifacts.db

# Required only for LOCAL_RO mode
DATASETS_HOST_RO=./example_llm_data

# Docker settings
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=1024
```

### Quick Configuration Examples

**Simple execution:**

In `.env`, set `DATASET_ACCESS=NONE`, then:
```bash
python main.py
```

**Local development:**

In `.env`, set `SESSION_STORAGE=BIND`, `DATASET_ACCESS=LOCAL_RO` and `DATASETS_HOST_RO=./`, then:
```bash
data python main.py
```

**Production (default):**
```bash
python main.py
```

## Usage Examples

The repository includes three complete examples demonstrating different modes:

### Simple Sandbox (TMPFS_NONE)
```bash
cd usage_examples/simple_sandbox
python main.py
```
or simply (this is the default example)
```bash
langgraph-sandbox
``` 

- No datasets, pure code execution
- Perfect for algorithms and calculations
- Everything runs in memory

### Fully Local (BIND_LOCAL)
```bash
cd usage_examples/fully_local
python main.py
```
- Persistent session storage
- Local datasets mounted read-only
- Full debugging capabilities

### TMPFS API (TMPFS_API)
```bash
cd usage_examples/tmpfs_api
python main.py
```
- Dynamic dataset fetching via API
- Memory-based caching
- Multi-tenant ready

## Tool Factory 

The system provides **production-ready LangGraph tools** out of the box through simple factory functions. These tools handle all the complexity of container management, session persistence, and artifact processing automatically.

### 🚀 **Ready-to-Use Tools**

**`make_code_sandbox_tool`** - Execute Python code with persistent state
- Maintains variables and imports across executions
- Automatic artifact detection and ingestion
- Memory cleanup to prevent container bloat
- Session-pinned containers for consistency

**`make_select_dataset_tool`** - Load datasets on-demand (**only in API mode**)
- Fetches datasets from your API sources
- Stages them directly into the sandbox
- Smart caching with PENDING/LOADED/FAILED status tracking
- Client wrapper pattern for easy integration *(note)[]

**`make_export_datasets_tool`** - Export modified datasets to host filesystem
- Timestamped exports to prevent overwrites
- Automatic artifact ingestion for download URLs
- Works with any file in `/session/data/`

Instead of writing custom tool implementations, you get:
- **Zero boilerplate**: Just call the factory with your dependencies
- **Battle-tested**: Handles edge cases, timeouts, and error recovery
- **Consistent**: Same patterns across all your LangGraph applications
- **Extensible**: Easy to customize with your own fetch functions and clients

```python
# Example: Create tools in 3 lines
code_tool = make_code_sandbox_tool(session_manager=sm, session_key_fn=get_session)
dataset_tool = make_select_dataset_tool(session_manager=sm, fetch_fn=my_fetch, client=my_client)
export_tool = make_export_datasets_tool(session_manager=sm, session_key_fn=get_session)
``` 

> **Note:** Notice that the `make_select_dataset_tool` expects the `fetch_fn` parameter to be a function that, given your dataset_id, returns the dataset **bytes** through your API client. 
>
> If in your implementation you need to pass your API `client` to the `select_dataset` tool (as we did in our [custom example](usage_examples\tmpfs_api\ex3_graph\tools.py)), you can do so by simply specifing the `client` as an input parameter. It will be automatically wrapped without any needed changes. 

## Artifact System

Files saved to `/session/artifacts/` are automatically processed:

1. **Ingestion**: Files are copied from the container
2. **Deduplication**: SHA-256 based content addressing
3. **Storage**: Saved in `blobstore/` with metadata in SQLite
4. **Access**: Secure download URLs with time-limited tokens
5. **Cleanup**: Original files removed from session directory

### Artifact Features

- **Automatic deduplication**: Identical files share storage
- **Secure downloads**: Signed URLs with configurable expiration
- **Metadata tracking**: Size, MIME type, creation time, session links
- **Content addressing**: SHA-256 based blob storage
- **API access**: REST endpoints for artifact management

### Security

- ✅ **Auto-generated secrets**: Secure token signing keys
- ✅ **Short-lived tokens**: Default 10-minute expiration
- ✅ **No manual configuration**: Works out of the box
- ✅ **Content verification**: SHA-256 integrity checking

## Session Management

### Session Lifecycle

1. **Creation**: Container started with session-specific configuration
2. **Execution**: Code runs with persistent Python state
3. **Artifact Processing**: Files automatically ingested after each run
4. **Cleanup**: Container stopped, resources released

### Session State

- **Variables**: All Python variables persist between executions
- **Imports**: Module imports remain available
- **Working Directory**: Consistent `/session` working directory
- **Environment**: Isolated Python environment with common packages

## Development & Debugging

### BIND Mode Enhanced Features

When using `SESSION_STORAGE=BIND`, the system provides comprehensive debugging capabilities:

#### Session Directory Structure
```
sessions/<session_id>/
├── session.log                    # Complete execution history
├── session_metadata.json          # Session info and statistics
├── python_state.json             # Current Python state snapshot
└── artifacts/                    # Ingested at runtime
```

#### Session Viewer Tool
```bash
# View complete session information
python src/sandbox/session_viewer.py sessions/<session_id>

# View last 10 log entries
python src/sandbox/session_viewer.py sessions/<session_id> --limit 10

# Skip state and artifacts display
python src/sandbox/session_viewer.py sessions/<session_id> --no-state --no-artifacts
```

#### Debugging Benefits

- **Complete execution history**: See all code executed and results
- **State inspection**: View variables, imports, and Python environment
- **Artifact tracking**: Monitor file creation and processing
- **Container information**: Track container lifecycle and configuration
- **Performance analysis**: Execution timing and resource usage


### Docker Image

The sandbox runs in a custom Docker image with:
- Python 3.11
- Common data science packages (pandas, numpy, matplotlib, etc.)
- Security-hardened configuration
- Resource limits and timeouts

## API Reference

### Artifact API Endpoints

- `GET /artifacts/{artifact_id}?token={token}` - Download artifact
- `HEAD /artifacts/{artifact_id}?token={token}` - Get artifact metadata

### Configuration API

- `Config.from_env()` - Load configuration from environment
- `Config.from_env(env_file_path)` - Load from specific file

### Session Management

- `SessionManager.start(session_id)` - Start new session
- `SessionManager.exec(session_id, code)` - Execute code
- `SessionManager.stop(session_id)` - Stop session

## Troubleshooting

### Common Issues

**Container startup failures:**
- Ensure Docker is running
- Check `SANDBOX_IMAGE` points to correct image
- Verify sufficient disk space

**Dataset access problems:**
- For `LOCAL_RO`: Ensure `DATASETS_HOST_RO` path exists
- For `API`: Check network connectivity and API configuration
- Verify dataset files are in Parquet format

**Artifact download failures:**
- Check artifact server is running (port 8000)
- Verify token hasn't expired
- Ensure artifact ID is correct

## Next Steps

- **Quotas**: Add per-session size limits and retention policies
- **Scalability**: Migrate to Postgres + S3/MinIO for production
- **Monitoring**: Add metrics and health checks
- **Extensions**: Support for additional languages and frameworks

For more examples and detailed documentation, see the `usage_examples/` directory.