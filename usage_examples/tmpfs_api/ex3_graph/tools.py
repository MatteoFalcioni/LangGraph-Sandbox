from src.tool_factory.make_tools import make_code_sandbox_tool, make_export_datasets_tool
from src.config import Config
from src.artifacts.tokens import create_download_url
from src.artifacts.reader import get_metadata, fetch_artifact_urls
from opendata_api.helpers import get_dataset_bytes, list_catalog
from opendata_api.client import BolognaOpenData
from pathlib import Path
from src.sandbox.session_manager import SessionManager
from typing import List, Dict
import re
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage
import json

cfg = Config.from_env(env_file_path=Path("tmpfs_api.env"))

# Global variable to store the current session ID
_current_session_id = None

def get_session_key():
    """Get session key from the conversation context."""
    global _current_session_id
    if _current_session_id is None:
        # Fallback to a default if not set
        return "conv"
    return _current_session_id

def set_session_id(session_id: str):
    """Set the current session ID for the code execution tool."""
    global _current_session_id
    _current_session_id = session_id


def extract_artifact_references(text: str) -> List[str]:
    """
    Extract artifact references from text that might contain artifact IDs.
    Looks for patterns like 'art_...' or mentions of artifacts.
    """
    # Look for artifact ID patterns (assuming they start with 'art_')
    artifact_pattern = r'art_[a-zA-Z0-9_-]+'
    matches = re.findall(artifact_pattern, text)
    return list(set(matches))  # Remove duplicates


client = BolognaOpenData()  # close it in main then

@tool(
    name_or_callable="list_catalog",
    description="Search the dataset catalog with a keyword."
)
async def list_catalog_tool(
    q: Annotated[str, "The dataset search keyword"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    res = await list_catalog(client=client, q=q, limit=15)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=json.dumps(res, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )

@tool(
    name_or_callable="select_dataset",
    description="Select a dataset to load into sandbox as a parquet file. This will fetch and stage the dataset immediately."
)
async def select_dataset_tool(
    dataset_id: Annotated[str, "The dataset ID"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    from src.datasets.cache import add_entry, DatasetStatus, get_entry_status
    from src.datasets.sync import load_pending_datasets
    
    session_id = get_session_key()
    
    # Check if dataset is already loaded
    current_status = get_entry_status(cfg, session_id, dataset_id)
    if current_status == DatasetStatus.LOADED:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Dataset '{dataset_id}' is already loaded and available in the sandbox.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    
    # Add the dataset to cache with PENDING status
    cache_path = add_entry(cfg, session_id, dataset_id, status=DatasetStatus.PENDING)
    
    try:
        # Start the session if not already started
        session_manager.start(session_id)
        
        # Create a wrapper function for get_dataset_bytes that only takes dataset_id
        async def fetch_dataset_wrapper(ds_id: str) -> bytes:
            return await get_dataset_bytes(client, ds_id)
        
        # Load the dataset into the sandbox
        container = session_manager.container_for(session_id)
        
        loaded_datasets = await load_pending_datasets(
            cfg=cfg,
            session_id=session_id,
            container=container,
            fetch_fn=fetch_dataset_wrapper,
            ds_ids=[dataset_id],
        )
        
        if loaded_datasets:
            dataset_info = loaded_datasets[0]
            path_in_container = dataset_info["path_in_container"]
            
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Dataset '{dataset_id}' successfully loaded into sandbox at {path_in_container}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
        else:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Failed to load dataset '{dataset_id}' - no datasets were loaded",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
            
    except Exception as e:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Failed to load dataset '{dataset_id}': {str(e)}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )


# Create single session manager instance
session_manager = SessionManager(
    image=cfg.sandbox_image,
    session_storage=cfg.session_storage,
    dataset_access=cfg.dataset_access,
    datasets_path=cfg.datasets_host_ro,
    session_root=cfg.sessions_root,
    tmpfs_size=cfg.tmpfs_size_mb,
)

# Create tools using the shared session manager
code_exec_tool = make_code_sandbox_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key
)

export_datasets_tool = make_export_datasets_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key
)
