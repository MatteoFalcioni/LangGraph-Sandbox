# Simple Sandbox Example - TMPFS_NONE Mode

This example demonstrates how to use the LangGraph Sandbox in **TMPFS_NONE** mode - a simple sandbox with no datasets that runs entirely in memory (tmpfs).

## Configuration

- **SessionStorage**: `TMPFS` (RAM, ephemeral)
- **DatasetAccess**: `NONE` (no datasets)
- **Use Case**: General-purpose code execution, algorithms, lightweight demos

## Setup

1. **Set your OpenAI API key** in `simple_sandbox.env`:
   ```env
   OPENAI_API_KEY=your_actual_api_key_here
   ```

2. **Run the example**:
   ```bash
   cd usage_examples/simple_sandbox
   python main.py
   ```

## What This Example Shows

- ✅ **Simple code execution** without any dataset dependencies
- ✅ **TMPFS storage** - everything runs in memory and is discarded when done
- ✅ **Artifact generation** - files saved to `/session/artifacts/` are automatically processed
- ✅ **Persistent session state** - variables and imports persist between tool calls
- ✅ **No external data dependencies** - perfect for algorithms, calculations, and demos

## Key Differences from fully_local

- **No dataset initialization** - removed `initialize_local_datasets()` call
- **No dataset cache clearing** - removed `clear_cache()` call
- **Simplified prompt** - removed dataset-specific instructions
- **TMPFS_NONE configuration** - uses memory storage with no datasets

## Example Usage

Once running, try these commands:

```
User: Calculate the factorial of 10
User: Create a simple plot of sin(x) from 0 to 2π and save it as an artifact
User: Generate a random dataset with 100 rows and 5 columns, then create a correlation matrix heatmap
User: Write a function to find prime numbers and test it with numbers 1-50
```

## Files Generated

- `simple_artifacts.db` - SQLite database for artifact metadata
- `simple_blobstore/` - Content-addressed storage for artifact files
- `sessions/` - Session data (minimal in TMPFS mode)

This example is perfect for general-purpose coding tasks that don't require external datasets!
