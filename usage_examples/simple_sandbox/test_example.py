#!/usr/bin/env python3
"""
Simple test script to verify the simple_sandbox example works correctly.
This script tests the basic functionality without requiring user interaction.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Set environment variables before any imports
os.environ["ARTIFACTS_DB_PATH"] = str(Path("simple_artifacts.db").resolve())
os.environ["BLOBSTORE_DIR"] = str(Path("simple_blobstore").resolve())

from dotenv import load_dotenv
from src.config import Config
from src.artifacts.store import ensure_artifact_store
from tools import set_session_id
from simple_ex_graph import get_builder
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

def test_simple_sandbox():
    """Test the simple sandbox example."""
    print("🧪 Testing Simple Sandbox Example (TMPFS_NONE mode)")
    print("=" * 60)
    
    # Load environment
    env = load_dotenv("simple_sandbox.env")
    if env:
        print("✅ Loaded simple_sandbox.env")
    else:
        print("❌ No .env file found")
        return False
    
    # Initialize artifact store
    try:
        ensure_artifact_store()
        print("✅ Artifact store initialized")
    except Exception as e:
        print(f"❌ Failed to initialize artifact store: {e}")
        return False
    
    # Load configuration
    try:
        cfg = Config.from_env(env_file_path=Path("simple_sandbox.env"))
        print(f"✅ Configuration loaded - SessionStorage: {cfg.session_storage}, DatasetAccess: {cfg.dataset_access}")
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return False
    
    # Test session ID setup
    try:
        test_session_id = "test-session-123"
        set_session_id(test_session_id)
        print(f"✅ Session ID set: {test_session_id}")
    except Exception as e:
        print(f"❌ Failed to set session ID: {e}")
        return False
    
    # Test graph creation
    try:
        builder = get_builder()
        memory = InMemorySaver()
        graph = builder.compile(checkpointer=memory)
        print("✅ LangGraph compiled successfully")
    except Exception as e:
        print(f"❌ Failed to create graph: {e}")
        return False
    
    # Test simple execution
    try:
        print("\n🔬 Testing simple code execution...")
        init = {"messages": [HumanMessage(content="Calculate 2 + 2 and print the result")]}
        result = graph.invoke(init, config={"configurable": {"thread_id": test_session_id}})
        print("✅ Code execution test completed")
        print(f"   Response: {result['messages'][-1].content[:100]}...")
    except Exception as e:
        print(f"❌ Code execution failed: {e}")
        return False
    
    print("\n🎉 All tests passed! Simple sandbox is working correctly.")
    print("\nTo run the interactive version:")
    print("  python main.py")
    return True

if __name__ == "__main__":
    success = test_simple_sandbox()
    sys.exit(0 if success else 1)
