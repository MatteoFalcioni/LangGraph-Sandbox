# tools.py
import json
from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from src.config import Config
from src.sandbox.session_manager import SessionManager

CFG = Config.from_env()

# ---- session manager singleton (host-side) ----
_manager = SessionManager(
    image=CFG.sandbox_image,   # was "py-sandbox:latest"
)

def _get_session_key() -> str:
    return "conv"  # replace with your real thread/user id

# ---- args schema ----
class ExecuteCodeArgs(BaseModel):
    code: str = Field(description="Python code to execute in the sandbox.")
    tool_call_id: Annotated[str, InjectedToolCallId]
    model_config = ConfigDict(arbitrary_types_allowed=True)

@tool(
    name_or_callable="code_sandbox",
    description="Execute Python code in a session-pinned Docker sandbox. Returns stdout and any artifacts created under /session/artifacts.",
    args_schema=ExecuteCodeArgs,
)
def code_sandbox(
    code: Annotated[str, "Python code to run"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    sid = _get_session_key()
    _manager.start(sid)  # no-op if already running

    result = _manager.exec(sid, code, timeout=30)

    payload = {
        "stdout": result.get("stdout", ""),
        "stderr": result.get("error", "") or result.get("stderr", ""),
        "session_dir": result.get("session_dir", ""),
    }

    artifacts = result.get("artifacts", [])   # <-- removed trailing comma

    tool_msg = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        artifact=artifacts,
        tool_call_id=tool_call_id,
    )
    return Command(update={"messages": [tool_msg]})