# tools.py
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from src.config import Config
from src.sandbox.session_manager import SessionManager
from src.datasets.sync import sync_datasets

# get configs from .env file
CFG = Config.from_env()

# ---- session manager init ----
_manager = SessionManager(
    image=CFG.sandbox_image,   
    session_storage=CFG.session_storage,
    dataset_access=CFG.dataset_access,
    datasets_path=CFG.datasets_host_ro,
    session_root=CFG.sessions_root,
    tmpfs_size=CFG.tmpfs_size_mb,
)

def _get_session_key() -> str:
    return "conv"  # TODO: replace with real thread/user id

# helper function called inside the tool
def code_executor(code : str, dataset_ids: List[str] = []) -> Dict:
    """
    This functions syncs datasets to the current docker sandbox session, 
    then executes the provided code inside the sandbox, and returns the output.
    """
    sid = _get_session_key()
    _manager.start(sid)  # no-op if already running
    sync_result = {"sync": "No datasets synced."} 

    if dataset_ids:
        # sync
        sync_result = sync_datasets(
            cfg=CFG, 
            session_id=sid, 
            fetch_fn=fetch_fn,
            container=_manager.container_for(sid),  # does container_for exist? 
            force_refresh=False, 
            ds_ids=CFG.datasets
            )

    code_result = _manager.exec(sid, code, timeout=30)

    return code_result, sync_result


# ---- args schema for the actual tool ----
class ExecuteCodeArgs(BaseModel):
    code: str = Field(description="Python code to execute in the sandbox.")
    tool_call_id: Annotated[str, InjectedToolCallId]
    model_config = ConfigDict(arbitrary_types_allowed=True)

# the actual tool
@tool(
    name_or_callable="code_executor",
    description="Execute Python code in a session-pinned Docker sandbox. Returns stdout and any artifacts created under /session/artifacts." \
    "Always use `print(...)` when you want to print something, never rely on implicit return values like `df.head()`.",
    args_schema=ExecuteCodeArgs,
)
def code_sandbox(
    code: Annotated[str, "Python code to run"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    
    code_result, sync_result = code_executor(code)    # syncs datasets and executes the code

    payload = {
        "stdout": code_result.get("stdout", ""),
        "stderr": code_result.get("error", "") or code_result.get("stderr", ""),
        "session_dir": code_result.get("session_dir", ""),
    }

    artifacts = code_result.get("artifacts", [])   

    # return sync result in artifact maybe

    tool_msg = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        artifact=artifacts,
        tool_call_id=tool_call_id,
    )
    return Command(update={"messages": [tool_msg]})

