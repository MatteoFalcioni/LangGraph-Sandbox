# Set environment variables to use fully_local database and blobstore
# This must be done before any imports that use the artifact system
import os
from pathlib import Path
os.environ["ARTIFACTS_DB_PATH"] = str(Path("fully_local.db").resolve())
os.environ["BLOBSTORE_DIR"] = str(Path("fully_local_blobstore").resolve())

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI
from src.artifacts.store import ensure_artifact_store
from src.artifacts.api import router as artifacts_router
from src.datasets.startup import initialize_local_datasets

from src.datasets.cache import clear_cache
from src.config import Config
from local_ex_graph import get_builder
from tools import set_session_id
from src.sandbox.container_utils import cleanup_sandbox_containers
from tools import fetch_artifact_urls, extract_artifact_references

if __name__ == "__main__":

    app = FastAPI()

    env = load_dotenv("fully_local.env")
    if env == True: 
        print("Loaded .env file")
    else:
        print("No .env file found")
    
    ensure_artifact_store(
        custom_db_path=Path("fully_local.db"), 
        custom_blob_dir=Path("fully_local_blobstore")
        ) # bootstrap storage

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

    # Start a simple HTTP server for artifacts
    import http.server
    import socketserver
    import threading
    import time
    from urllib.parse import urlparse, parse_qs
    
    class ArtifactHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/artifacts/'):
                # Handle artifact download
                try:
                    from src.artifacts.tokens import verify_token
                    from src.artifacts.store import _resolve_paths
                    import sqlite3
                    
                    # Parse the URL
                    parsed = urlparse(self.path)
                    artifact_id = parsed.path.split('/')[-1]
                    query_params = parse_qs(parsed.query)
                    
                    if 'token' not in query_params:
                        self.send_error(400, "Missing token parameter")
                        return
                    
                    token = query_params['token'][0]
                    
                    # Verify token
                    try:
                        data = verify_token(token)
                    except RuntimeError as e:
                        self.send_error(401, str(e))
                        return
                    
                    if data["artifact_id"] != artifact_id:
                        self.send_error(403, "Token does not match artifact")
                        return
                    
                    # Get artifact from database
                    paths = _resolve_paths()
                    with sqlite3.connect(paths["db_path"]) as conn:
                        row = conn.execute(
                            "SELECT sha256, mime, filename FROM artifacts WHERE id = ?",
                            (artifact_id,),
                        ).fetchone()
                        if not row:
                            self.send_error(404, "Artifact not found")
                            return
                        sha, mime, filename = row
                    
                    # Get blob path
                    blob_dir = paths["blob_dir"]
                    blob_path = blob_dir / sha[:2] / sha[2:4] / sha
                    if not blob_path.exists():
                        self.send_error(410, "Blob missing")
                        return
                    
                    # Serve the file
                    self.send_response(200)
                    self.send_header('Content-Type', mime or 'application/octet-stream')
                    self.send_header('Content-Disposition', f'attachment; filename="{filename or artifact_id}"')
                    self.end_headers()
                    
                    with open(blob_path, 'rb') as f:
                        self.wfile.write(f.read())
                        
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(404, "Not found")
    
    def run_server():
        try:
            with socketserver.TCPServer(("", 8000), ArtifactHandler) as httpd:
                httpd.serve_forever()
        except Exception as e:
            print(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1)  # Give the server time to start
    print("Artifact server started on http://localhost:8000")

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

        print(f"\n--- Processing: {usr_msg} ---")
        
        try:
            # Use streaming to see real-time output and errors
            for chunk in graph.stream(
                {"messages": [{"role": "user", "content": usr_msg}]},
                {"configurable": {"thread_id": f"{convo_id}"}, "recursion_limit": 25},
            ):
                print(f"AI: {chunk['chat_model']['messages'][-1].content}")
                
                # Check if this is the final result
                if "messages" in chunk and chunk["messages"]:
                    last_message = chunk["messages"][-1]
                    if hasattr(last_message, 'content') and last_message.content:
                        print(f"\nAI: {last_message.content}")
                        
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
        
        # Check for artifacts after the entire conversation turn
        artifacts = fetch_artifact_urls(convo_id)
        if artifacts:
            print(f"\n📁 Generated Artifacts ({len(artifacts)}):")
            for artifact in artifacts:
                print(f"  • {artifact['filename']} ({artifact['mime']})")
                print(f"    Download: {artifact['download_url']}")
                print(f"    Size: {artifact['size']} bytes")
                print()
        
        print("\n" + "="*50 + "\n")