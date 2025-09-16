# BIND Mode Session Logging

This document describes the enhanced BIND mode functionality that makes session directories much more useful for debugging and inspection.

## Overview

In BIND mode, the session directory (`./sessions/<session_id>`) now contains much more than just empty artifacts directories. The system automatically saves:

1. **Session execution logs** - Complete history of code execution
2. **Session metadata** - Container info, timestamps, execution stats
3. **Python state snapshots** - Variables and imports for debugging
4. **Artifacts directory** - Files created during execution (before ingestion)

## Files Created

### `session.log`
A line-delimited JSON file containing the complete execution history:

```json
{"timestamp": "2024-01-15T10:30:00", "event": "session_started", "container_id": "abc123", "host_port": 9001}
{"timestamp": "2024-01-15T10:30:15", "event": "code_execution", "code": "import pandas as pd\nprint('Hello')", "success": true, "stdout": "Hello\n"}
{"timestamp": "2024-01-15T10:30:20", "event": "artifacts_created", "artifact_count": 1, "artifacts": [{"id": "art_123", "filename": "plot.png", "size_bytes": 15432}]}
{"timestamp": "2024-01-15T10:35:00", "event": "session_stopped", "container_id": "abc123"}
```

### `session_metadata.json`
Session configuration and statistics:

```json
{
  "session_id": "conv",
  "created_at": "2024-01-15T10:30:00",
  "last_used": "2024-01-15T10:35:00",
  "container_id": "abc123",
  "host_port": 9001,
  "session_storage": "BIND",
  "dataset_access": "API",
  "image": "sandbox:latest",
  "execution_count": 5,
  "stopped_at": "2024-01-15T10:35:00",
  "final_execution_count": 5
}
```

### `python_state.json`
Current Python state (variables and imports):

```json
{
  "timestamp": "2024-01-15T10:35:00",
  "variables": {
    "df": {
      "type": "DataFrame",
      "value": "   A  B  C\n0  1  2  3\n1  4  5  6"
    },
    "x": {
      "type": "list",
      "value": "[1, 2, 3, 4, 5]"
    }
  },
  "imported_modules": ["pandas", "numpy", "matplotlib.pyplot"]
}
```

### `artifacts/`
Directory containing files created during execution (before they're ingested into the artifact store).

## Using the Session Viewer

A utility script is provided to easily inspect session data:

```bash
# View all session information
python src/sandbox/session_viewer.py sessions/<session_id>

# View only last 10 log entries
python src/sandbox/session_viewer.py sessions/<session_id> --limit 10

# Skip Python state and artifacts display
python src/sandbox/session_viewer.py sessions/<session_id> --no-state --no-artifacts
```

## Benefits for Debugging

### 1. **Complete Execution History**
- See exactly what code was executed and when
- Track success/failure of each execution
- View output and error messages
- Understand the sequence of operations

### 2. **Session State Inspection**
- See what variables were created
- Check which modules were imported
- Understand the Python environment state
- Debug variable values and types

### 3. **Artifact Tracking**
- See what files were created during execution
- Track artifact creation timing
- Inspect files before they're ingested
- Debug file generation issues

### 4. **Container Information**
- Track container lifecycle
- See port mappings and configuration
- Debug container-related issues
- Monitor resource usage patterns

## Example Session Directory Structure

```
sessions/conv/
├── session.log                    # Execution history
├── session_metadata.json          # Session info and stats
├── python_state.json             # Current Python state
└── artifacts/                    # Files created during execution
    ├── hello.txt                # these are automatically ingested and deleted after
    ├── plot.png
    └── data.csv
```

## When to Use BIND Mode

BIND mode is now particularly useful for:

- **Development and debugging** - Full visibility into session state
- **Troubleshooting** - Complete execution logs and state snapshots
- **Learning and exploration** - See what happens during code execution
- **Audit trails** - Track all operations performed in a session
- **State inspection** - Debug variable values and imports

## Performance Considerations

- Logging adds minimal overhead (only in BIND mode)
- Python state saving runs after each execution
- Files are written asynchronously to avoid blocking execution
- State snapshots are truncated to prevent huge files

## Migration from TMPFS

If you're currently using TMPFS mode and want the debugging benefits:

1. Change `session_storage` to `SessionStorage.BIND` in your configuration
2. Existing sessions will continue to work
3. New sessions will automatically get logging
4. Use the session viewer to inspect session data

The logging system is designed to be non-intrusive and only activates in BIND mode, so it won't affect TMPFS performance.
