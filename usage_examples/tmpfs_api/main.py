import os
import sys
from pathlib import Path

# Add the project root to Python path so we can import from src
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

os.environ["ARTIFACTS_DB_PATH"] = str(Path("tmpfs_api_artifacts.db").resolve())
os.environ["BLOBSTORE_DIR"] = str(Path("tmpfs_api_blobstore").resolve())

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI
from langgraph_sandbox.artifacts.store import ensure_artifact_store
from langgraph_sandbox.artifacts.api import router as artifacts_router

from langgraph_sandbox.config import Config
from ex3_graph.tmpfs_api_ex_graph import get_builder
from ex3_graph.tools import set_session_id, client
from langgraph_sandbox.sandbox.container_utils import cleanup_sandbox_containers

if __name__ == "__main__":

    app = FastAPI()
    
    ensure_artifact_store() # bootstrap storage using environment variables

    cfg = Config.from_env(env_file_path=Path("tmpfs_api.env"))
    
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
    
    server_port = [None]  # Use a list to make it mutable
    
    def run_server():
        ports_to_try = [8000, 8001, 8002, 8003, 8004]
        for port in ports_to_try:
            try:
                server_port[0] = port
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
    if server_port[0]:
        print(f"Artifact server started on http://localhost:{server_port[0]}")
    else:
        print("Artifact server started")

    builder = get_builder()

    memory = InMemorySaver()

    graph = builder.compile(checkpointer=memory)

    print("\n=== TMPFS API Example (TMPFS_API mode) ===\n")
    print("\n=== Type /bye to exit. ===\n")

    usr_msg = ""

    while True:

        usr_msg = input("User: ")

        if "/bye" in usr_msg.lower():
            # Close the API client gracefully
            print("Closing API client...")
            try:
                import asyncio
                # Check if there's a running event loop
                try:
                    loop = asyncio.get_running_loop()
                    # If we're in a running loop, schedule the close
                    loop.create_task(client.close())
                except RuntimeError:
                    # No event loop running, create a new one
                    asyncio.run(client.close())
            except Exception as e:
                print(f"Warning: Could not close client gracefully: {e}")
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
        
        # Artifacts are displayed directly in the agent's response
        
        print("\n" + "="*50 + "\n")
