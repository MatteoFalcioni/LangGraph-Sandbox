# LangGraph Sandbox – Docker-Based Code Execution Environment

A production-ready Docker sandbox for executing Python code within LangGraph agentic systems. Provides secure, isolated code execution with persistent state, dataset management, and automatic artifact storage.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Execution Modes](#execution-modes)
- [Quick Start](#quick-start)
- [Using as a Package in Other Projects](#using-as-a-package-in-other-projects)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Tool Factory](#tool-factory)
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

#### For Development/Testing:
```bash
# Clone and install the package
git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
cd LangGraph-Sandbox

# Ensure you have Python >= 3.11
python --version  # Should show Python 3.11.x or higher

# Install the package in development mode
pip install -e .

# Build the Docker image
docker build -t sandbox:latest -f Dockerfile .
```

Set your OpenAI API key by modifying the [`simple_sandbox.env`](usage_examples\simple_sandbox\simple_sandbox.env) file, and run the example:

```bash
# Run the simple sandbox
langgraph-sandbox
```

#### For Using in Other Projects:
```bash
# Install the package (development mode)
pip install -e /path/to/LangGraph-Sandbox

# Or install from built package
pip install dist/langgraph_sandbox-0.1.0-py3-none-any.whl

# Run setup to copy Docker files and build image
sandbox-setup
```

Then customize your `.env` file and use in your code:

```python
from langgraph_sandbox import make_code_sandbox_tool, SessionManager, Config

# Load configuration
config = Config.from_env()
session_manager = SessionManager(
    image=config.sandbox_image,
    session_storage=config.session_storage,
    dataset_access=config.dataset_access,
    datasets_path=config.datasets_host_ro,
    session_root=config.sessions_root,
    tmpfs_size=config.tmpfs_size_mb,
)

# Create tools with a session key function
def get_session_key():
    return "my_unique_session_id"  # Use your own session management key if needed for UI (otherwise defaults to convo)

code_tool = make_code_sandbox_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key
)
```

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
langgraph-sandbox
```

## Using as a Package in Other Projects

### Installation

**Requirements:**
- Python >= 3.11
- Docker installed and running

```bash
# Install in development mode (recommended for local development)
pip install -e /path/to/LangGraph-Sandbox

# Or install from built package
pip install dist/langgraph_sandbox-0.1.0-py3-none-any.whl
```

**Note:** After installation, the package modules are available as top-level imports:
- `from langgraph_sandbox import make_code_sandbox_tool, SessionManager, Config`
- `import langgraph_sandbox.tool_factory`, `import langgraph_sandbox.sandbox`, `import langgraph_sandbox.artifacts`, `import langgraph_sandbox.datasets`

**Usage Examples:** The package includes complete usage examples that are installed with the package. You can find them in your Python environment or use them as templates for your own projects.

### Setup Docker Environment

After installation, run the setup command to copy Docker files to your project directory:

```bash
sandbox-setup
```

This command will:
- Copy Docker files (`Dockerfile`, `example.env`, `docker.env`) to your current directory
- Copy the `sandbox/` directory needed for Docker build
- Provide instructions for building the Docker image

Then build the Docker image:
```bash
docker build -t sandbox:latest -f Dockerfile .
```

### Customize Configuration

Edit the `.env` file to customize your setup:

```bash
nano .env
```

Key settings you might want to change:
- `SESSION_STORAGE`: `TMPFS` (default) or `BIND`
- `DATASET_ACCESS`: `API`, `LOCAL_RO`, or `API_TMPFS`
- `SESSIONS_ROOT`: Directory for session storage
- `SANDBOX_IMAGE`: Docker image name (default: `sandbox:latest`)
- `TMPFS_SIZE_MB`: Size of tmpfs mount (default: 1024)

### Usage in Your Code

```python
from langgraph_sandbox import (
    make_code_sandbox_tool,
    make_select_dataset_tool,
    make_export_datasets_tool,
    make_list_datasets_tool,
    SessionManager,
    Config
)

# Load configuration
config = Config.from_env()

# Create session manager
session_manager = SessionManager(
    image=config.sandbox_image,
    session_storage=config.session_storage,
    dataset_access=config.dataset_access,
    datasets_path=config.datasets_host_ro,
    session_root=config.sessions_root,
    tmpfs_size=config.tmpfs_size_mb,
)

# Create tools with a session key function
def get_session_key():
    return "my_unique_session_id"  # Use your own session management

code_tool = make_code_sandbox_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key,
    timeout_s=60
)

# Custom dataset fetching function
def my_fetch_function(dataset_id: str) -> bytes:
    # Your custom logic to fetch dataset
    return dataset_bytes

dataset_tool = make_select_dataset_tool(
    session_manager=session_manager,
    fetch_fn=my_fetch_function
)

# Use in your LangGraph workflow
# ... your code here
```

### Project Structure After Setup

```
your-project/
├── .env                    # Your configuration
├── Dockerfile             # Copied from package
├── example.env            # Template (copied from package)
├── docker.env             # Alternative config (copied from package)
├── your_code.py           # Your Python code
└── ...
```

### Custom Docker Image

To use a custom Docker image:

1. Modify the Dockerfile in your project directory
2. Update the `SANDBOX_IMAGE` in your `.env` file
3. Rebuild the image:
   ```bash
   docker build -t your-custom-image:latest .
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
langgraph-sandbox
```

**Local development:**

In `.env`, set `SESSION_STORAGE=BIND`, `DATASET_ACCESS=LOCAL_RO` and `DATASETS_HOST_RO=./`, then:
```bash
data python main.py
```

**Production (default):**
```bash
langgraph-sandbox
```

## Usage Examples

The repository includes three complete examples demonstrating different modes. **Run all examples from the project root directory:**

### Simple Sandbox (TMPFS_NONE)
```bash
# From project root - recommended approach
langgraph-sandbox

# Alternative: run directly from example directory
cd usage_examples/simple_sandbox
python main.py
```
- No datasets, pure code execution
- Perfect for algorithms and calculations
- Everything runs in memory

### Fully Local (BIND_LOCAL)
```bash
# From project root
cd usage_examples/fully_local
python main.py
```
- Persistent session storage
- Local datasets mounted read-only
- Full debugging capabilities

### TMPFS API (TMPFS_API)
```bash
# From project root
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
- Client wrapper pattern for easy integration

**`make_export_datasets_tool`** - Export modified datasets to host filesystem
- Timestamped exports to prevent overwrites
- Automatic artifact ingestion for download URLs
- Works with any file in `/session/data/`

**`make_list_datasets_tool`** - List available datasets in the sandbox
- **API mode**: Lists datasets loaded in `/session/data` (dynamically loaded datasets)
- **LOCAL_RO mode**: Lists statically mounted files in `/data` (host-mounted datasets)
- **NONE mode**: Returns message indicating no datasets are available
- Provides detailed file information including size, modification time, and paths

Instead of writing custom tool implementations, you get:
- **Zero boilerplate**: Just call the factory with your dependencies
- **Battle-tested**: Handles edge cases, timeouts, and error recovery
- **Consistent**: Same patterns across all your LangGraph applications
- **Extensible**: Easy to customize with your own fetch functions and clients

```python
# Example: Create tools in 4 lines
def get_session_key():
    return "my_session_id"  # Implement your session management logic

code_tool = make_code_sandbox_tool(session_manager=sm, session_key_fn=get_session_key)
dataset_tool = make_select_dataset_tool(session_manager=sm, fetch_fn=my_fetch, client=my_client)
export_tool = make_export_datasets_tool(session_manager=sm, session_key_fn=get_session_key)
list_tool = make_list_datasets_tool(session_manager=sm, session_key_fn=get_session_key)
```

> **Session Key Management:** The `session_key_fn` parameter is crucial for maintaining session isolation. Each unique session key gets its own container, so implement proper session management in your application (e.g., user ID, conversation ID, or thread ID). You can see in our example that we did it in main by generating a random session key.

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
python langgraph_sandbox/sandbox/session_viewer.py sessions/<session_id>

# View last 10 log entries
python langgraph_sandbox/sandbox/session_viewer.py sessions/<session_id> --limit 10

# Skip state and artifacts display
python langgraph_sandbox/sandbox/session_viewer.py sessions/<session_id> --no-state --no-artifacts
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

**Import errors (`ModuleNotFoundError`):**
- Ensure you have Python >= 3.11: `python --version`
- Install in the correct environment: `pip install -e .`
- If using conda, activate the correct environment first
- For usage examples, run from project root: `langgraph-sandbox`

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

**Usage example failures:**
- Examples must be run from the project root directory
- Use `langgraph-sandbox` command
- Do not run examples directly from their subdirectories

## Next Steps

- **Quotas**: Add per-session size limits and retention policies
- **Scalability**: Migrate to Postgres + S3/MinIO for production
- **Monitoring**: Add metrics and health checks
- **Extensions**: Support for additional languages and frameworks

For more examples and detailed documentation, see the `usage_examples/` directory.