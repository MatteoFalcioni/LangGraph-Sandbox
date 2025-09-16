# Fully Local Example - BIND Mode with Datasets

This example demonstrates how to use the LangGraph Sandbox in **BIND** mode with local dataset access - a full-featured sandbox that can work with real datasets mounted from the host filesystem.

## Configuration

- **SessionStorage**: `BIND` (persistent host filesystem)
- **DatasetAccess**: `LOCAL_RO` (read-only datasets from host)
- **Use Case**: Data analysis, machine learning, working with real datasets

## Setup

1. **Set your OpenAI API key** in `fully_local.env`:
   ```env
   OPENAI_API_KEY=your_actual_api_key_here
   ```

2. **Ensure datasets are available** in the `../../example_llm_data` directory (relative to the example folder)

3. **Run the example**:
   ```bash
   cd usage_examples/fully_local
   python main.py
   ```

## What This Example Shows

- ✅ **Full dataset access** - datasets mounted read-only under `/data/` in Parquet format
- ✅ **Persistent session storage** - files and state persist between conversations
- ✅ **Artifact generation** - files saved to `/session/artifacts/` are automatically processed
- ✅ **Dataset export capability** - modified datasets can be exported to host filesystem
- ✅ **Real data analysis** - work with actual datasets for meaningful analysis

## Key Features

- **Dataset initialization** - automatically mounts available datasets for the session
- **Dataset cache management** - clears cache when exiting to free up space
- **Export functionality** - save modified datasets to `./exports/modified_datasets/` with timestamps
- **Comprehensive prompt** - includes dataset-specific instructions and best practices

## Example Usage

Once running, try these commands:

```
User: What datasets are available in /data/?
User: Load the temperature dataset and create a time series plot
User: Analyze the air quality data and find correlations
User: Create a new dataset by combining two existing ones and export it
User: Generate a machine learning model using the available data
```

## Files Generated

- `example1_artifacts.db` - SQLite database for artifact metadata
- `example1_blobstore/` - Content-addressed storage for artifact files
- `sessions/` - Session data with persistent storage
- `exports/modified_datasets/` - Exported datasets with timestamp prefixes

## Available Datasets

The example includes several sample datasets in Parquet format:
- `attivita-elenco-acconciatori-barbieri-estetisti-tatuatori.parquet`
- `attivita-elenco-laboratori-alimentari.parquet`
- `centraline_qualita_aria_2025.parquet`
- `dataset-pubblicati.parquet`
- `statistical_zones.parquet`
- `storico_qualita_aria.parquet`
- `teatri-cinema.parquet`
- `temperatures.parquet`

## Key Differences from simple_sandbox

- **Dataset initialization** - calls `initialize_local_datasets()` to mount datasets
- **Dataset cache clearing** - calls `clear_cache()` when exiting
- **Enhanced prompt** - includes dataset-specific instructions and export guidance
- **BIND configuration** - uses persistent host filesystem storage
- **Export tool** - includes `export_datasets_tool` for saving modified data

This example is perfect for data science workflows, machine learning experiments, and any task requiring access to real datasets!
