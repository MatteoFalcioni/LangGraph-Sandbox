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
    # The project root (where Dockerfile.sandbox template is)
    project_root = langgraph_sandbox_dir.parent
    current_dir = Path.cwd()
    
    # Files to copy from project root
    root_files_to_copy = [
        "Dockerfile.sandbox",
        "docker-compose.yml",
        "docker-compose.override.yml"
    ]
    
    # Files to copy from setup directory
    setup_files_to_copy = [
        "sandbox.env.example"
    ]
    
    # Directories to copy
    dirs_to_copy = [
        "sandbox"
    ]
    
    print("Setting up LangGraph Sandbox...")
    
    # Copy files from project root
    for filename in root_files_to_copy:
        source = project_root / filename
        destination = current_dir / filename
        
        if source.exists():
            # Skip if source and destination are the same file (already in project root)
            if source.resolve() == destination.resolve():
                print(f"✓ {filename} already exists in current directory")
            else:
                shutil.copy2(source, destination)
                print(f"✓ Copied {filename}")
        else:
            print(f"✗ Warning: {filename} not found in project root")
    
    # Copy files from setup directory
    for filename in setup_files_to_copy:
        source = package_dir / filename
        destination = current_dir / filename
        
        if source.exists():
            # Skip if source and destination are the same file (already in project root)
            if source.resolve() == destination.resolve():
                print(f"✓ {filename} already exists in current directory")
            else:
                shutil.copy2(source, destination)
                print(f"✓ Copied {filename}")
        else:
            print(f"✗ Warning: {filename} not found in package")
    
    for dirname in dirs_to_copy:
        source = langgraph_sandbox_dir / dirname
        destination = current_dir / dirname
        
        if source.exists():
            # Skip if source and destination are the same directory (already in project root)
            if source.resolve() == destination.resolve():
                print(f"✓ {dirname}/ directory already exists in current directory")
            else:
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(source, destination)
                print(f"✓ Copied {dirname}/ directory")
        else:
            print(f"✗ Warning: {dirname}/ directory not found in package")
    
    print("\nSetup complete! Next steps:")
    print("  # 1. Copy and customize config:")
    print("  cp sandbox.env.example sandbox.env")
    print("  # 2. Choose your deployment:")
    print("  # Docker Compose (recommended):")
    print("  docker-compose up -d")
    print("  langgraph-sandbox  # Run this command on the HOST machine")
    print("  # OR Traditional Docker:")
    print("  docker build -t sandbox:latest -f Dockerfile.sandbox .")
    print("  langgraph-sandbox  # Run this command on the HOST machine")


if __name__ == "__main__":
    setup_sandbox()