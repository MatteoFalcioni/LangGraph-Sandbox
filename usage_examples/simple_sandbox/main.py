# Set environment variables to use simple database and blobstore
# This must be done before any imports that use the artifact system
import os
import sys
from pathlib import Path

# Add the project root to Python path so we can import from src
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

os.environ["ARTIFACTS_DB_PATH"] = str(Path("simple_artifacts.db").resolve())
os.environ["BLOBSTORE_DIR"] = str(Path("simple_blobstore").resolve())

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI
from langgraph_sandbox.artifacts.store import ensure_artifact_store
from langgraph_sandbox.artifacts.api import router as artifacts_router

from langgraph_sandbox.config import Config
from ex2_graph.simple_ex_graph import get_builder
from ex2_graph.tools import set_session_id
from langgraph_sandbox.sandbox.container_utils import cleanup_sandbox_containers
from langgraph_sandbox.artifacts.reader import fetch_artifact_urls

def main():
    app = FastAPI()

    env = load_dotenv("simple_sandbox.env")
    if env == True: 
        print("Loaded .env file")
    else:
        print("No .env file found")
    
    ensure_artifact_store() # bootstrap storage using environment variables

    cfg = Config.from_env(env_file_path=Path("simple_sandbox.env"))
    
    # Clean up any existing sandbox containers to avoid conflicts
    cleanup_sandbox_containers()
    
    # Generate a unique session ID for this conversation
    convo_id = str(uuid.uuid4())[:8]
    print(f"Starting new session: {convo_id}")
    
    # Set the session ID for the code execution tool
    set_session_id(convo_id)
    
    app.include_router(artifacts_router) # register endpoints

    # Start the FastAPI server for artifacts
    import uvicorn
    import threading
    import time
    
    def run_server():
        try:
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
        except Exception as e:
            print(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Give the server time to start
    print("Artifact server started on http://localhost:8000")

    builder = get_builder()

    memory = InMemorySaver()

    graph = builder.compile(checkpointer=memory)

    print("\n=== Simple Sandbox Example (TMPFS_NONE mode) ===\n")
    print("\n=== Type /bye to exit. ===\n")

    usr_msg = ""

    while True:

        usr_msg = input("User: ")

        if "/bye" in usr_msg.lower():
            break

        print(f"\n--- Thinking ... ---\n")
        
        try:
            # Use streaming to see real-time output and errors
            import asyncio
            
            async def run_stream():
                async for chunk in graph.astream(
                    {"messages": [{"role": "user", "content": usr_msg}]},
                    {"configurable": {"thread_id": f"{convo_id}"}, "recursion_limit": 25},
                ):
                    print(f"AI: {chunk['chat_model']['messages'][-1].content}")
            
            asyncio.run(run_stream())
                        
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
        
        # Artifacts are displayed directly in the agent's response
        
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
