#!/usr/bin/env python3
"""
LangGraph Sandbox - Main Entry Point

This is the main entry point for the LangGraph Sandbox package.
It redirects to the simple sandbox example by default.

Usage:
    langgraph-sandbox                    # Run simple sandbox
    python main.py                       # Run simple sandbox
    python main.py --help                # Show help
"""

import sys
import os
from pathlib import Path

def main():
    """Main entry point that redirects to the simple sandbox example."""
    
    # Add the usage_examples/simple_sandbox directory to Python path
    simple_sandbox_dir = Path(__file__).parent / "usage_examples" / "simple_sandbox"
    if str(simple_sandbox_dir) not in sys.path:
        sys.path.insert(0, str(simple_sandbox_dir))
    
    # Change to the simple sandbox directory so relative paths work
    os.chdir(simple_sandbox_dir)
    
    # Import and run the simple sandbox main
    try:
        # Import the simple sandbox main module and execute it
        import importlib.util
        main_file = simple_sandbox_dir / "main.py"
        
        spec = importlib.util.spec_from_file_location("simple_main", main_file)
        simple_main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(simple_main)
        
        # Execute the main function from the simple sandbox
        if hasattr(simple_main, 'main'):
            simple_main.main()
        else:
            # If no main function, execute the module directly
            exec(open(main_file).read())
    except Exception as e:
        print(f"Error running simple sandbox: {e}")
        print("Make sure you're running from the LangGraph-Sandbox root directory.")
        print("Also ensure Docker is running and the sandbox image is built.")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()