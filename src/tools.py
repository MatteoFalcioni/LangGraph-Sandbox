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
    
    result = run_python_in_docker(
        code,
        extra_ro_mounts = {os.path.abspath("llm_data") : "/data"},  # local_path: container_path
        timeout_s=20,
        mem_limit="512m",
        nano_cpus=1_000_000_000,
    )

    # Keep the message lean; include paths to artifacts you can serve from your API.
    payload = {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][-4000:],  # trim if huge
        "workdir": result["workdir"],
    }

    artifact = result["artifacts"]
    content = json.dumps(payload)

    tool_msg = ToolMessage(content=content, artifact=artifact, tool_call_id=tool_call_id)

    # Resume the graph with a ToolMessage
    return Command(
        update={
            "messages": [tool_msg]
        }
    )
