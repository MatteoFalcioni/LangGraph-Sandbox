# tools.py
import json, os
from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from .session_manager import SessionManager

# ---- session manager singleton (host-side) ----
# Mount datasets (RO) at /data inside the sandbox; keep per-session files in ./sessions/<sid>
# (state persists in RAM; files persist under /session)
_manager = SessionManager(
    image="py-sandbox:latest",
    datasets_path=os.path.abspath("src/llm_data"),
    session_root="sessions",
)

def _get_session_key() -> str:
    """
    Decide how to key sessions. Replace this with your thread/user id.
    For now, keep a single shared session named 'conv'.
    """
    return "conv"

# ---- args schema ----
class ExecuteCodeArgs(BaseModel):
    code: str = Field(description="Python code to execute in the sandbox.")
    # the following is needed since we are returning a Command object in the tool
    tool_call_id: Annotated[str, InjectedToolCallId]
    model_config = ConfigDict(arbitrary_types_allowed=True)

# tools.py (only the differences)
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

    result = _manager.exec(sid, code, timeout=30)  # {ok, stdout, error?, artifact_map, session_dir}

    payload = {
        "ok": result.get("ok", False),
        "stdout": (result.get("stdout") or "")[-4000:],
        "error": (result.get("error") or "")[-4000:] if not result.get("ok", False) else "",
        "session_key": sid,
        "session_dir": result.get("session_dir"),
        "artifact_count": len(result.get("artifact_map", [])),
        "hint": "Write files to /session/artifacts to persist & expose them.",
    }

    tool_msg = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        artifact=result.get("artifact_map", []),  # [{container, host}, ...]
        tool_call_id=tool_call_id,
    )

    return Command(update={"messages": [tool_msg]})

