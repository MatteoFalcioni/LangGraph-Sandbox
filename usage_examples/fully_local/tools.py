from src.tool_factory.make_codexec_tool import make_code_sandbox_tool
from src.config import Config
from pathlib import Path
from src.artifacts.tokens import create_download_url
from src.artifacts.reader import get_metadata
from typing import List, Dict
import re

cfg = Config.from_env(env_file_path=Path("fully_local.env"))

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

# Artifact fetching is now handled by the general artifact system
# Import the function from the general location
from src.artifacts.reader import fetch_artifact_urls

def extract_artifact_references(text: str) -> List[str]:
    """
    Extract artifact references from text that might contain artifact IDs.
    Looks for patterns like 'art_...' or mentions of artifacts.
    """
    # Look for artifact ID patterns (assuming they start with 'art_')
    artifact_pattern = r'art_[a-zA-Z0-9_-]+'
    matches = re.findall(artifact_pattern, text)
    return list(set(matches))  # Remove duplicates

code_exec_tool = make_code_sandbox_tool(cfg=cfg, session_key_fn=get_session_key)

