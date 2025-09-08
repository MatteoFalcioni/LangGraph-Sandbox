# tools.py
import json
from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from .sandbox_runner import run_python_in_docker
import os

# ---- args schema ----
class ExecuteCodeArgs(BaseModel):
    code: str = Field(description="Python code to execute in the sandbox.")
    # the following is needed since we are returning a Command object in the tool
    tool_call_id: Annotated[str, InjectedToolCallId]
    model_config = ConfigDict(arbitrary_types_allowed=True)

@tool(
    name_or_callable="code_sandbox",
    description="Execute untrusted Python code in an ephemeral Docker sandbox. Returns stdout and any artifacts created in /work/artifacts.",
    args_schema=ExecuteCodeArgs,
)
def code_sandbox(
    code: Annotated[str, "Python code to run"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    
    session_id = "conv"  # better: pull from graph state/checkpoint (e.g., run_id/user_id)
    
    result = run_python_in_docker(
        code,
        extra_ro_mounts = {os.path.abspath("src/llm_data/") : "/data"},  # local_path: container_path
        session_id=session_id,                 # <— enables /session
        timeout_s=20,
        mem_limit="512m",
        nano_cpus=1_000_000_000,
        persist_root="outputs",  # promoted artifacts end up here
    )

    # Keep the message lean; include paths to artifacts - you can serve them from your API.
    payload = {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][-4000:],  # trim if large
        "stderr": result["stderr"][-4000:],  # trim if large
        "persist_dir": result["persist_dir"],
        "run_id": result["run_id"],
        "artifact_map_count": len(result["artifact_map"]),
    }

    # Put the full map in ToolMessage.artifact (structured)
    tool_msg = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        artifact=result["artifact_map"],           # [{container, host}, ...]
        tool_call_id=tool_call_id,
    )

    # Return result as a ToolMessage
    return Command(
        update={
            "messages": [tool_msg]
        }
    )
