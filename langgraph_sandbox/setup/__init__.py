"""
Setup utilities for LangGraph Sandbox
"""

import os
import shutil
from pathlib import Path


def setup_sandbox():
    """
    Set up the sandbox environment by copying necessary files to the current directory.
    This allows users to run Docker commands after pip installation.
    """
    # Get the directory where this package is installed
    package_dir = Path(__file__).parent
    # The sandbox directory is in the parent langgraph_sandbox directory
    langgraph_sandbox_dir = package_dir.parent
    current_dir = Path.cwd()
    
    # Files to copy
    files_to_copy = [
        "Dockerfile",
        "docker.env", 
        "example.env"
    ]
    
    # Directories to copy
    dirs_to_copy = [
        "sandbox"
    ]
    
    print("Setting up LangGraph Sandbox...")
    
    for filename in files_to_copy:
        source = package_dir / filename
        destination = current_dir / filename
        
        if source.exists():
            shutil.copy2(source, destination)
            print(f"✓ Copied {filename}")
        else:
            print(f"✗ Warning: {filename} not found in package")
    
    for dirname in dirs_to_copy:
        source = langgraph_sandbox_dir / dirname
        destination = current_dir / dirname
        
        if source.exists():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
            print(f"✓ Copied {dirname}/ directory")
        else:
            print(f"✗ Warning: {dirname}/ directory not found in package")
    
    print("\nSetup complete! You can now run:")
    print("  docker build -t sandbox:latest -f Dockerfile .")
    print("  docker run -p 8000:8000 sandbox:latest")


if __name__ == "__main__":
    setup_sandbox()