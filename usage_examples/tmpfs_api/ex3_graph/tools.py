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
    name="list_catalog",
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

# the following function does not really load into sandbox: it lets the agent select datasets,
# which are written into cache by this tool.
# Then when we run the code executor tool it automatically syncs the dataset into sandbox
@tool(
    name="select_dataset",
    description="Select a dataset to load into sandbox as a parquet file."
)
async def select_dataset_tool(
    dataset_id: Annotated[str, "The dataset ID"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:

    with open(f"{FILENAME}", "wb") as f:
        f.write(dataset_id)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=json.dumps(bytes, ensure_ascii=False),
                    artifact=bytes,
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
    fetch_fn=get_dataset_bytes,
    session_manager=session_manager,
    session_key_fn=get_session_key
)

export_datasets_tool = make_export_datasets_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key
)
