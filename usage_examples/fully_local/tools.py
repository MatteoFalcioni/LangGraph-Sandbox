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

def fetch_artifact_urls(session_id: str) -> List[Dict[str, str]]:
    """
    Fetch all artifacts for a given session and return their download URLs.
    Returns a list of dictionaries with artifact info and download URLs.
    """
    from src.artifacts.store import _resolve_paths
    import sqlite3
    
    paths = _resolve_paths()
    artifacts = []
    
    try:
        with sqlite3.connect(paths["db_path"]) as conn:
            # Get all artifacts linked to this session
            rows = conn.execute("""
                SELECT a.id, a.filename, a.mime, a.size, a.created_at
                FROM artifacts a
                JOIN links l ON a.id = l.artifact_id
                WHERE l.session_id = ?
                ORDER BY a.created_at DESC
            """, (session_id,)).fetchall()
            
            for row in rows:
                artifact_id, filename, mime, size, created_at = row
                try:
                    download_url = create_download_url(artifact_id)
                    artifacts.append({
                        "id": artifact_id,
                        "filename": filename or artifact_id,
                        "mime": mime,
                        "size": size,
                        "created_at": created_at,
                        "download_url": download_url
                    })
                except Exception as e:
                    print(f"Warning: Could not create URL for artifact {artifact_id}: {e}")
                    
    except Exception as e:
        print(f"Error fetching artifacts: {e}")
    
    return artifacts

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

