# src/tools/factory.py
from __future__ import annotations

import json
from typing import Callable, Optional

from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from src.config import Config
from src.sandbox.session_manager import SessionManager, DatasetAccess
from src.datasets.sync import sync_datasets
from src.datasets.cache import read_ids, read_pending_ids


def _default_get_session_key() -> str:
    return "conv"  # TODO: user/thread id


def make_code_sandbox_tool(
    *,
    session_manager: SessionManager,
    session_key_fn: Callable[[], str] = _default_get_session_key,
    fetch_fn: Optional[Callable[[str], bytes]] = None,
    name: str = "code_sandbox",
    description: str = (
        "Execute Python code in a session-pinned Docker sandbox. "
        "Returns stdout and any artifacts from /session/artifacts. "
        "Always use print(...) to show results."
    ),
    timeout_s: int = 30,
) -> Callable:
    """
    Factory that returns a LangChain Tool for executing code inside the sandbox,
    with optional per-run dataset sync. The provided `fetch_fn` is used when
    datasets must be staged via API.

    Usage:
        session_manager = SessionManager(...)
        code_sandbox = make_code_sandbox_tool(
            session_manager=session_manager,
            session_key_fn=lambda: "conv",
            fetch_fn=my_fetch_dataset,  # def my_fetch_dataset(ds_id) -> bytes
        )
    """

    class ExecuteCodeArgs(BaseModel):
        code: str = Field(description="Python code to execute in the sandbox.")
        tool_call_id: Annotated[str, InjectedToolCallId]
        model_config = ConfigDict(arbitrary_types_allowed=True)

    # The implementation closes over session_manager, session_key_fn, fetch_fn
    def _impl(
        code: Annotated[str, "Python code to run"],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        sid = session_key_fn()
        session_manager.start(sid)

        # Initialize resolved datasets list
        resolved = []
        
        # Only sync datasets in API mode (when using API dataset access)
        if session_manager.dataset_access == DatasetAccess.API:
            # raise an error if fetch_fn is not provided
            if fetch_fn is None:
                raise ValueError("fetch_fn must be provided when using API dataset access")

            # Read PENDING dataset IDs from session cache (created by select_datasets tool)
            # Create a minimal config for read_pending_ids
            from src.config import Config
            cfg = Config.from_env()
            datasets = read_pending_ids(cfg, sid)
            
            if datasets:
                # Get container reference and sync datasets
                container = session_manager.container_for(sid)
                resolved = sync_datasets(
                    cfg=cfg,
                    session_id=sid,
                    container=container,
                    ds_ids=datasets,
                    fetch_fn=fetch_fn,  
                )
        # NONE and LOCAL_RO modes don't need dataset syncing

        result = session_manager.exec(sid, code, timeout=timeout_s)

        artifacts = result.get("artifacts", [])
        
        # Include artifact information in the content for the agent
        artifact_info = ""
        if artifacts:
            artifact_info = "\n\n📁 Generated Artifacts:\n"
            for artifact in artifacts:
                filename = artifact.get('name', 'unknown')
                size = artifact.get('size', 0)
                mime = artifact.get('mime', 'unknown')
                download_url = artifact.get('url', '')
                artifact_info += f"  • {filename} ({mime}, {size} bytes)\n"
                if download_url:
                    artifact_info += f"    Download: {download_url}\n"
            artifact_info += "\n"
        
        payload = {
            "stdout": result.get("stdout", ""),
            "stderr": result.get("error", "") or result.get("stderr", ""),
            "session_dir": result.get("session_dir", ""),
            "datasets": resolved,  # each item has id/path_in_container/mode/staged
        }

        # Combine stdout with artifact information
        combined_content = result.get("stdout", "") + artifact_info + json.dumps(payload, ensure_ascii=False, indent=2)

        tool_msg = ToolMessage(
            content=combined_content,
            artifact=artifacts,
            tool_call_id=tool_call_id,
        )
        return Command(update={"messages": [tool_msg]})

    # Return a LangChain Tool by applying the decorator at factory time
    return tool(
        name_or_callable=name,
        description=description,
        args_schema=ExecuteCodeArgs,
    )(_impl)


def make_export_datasets_tool(
    *,
    session_manager: SessionManager,
    session_key_fn: Callable[[], str] = _default_get_session_key,
    name: str = "export_datasets",
    description: str = (
        "Export a modified dataset from /session/data/ to ./exports/modified_datasets/ "
        "with timestamp prefix. Use this to save processed or modified datasets "
        "from the sandbox to the host filesystem."
    ),
) -> Callable:
    """
    Create a tool for exporting files from the container's /session/data/ directory.
    
    Parameters:
        session_manager: SessionManager instance to use for container operations
        session_key_fn: Function to get current session key
        name: Tool name
        description: Tool description
        
    Returns:
        LangChain tool function
    """
    
    class ExportDatasetArgs(BaseModel):
        container_path: Annotated[str, Field(description="Path to file inside container (e.g., '/session/data/modified_data.parquet')")]
        tool_call_id: Annotated[str, InjectedToolCallId]
        model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def _impl(
        container_path: Annotated[str, "Path to file inside container (e.g., '/session/data/modified_data.parquet')"], 
        tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> Command:
        """Export a file from container to host filesystem."""
        session_key = session_key_fn()
        
        # Call the session manager's export method
        result = session_manager.export_file(session_key, container_path)
        
        if result["success"]:
            tool_msg = ToolMessage(
                content=(
                    f"Successfully exported dataset:\n"
                    f"  Container path: {container_path}\n"
                    f"  Host path: {result['host_path']}\n"
                    f"  Download URL: {result['download_url']}"
                ),
                tool_call_id=tool_call_id,
            )
        else:
            tool_msg = ToolMessage(
                content=f"Failed to export dataset: {result['error']}",
                tool_call_id=tool_call_id,
            )
        
        return Command(update={"messages": [tool_msg]})
    
    # Return a LangChain Tool by applying the decorator at factory time
    return tool(
        name_or_callable=name,
        description=description,
        args_schema=ExportDatasetArgs,
    )(_impl)
