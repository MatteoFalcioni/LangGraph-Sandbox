from langgraph_sandbox.tool_factory.make_tools import make_code_sandbox_tool, make_export_datasets_tool, make_select_dataset_tool
from langgraph_sandbox.config import Config
from langgraph_sandbox.artifacts.tokens import create_download_url
from langgraph_sandbox.artifacts.reader import get_metadata, fetch_artifact_urls
from opendata_api.helpers import get_dataset_bytes, list_catalog
from opendata_api.client import BolognaOpenData
from pathlib import Path
from langgraph_sandbox.sandbox.session_manager import SessionManager
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

select_dataset_tool = make_select_dataset_tool(
    session_manager=session_manager,
    session_key_fn=get_session_key,
    fetch_fn=get_dataset_bytes,
    client=client
)
