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
- **Docker Compose setup out-of-the-box**: Possibility to choose network-oriented compose or simple docker image runs

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

### Option 1: Manual Installation

```bash
# Clone the repository and build the Docker Image
git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
cd LangGraph-Sandbox

# Install Dependencies
pip install -r requirements.txt

# Set up the sandbox environment (copies required files)
python sandbox-setup

# Set up configuration
cp sandbox.env.example sandbox.env
# Edit sandbox.env and add your OPENAI_API_KEY

# Build the Docker image
docker build -t sandbox:latest -f Dockerfile.sandbox .
```

Run a simple example:

```bash
# Run Simple Example
langgraph-sandbox
```

### Option 2: Python Package Installation 

```bash
# Clone and install the package
git clone https://github.com/MatteoFalcioni/LangGraph-Sandbox
cd LangGraph-Sandbox

# Ensure you have Python >= 3.11
python --version  # Should show Python 3.11.x or higher

# Install the package in development mode
pip install -e .

# Set up the sandbox environment (copies required files)
sandbox-setup
```
you should see: 
```bash
Setting up LangGraph Sandbox...
✓ Copied Dockerfile.sandbox
✓ Copied docker-compose.yml
✓ Copied docker-compose.override.yml
✓ Copied sandbox.env.example
✓ Copied sandbox/ directory
#...
```

then:

```bash
# Set up configuration
cp sandbox.env.example sandbox.env
# Edit sandbox.env and add your OPENAI_API_KEY

# Build the Docker image
docker build -t sandbox:latest -f Dockerfile.sandbox .
```

Run the example:

```bash
# Run the simple sandbox
langgraph-sandbox
```

#### For Using in Other Projects:

Once you have cloned the repo to your `<path_to_LangGraph-Sandbox>`:
```bash
# Install the package (development mode)
pip install -e <path_to_LangGraph-Sandbox>
```

then follow the same steps of [option 2 above](#option-2-python-package-installation)

### Project Structure After Setup

```
your-project/
├── sandbox.env                    # Your configuration (copy from sandbox.env.example)
├── Dockerfile.sandbox             # Copied from package
├── docker-compose.yml             # Copied from package
├── docker-compose.override.yml    # Copied from package
├── sandbox.env.example            # Template (copied from package)
├── sandbox/                       # Sandbox runtime files
├── your_code.py                   # Your Python code
└── ...
```

## Configuration

Configuration is managed through environment variables with sensible defaults:

### Core Settings

```sandbox.env

# --- Core knobs ---
SESSION_STORAGE=TMPFS        # TMPFS | BIND
DATASET_ACCESS=API           # API | LOCAL_RO | NONE

# --- Host paths ---
SESSIONS_ROOT=./sessions
BLOBSTORE_DIR=./blobstore
ARTIFACTS_DB=./artifacts.db

# Required ONLY if DATASET_ACCESS=LOCAL_RO
# DATASETS_HOST_RO=./example_llm_data

# --- Docker / runtime ---
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=1024

# --- Artifact display options ---
IN_CHAT_URL=false            # true | false (default: false)

# --- Network configuration ---
# "host" strategy: Uses port mapping, works everywhere (recommended)
# "container" strategy: Uses Docker network DNS, requires Docker Compose
SANDBOX_ADDRESS_STRATEGY=host  # "container" for Docker network DNS, "host" for port mapping
COMPOSE_NETWORK=langgraph-network  # Docker network name (optional, only used with container strategy)
HOST_GATEWAY=host.docker.internal  # Gateway hostname for host strategy (auto-detected in WSL2)

# --- External API keys ---
# OPENAI_API_KEY=your_openai_api_key_here

# --- Artifacts service (optional) ---
# ARTIFACTS_PUBLIC_BASE_URL=http://localhost:8000  # default: http://localhost:8000
# ARTIFACTS_TOKEN_TTL_SECONDS=600                  # default: 600 seconds
```

### Quick Configuration Examples

**Simple execution:**

In `sandbox.env`, set `DATASET_ACCESS=NONE`, then:
```bash
langgraph-sandbox
```

**Local development:**

In `sandbox.env`, set `SESSION_STORAGE=BIND`, `DATASET_ACCESS=LOCAL_RO` and `DATASETS_HOST_RO=./`, then:
```bash
langgraph-sandbox
```

**Production (default -> TMPFS+API):**
```bash
langgraph-sandbox
```

**Docker Compose:**
```bash
# Start container
docker-compose up -d

# Run langgraph-sandbox on HOST machine (connects to container)
langgraph-sandbox

# Or customize in docker-compose.yml:
# SANDBOX_ADDRESS_STRATEGY=container
# COMPOSE_NETWORK=langgraph-network
```

### Artifact Display Options

The `IN_CHAT_URL` setting controls how generated artifacts (plots, files, etc.) are displayed:

- **`IN_CHAT_URL=false` (default)**: Artifacts are not displayed in chat, but are still returned as artifacts in tools and can be displayed in main app; see [main.py](langgraph_sandbox/main.py) for an example. 

- **`IN_CHAT_URL=true`**: Artifacts are displayed directly in the chat with download links. Useful for interactive sessions where you want immediate access to generated files.

> **Note:** careful if adding artifacts URLs to chat, because they might confuse your agent. For bigger, smarter models it's fine, but smaller models may run off track seeing urls. 

### Network Configuration

**Host Strategy** (default, recommended):
```env
SANDBOX_ADDRESS_STRATEGY=host
HOST_GATEWAY=host.docker.internal
```
- Uses host port mapping and gateway
- Compatible with traditional Docker deployment
- URL: `http://host.docker.internal:{mapped_port}` (or `http://localhost:{mapped_port}` in WSL2)
- **Auto-detects environment**: Automatically uses `localhost` in WSL2, `host.docker.internal` in Docker Desktop
- **This is the default configuration** - works out of the box everywhere

**Container Strategy** (for Docker Compose deployments):
```env
SANDBOX_ADDRESS_STRATEGY=container
COMPOSE_NETWORK=langgraph-network
```
- Containers communicate via Docker network DNS
- No port mapping needed
- URL: `http://sbox-{session_id}:9000`
- Requires Docker Compose setup (see Docker Compose Setup below)

### Docker Compose Setup

The project includes a `docker-compose.yml` file with **pre-configured networking** for the container strategy:

#### ✅ Container Strategy Networking (Already Configured):

The `docker-compose.yml` file already includes:
- Custom Docker network: `langgraph-network`
- Proper network configuration for container strategy
- Default environment variables set correctly

**Note:** The default `sandbox.env.example` uses Host Strategy. To use Container Strategy with Docker Compose, change `SANDBOX_ADDRESS_STRATEGY=container` in your `sandbox.env` file.

#### Manual Network Creation (if needed):

If you encounter network issues, you can manually create the network:
```bash
docker network create langgraph-network
```

#### Troubleshooting Container Strategy:

If you encounter issues with container strategy:

1. **Check if network exists:**
   ```bash
   docker network ls | grep langgraph-network
   ```

2. **Verify container is in correct network:**
   ```bash
   docker inspect sbox-{session_id} | grep -A 10 "Networks"
   ```

3. **Test connectivity from main app:**
   ```bash
   docker exec -it {main_app_container} curl http://sbox-{session_id}:9000/health
   ```

### Docker Compose Example

The project includes a `docker-compose.yml` file demonstrating both strategies:

**Container Strategy (default):**
```yaml
services:
  app:
    environment:
      SANDBOX_ADDRESS_STRATEGY: container
      COMPOSE_NETWORK: langgraph-network
    networks:
      - langgraph-network

networks:
  langgraph-network:
    driver: bridge
```

**Host Strategy (override):**
```yaml
# docker-compose.override.yml
services:
  app:
    environment:
      SANDBOX_ADDRESS_STRATEGY: host
      HOST_GATEWAY: host.docker.internal
    ports:
      - "9000:9000"  # Sandbox REPL
```

Run with:
```bash
# Container strategy (default)
docker-compose up -d
langgraph-sandbox  # Run on HOST machine

# Host strategy (with override)
docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
langgraph-sandbox  # Run on HOST machine
```

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
    return "my_session_id"  # Implement your session management logic if needed

code_tool = make_code_sandbox_tool(session_manager=sm, session_key_fn=get_session_key)
dataset_tool = make_select_dataset_tool(session_manager=sm, fetch_fn=my_fetch, client=my_client)
export_tool = make_export_datasets_tool(session_manager=sm, session_key_fn=get_session_key)
list_tool = make_list_datasets_tool(session_manager=sm, session_key_fn=get_session_key)
```

> **Session Key Management:** The `session_key_fn` parameter is crucial for maintaining session isolation. Each unique session key gets its own container, so implement proper session management in your application (e.g., user ID, conversation ID, or thread ID). You can see in our [main.py](langgraph_sandbox/main.py) example that we did it by generating a random session key.

> **Note:** Notice that the `make_select_dataset_tool` expects the `fetch_fn` parameter to be a function that, given your dataset_id, returns the dataset **bytes** through your API client. 
>
> If in your implementation **you need to pass your API `client` to the `select_dataset` tool** (as we did in our [custom example](usage_examples\tmpfs_api\ex3_graph\tools.py)), you can do so by simply specifing `client` as an input parameter. It will be automatically wrapped without any needed changes. 

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

**Docker build failures:**
- Ensure you've run the setup process: `python -m langgraph_sandbox.setup`
- The Dockerfile expects `sandbox/repl_server.py` to exist in the build context
- If you get "COPY sandbox/repl_server.py: not found", run the setup command above

**Session Manager hanging/timeout issues:**
- This is expected when running SessionManager directly from the host machine
- The SessionManager is designed to run inside the Docker Compose environment
- For testing, use the full CLI workflow: `langgraph-sandbox`
- Container strategy requires proper network configuration (already set up in docker-compose.yml)

**Network connectivity issues:**
- Ensure Docker Compose is running: `docker compose up -d`
- Check containers are in the correct network: `docker network inspect langgraph-network`
- Verify container names follow the pattern: `sbox-{session_id}`

## Next Steps

- **Quotas**: Add per-session size limits and retention policies
- **Scalability**: Migrate to Postgres + S3/MinIO for production
- **Monitoring**: Add metrics and health checks

For more examples and detailed documentation, see the `usage_examples/` directory.