from src.tool_factory.make_codexec_tool import make_code_sandbox_tool
from src.config import Config
from pathlib import Path

cfg = Config.from_env(env_file_path=Path("fully_local.env"))
code_exec_tool = make_code_sandbox_tool(cfg=cfg)

