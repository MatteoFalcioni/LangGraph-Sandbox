# TMPFS API Example - TMPFS_API Mode

This example demonstrates how to use the LangGraph Sandbox in **TMPFS_API** mode - a sandbox that fetches datasets dynamically via API calls and caches them in memory (tmpfs).

## Configuration

- **SessionStorage**: `TMPFS` (RAM, ephemeral)
- **DatasetAccess**: `API` (datasets fetched on-demand via API)
- **Use Case**: Dynamic dataset access, API-based data sources, cloud datasets

## Setup

1. **Set your OpenAI API key** in `tmpfs_api.env`:
   ```env
   OPENAI_API_KEY=your_actual_api_key_here
   ```

2. **Configure your custom fetch function** in `custom_fetch_functions.py`:
   - Implement your dataset fetching logic
   - Define how datasets are retrieved from your API sources
   - Handle authentication, pagination, and data transformation

3. **Run the example**:
   ```bash
   cd usage_examples/tmpfs_api
   python main.py
   ```

## What This Example Shows

- ✅ **Dynamic dataset fetching** - datasets are fetched on-demand via API calls
- ✅ **TMPFS caching** - fetched datasets are cached in memory for performance
- ✅ **Artifact generation** - files saved to `/session/artifacts/` are automatically processed
- ✅ **Persistent session state** - variables and imports persist between tool calls
- ✅ **API-based data sources** - perfect for cloud datasets, external APIs, and dynamic content

## Key Features

- **On-demand fetching** - datasets are downloaded only when first accessed
- **Memory caching** - subsequent accesses use cached data for speed
- **Custom fetch functions** - implement your own dataset retrieval logic
- **Export functionality** - save modified datasets to `./exports/modified_datasets/` with timestamps
- **Comprehensive prompt** - includes API-specific instructions and best practices

## Example Usage

Once running, try these commands:

```
User: Search for datasets about air quality
User: Select the "centraline_qualita_aria_2025" dataset
User: What datasets are available in /session/data/?
User: Load the air quality dataset and create a visualization
User: Analyze the data and find correlations
User: Create a new dataset by combining API data and export it
User: Generate a machine learning model using the fetched data
```

## Files Generated

- `tmpfs_api_artifacts.db` - SQLite database for artifact metadata
- `tmpfs_api_blobstore/` - Content-addressed storage for artifact files
- `sessions/` - Session data (minimal in TMPFS mode)
- `exports/modified_datasets/` - Exported datasets with timestamp prefixes

## Custom Fetch Functions

The `custom_fetch_functions.py` file is where you implement your dataset fetching logic. This file should contain:

- Functions to fetch datasets from your API sources
- Data transformation logic (e.g., JSON to Parquet)
- Authentication handling
- Error handling and retry logic
- Dataset metadata management

Example structure:
```python
def fetch_dataset(dataset_name: str) -> str:
    """
    Fetch a dataset from your API source.
    
    Args:
        dataset_name: Name of the dataset to fetch
        
    Returns:
        Path to the cached dataset file
    """
    # Your implementation here
    pass

def list_available_datasets() -> List[str]:
    """
    List all available datasets from your API source.
    
    Returns:
        List of dataset names
    """
    # Your implementation here
    pass
```

## Key Differences from Other Examples

- **API dataset access** - uses `DATASET_ACCESS=API` configuration
- **Custom fetch functions** - requires implementation of dataset fetching logic
- **Dynamic loading** - datasets are fetched on-demand, not pre-mounted
- **Memory caching** - datasets are cached in tmpfs for performance
- **No dataset initialization** - removed `initialize_local_datasets()` call
- **Enhanced prompt** - includes API-specific instructions and caching guidance

## Performance Considerations

- **First access**: May be slower due to API fetch time
- **Subsequent access**: Fast due to tmpfs caching
- **Memory usage**: Cached datasets consume tmpfs space (1GB available)
- **Network dependency**: Requires internet connection for dataset fetching

This example is perfect for working with cloud datasets, external APIs, and any scenario where datasets need to be fetched dynamically!
