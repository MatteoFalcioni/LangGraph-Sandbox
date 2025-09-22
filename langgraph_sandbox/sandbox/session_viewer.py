#!/usr/bin/env python3
"""
Session Viewer - Utility to inspect BIND mode session logs and metadata.

This script helps you explore what's been saved in your session directories
when using BIND mode, making the session-oriented debugging more useful.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any


def load_json_file(file_path: Path) -> Optional[Dict[Any, Any]]:
    """Safely load a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}")
        return None


def format_timestamp(timestamp: str) -> str:
    """Format ISO timestamp for display."""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return timestamp


def show_session_metadata(session_dir: Path) -> None:
    """Display session metadata."""
    metadata_file = session_dir / "session_metadata.json"
    metadata = load_json_file(metadata_file)
    
    if not metadata:
        print("No metadata found.")
        return
        
    print("=== SESSION METADATA ===")
    print(f"Session ID: {metadata.get('session_id', 'N/A')}")
    print(f"Created: {format_timestamp(metadata.get('created_at', 'N/A'))}")
    print(f"Last Used: {format_timestamp(metadata.get('last_used', 'N/A'))}")
    if 'stopped_at' in metadata:
        print(f"Stopped: {format_timestamp(metadata['stopped_at'])}")
    print(f"Container ID: {metadata.get('container_id', 'N/A')}")
    print(f"Host Port: {metadata.get('host_port', 'N/A')}")
    print(f"Storage Mode: {metadata.get('session_storage', 'N/A')}")
    print(f"Dataset Access: {metadata.get('dataset_access', 'N/A')}")
    print(f"Image: {metadata.get('image', 'N/A')}")
    print(f"Execution Count: {metadata.get('execution_count', 0)}")
    if 'final_execution_count' in metadata:
        print(f"Final Execution Count: {metadata['final_execution_count']}")
    print()


def show_session_log(session_dir: Path, limit: Optional[int] = None) -> None:
    """Display session execution log."""
    log_file = session_dir / "session.log"
    
    if not log_file.exists():
        print("No session log found.")
        return
        
    print("=== SESSION LOG ===")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    if limit:
        lines = lines[-limit:]
        
    for line in lines:
        try:
            entry = json.loads(line.strip())
            timestamp = format_timestamp(entry.get('timestamp', 'N/A'))
            event = entry.get('event', 'unknown')
            
            print(f"[{timestamp}] {event}")
            
            if event == "code_execution":
                success = "✓" if entry.get('success') else "✗"
                code_preview = entry.get('code', '')[:100]
                if len(entry.get('code', '')) > 100:
                    code_preview += "..."
                print(f"  {success} Code: {code_preview}")
                
                if entry.get('stdout'):
                    stdout_preview = entry['stdout'][:200]
                    if len(entry['stdout']) > 200:
                        stdout_preview += "..."
                    print(f"    Output: {stdout_preview}")
                    
                if entry.get('error'):
                    error_preview = entry['error'][:200]
                    if len(entry['error']) > 200:
                        error_preview += "..."
                    print(f"    Error: {error_preview}")
                    
            elif event == "artifacts_created":
                count = entry.get('artifact_count', 0)
                print(f"  Created {count} artifacts")
                for artifact in entry.get('artifacts', [])[:3]:  # Show first 3
                    print(f"    - {artifact.get('filename', 'unknown')} ({artifact.get('size_bytes', 0)} bytes)")
                if count > 3:
                    print(f"    ... and {count - 3} more")
                    
            elif event in ["session_started", "session_stopped"]:
                container_id = entry.get('container_id', 'N/A')
                print(f"  Container: {container_id}")
                
            print()
            
        except json.JSONDecodeError:
            print(f"Invalid JSON in log: {line.strip()}")
            print()


def show_python_state(session_dir: Path) -> None:
    """Display saved Python state."""
    state_file = session_dir / "python_state.json"
    state = load_json_file(state_file)
    
    if not state:
        print("No Python state found.")
        return
        
    print("=== PYTHON STATE ===")
    print(f"Captured: {format_timestamp(state.get('timestamp', 'N/A'))}")
    print()
    
    variables = state.get('variables', {})
    if variables:
        print("Variables:")
        for name, info in variables.items():
            var_type = info.get('type', 'unknown')
            value = info.get('value', 'N/A')
            print(f"  {name}: {var_type} = {value}")
        print()
    else:
        print("No variables found.")
        print()
        
    modules = state.get('imported_modules', [])
    if modules:
        print("Imported Modules:")
        for module in sorted(modules)[:20]:  # Show first 20
            print(f"  {module}")
        if len(modules) > 20:
            print(f"  ... and {len(modules) - 20} more")
        print()
    else:
        print("No imported modules found.")
        print()


def show_artifacts(session_dir: Path) -> None:
    """Display artifacts directory contents."""
    artifacts_dir = session_dir / "artifacts"
    
    if not artifacts_dir.exists():
        print("No artifacts directory found.")
        return
        
    print("=== ARTIFACTS ===")
    
    def show_dir_contents(path: Path, indent: int = 0) -> None:
        prefix = "  " * indent
        try:
            for item in sorted(path.iterdir()):
                if item.is_file():
                    size = item.stat().st_size
                    print(f"{prefix}{item.name} ({size} bytes)")
                elif item.is_dir():
                    print(f"{prefix}{item.name}/")
                    show_dir_contents(item, indent + 1)
        except PermissionError:
            print(f"{prefix}[Permission denied]")
    
    show_dir_contents(artifacts_dir)
    print()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python session_viewer.py <session_directory> [--limit N] [--no-state] [--no-artifacts]")
        print()
        print("Options:")
        print("  --limit N      Show only last N log entries (default: all)")
        print("  --no-state     Skip Python state display")
        print("  --no-artifacts Skip artifacts directory display")
        print()
        print("Examples:")
        print("  python session_viewer.py sessions/conv")
        print("  python session_viewer.py sessions/anon-4c2d63d6 --limit 10")
        sys.exit(1)
    
    session_dir = Path(sys.argv[1])
    
    if not session_dir.exists():
        print(f"Session directory not found: {session_dir}")
        sys.exit(1)
    
    # Parse options
    limit = None
    show_state = True
    show_artifacts_flag = True
    
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                print("Invalid limit value")
                sys.exit(1)
        elif arg == "--no-state":
            show_state = False
        elif arg == "--no-artifacts":
            show_artifacts_flag = False
    
    print(f"Session Directory: {session_dir.absolute()}")
    print("=" * 50)
    print()
    
    # Show all sections
    show_session_metadata(session_dir)
    show_session_log(session_dir, limit)
    
    if show_state:
        show_python_state(session_dir)
    
    if show_artifacts_flag:
        show_artifacts(session_dir)


if __name__ == "__main__":
    main()
