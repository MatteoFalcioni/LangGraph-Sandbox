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
from src.sandbox.session_manager import SessionManager
from src.datasets.sync import sync_datasets


def _default_get_session_key() -> str:
    return "conv"  # TODO: user/thread id

def make_code_sandbox_tool(
    *,
    cfg: Config = Config.from_env(),
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
    datasets must be staged via API_TMPFS.

    Usage:
        CFG = Config.from_env()
        code_sandbox = make_code_sandbox_tool(
            cfg=CFG,
            session_key_fn=lambda: "conv",
            fetch_fn=my_fetch_dataset,  # def my_fetch_dataset(ds_id) -> bytes
        )
    """

    # Build a session manager bound to this cfg
    manager = SessionManager(
        image=cfg.sandbox_image,
        session_storage=cfg.session_storage,
        dataset_access=cfg.dataset_access,
        datasets_path=cfg.datasets_host_ro,
        session_root=cfg.sessions_root,
        tmpfs_size=cfg.tmpfs_size_mb,
    )

    class ExecuteCodeArgs(BaseModel):
        code: str = Field(description="Python code to execute in the sandbox.")
        tool_call_id: Annotated[str, InjectedToolCallId]
        model_config = ConfigDict(arbitrary_types_allowed=True)

    # The implementation closes over cfg, manager, session_key_fn, fetch_fn
    def _impl(
        code: Annotated[str, "Python code to run"],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        sid = session_key_fn()
        manager.start(sid)

        # how can i inspect if there are any datasets to put in sandbox? 
        # if tmpfs -> i fetch with the fetcher
        # if ro, i list the datasets and sync -> actually these can be synced once at the beginning and that's it, they are static!
        # so i only use fetch_fn and sync behaviour in this tool when the mode is API - dont even care about tmpfs,  it's the
        # API mode that requires syncing

        # so the idea is, in API mode, at each run we have a list of datasets to load, if any (chosen by the agent at another step)
        
        # also, since we do not want to pass dataset_ids as a parameter, we put a get_datasets function 
        # the idea is that we'll have another tool (select_datasets) through which the agent can select which datasets to load. 
        # these get written to a file, and then the sync happens from that file

        if cfg.uses_api_staging: 

            resolved = []
            # the user will need to implement this - so basically we shifted the problem to implement another function from the user...
            # but i guess i cannot do otherwise, unless i want to pass dataset_ids as a parameter to the tool
            # which is not ideal since the agent would need to call the tool with a list of datasets each time - error prone
            datasets = get_datasets_to_sync(filename="datasets_to_sync.txt")  # implement this function to read from a file

            if datasets:
                container = manager.container_for(sid)  # ensure SessionManager exposes this - right now it doesn't
                resolved = sync_datasets(
                    cfg=cfg,
                    session_id=sid,
                    container=container,
                    ds_ids=datasets,
                    fetch_fn=fetch_fn,  
                )

        result = manager.exec(sid, code, timeout=timeout_s)

        payload = {
            "stdout": result.get("stdout", ""),
            "stderr": result.get("error", "") or result.get("stderr", ""),
            "session_dir": result.get("session_dir", ""),
            "datasets": resolved,  # each item has id/path_in_container/mode/staged
        }
        artifacts = result.get("artifacts", [])

        tool_msg = ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
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
