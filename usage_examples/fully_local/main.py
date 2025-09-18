# Set environment variables to use example1 database and blobstore
# This must be done before any imports that use the artifact system
import os
import sys
from pathlib import Path

# Add the project root to Python path so we can import from src
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

os.environ["ARTIFACTS_DB_PATH"] = str(Path("example1_artifacts.db").resolve())
os.environ["BLOBSTORE_DIR"] = str(Path("example1_blobstore").resolve())

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI
from langgraph_sandbox.artifacts.store import ensure_artifact_store
from langgraph_sandbox.artifacts.api import router as artifacts_router
from langgraph_sandbox.dataset_manager.startup import initialize_local_datasets

from langgraph_sandbox.dataset_manager.cache import clear_cache
from langgraph_sandbox.config import Config
from ex1_graph.local_ex_graph import get_builder
from ex1_graph.tools import set_session_id
from ex1_graph.tools import extract_artifact_references
from langgraph_sandbox.sandbox.container_utils import cleanup_sandbox_containers
from langgraph_sandbox.artifacts.reader import fetch_artifact_urls

if __name__ == "__main__":

    app = FastAPI()
    
    ensure_artifact_store() # bootstrap storage using environment variables

    cfg = Config.from_env(env_file_path=Path("fully_local.env"))
    
    # Clean up any existing sandbox containers to avoid conflicts
    cleanup_sandbox_containers()
    
    # Generate a unique session ID for this conversation
    convo_id = str(uuid.uuid4())[:8]
    print(f"Starting new session: {convo_id}")
    
    # Set the session ID for the code execution tool
    set_session_id(convo_id)
    
    # Initialize datasets for this specific conversation
    initialize_local_datasets(cfg, session_id=convo_id)

    app.include_router(artifacts_router) # register endpoints

    # Start the FastAPI server for artifacts
    import uvicorn
    import threading
    import time
    
    server_port = None
    
    def run_server():
        nonlocal server_port
        ports_to_try = [8000, 8001, 8002, 8003, 8004]
        for port in ports_to_try:
            try:
                server_port = port
                uvicorn.run(app, host="0.0.0.0", port=port, log_level="error")
                break  # Success, exit the loop
            except OSError as e:
                if "address already in use" in str(e).lower():
                    if port == ports_to_try[0]:  # Only show warning for first attempt
                        print(f"⚠️  Port {port} is already in use (likely by Docker Compose), trying alternative port...")
                    continue  # Try next port
                else:
                    print(f"Server error: {e}")
                    break
            except Exception as e:
                print(f"Server error: {e}")
                break
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Give the server time to start
    
    # Report the actual port used
    if server_port:
        print(f"Artifact server started on http://localhost:{server_port}")
    else:
        print("Artifact server started")

    builder = get_builder()

    memory = InMemorySaver()

    graph = builder.compile(checkpointer=memory)

    print("=== Type /bye to exit. ===\n")

    usr_msg = ""

    while True:

        usr_msg = input("User: ")

        if "/bye" in usr_msg.lower():
            # Clear the dataset cache when exiting
            clear_cache(cfg, convo_id)
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
                    
                    # Check if this is the final result
                    if "messages" in chunk and chunk["messages"]:
                        last_message = chunk["messages"][-1]
                        if hasattr(last_message, 'content') and last_message.content:
                            print(f"\nAI: {last_message.content}")
            
            asyncio.run(run_stream())
                        
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
        
        # you can handle artifact detection here - though it is not needed because it is handled by the general artifact system
        # still could be useful for UI or debugging
        '''# Check for artifacts after the entire conversation turn
        artifacts = fetch_artifact_urls(convo_id)
        if artifacts:
            print(f"\n📁 Generated Artifacts ({len(artifacts)}):")
            for artifact in artifacts:
                print(f"  • {artifact['filename']} ({artifact['mime']})")
                print(f"    Download: {artifact['download_url']}")
                print(f"    Size: {artifact['size']} bytes")
                print()'''
        
        print("\n" + "="*50 + "\n")