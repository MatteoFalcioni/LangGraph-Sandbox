# src/datasets/selector.py
from src.config import Config
from src.datasets.cache import write_ids


def select_datasets(cfg: Config, session_id: str) -> list[str]:
    """
    Fake implementation of a selector tool that allows the agent to select datasets to sync.
    Selected datasets are written to the session cache using the unified cache system.
    Implement your own for API_TMPFS mode.
    
    Args:
        cfg: Configuration object
        session_id: Session identifier
        
    Returns:
        List of selected dataset IDs
    """
    # Fake dataset selection - replace with your real implementation
    selected_datasets = ["dataset1", "dataset2", "dataset3"]
    
    # Write selected datasets to session cache
    cache_path = write_ids(cfg, session_id, selected_datasets)
    
    print(f"Selected datasets: {selected_datasets}")
    print(f"Cache written to: {cache_path}")
    
    return selected_datasets







