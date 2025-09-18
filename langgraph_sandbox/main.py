#!/usr/bin/env python3
"""
LangGraph Sandbox - Main Entry Point

This is the main entry point for the LangGraph Sandbox package.
It provides a simple interactive sandbox for code execution.

Usage:
    langgraph-sandbox                    # Run interactive sandbox
    python langgraph_sandbox/main.py                   # Run interactive sandbox
    python langgraph_sandbox/main.py --help            # Show help
"""

from cmd import PROMPT
import sys
import os
import uuid
import threading
import time
from pathlib import Path
from datetime import datetime

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

try:
    # Try relative imports first (when used as a module)
    from .artifacts.store import ensure_artifact_store
    from .artifacts.api import router as artifacts_router
    from .config import Config
    from .sandbox.container_utils import cleanup_sandbox_containers
    from .artifacts.reader import fetch_artifact_urls
except ImportError:
    # Fall back to absolute imports (when run directly)
    from artifacts.store import ensure_artifact_store
    from artifacts.api import router as artifacts_router
    from config import Config
    from sandbox.container_utils import cleanup_sandbox_containers
    from artifacts.reader import fetch_artifact_urls

def main():
    """Main entry point for the LangGraph Sandbox."""
    
    import argparse
    parser = argparse.ArgumentParser(description="LangGraph Sandbox - Interactive Code Execution Environment")
    args = parser.parse_args()
    
    print("🐳 LangGraph Sandbox - Interactive Code Execution Environment")
    print("=" * 60)
    
    # Load environment configuration
    env_file = Path("sandbox.env")
    if not env_file.exists():
        env_file = Path("example.env")
        print("(❗) No sandbox.env file found, using example.env - you should rename it to sandbox.env and fill in the OpenAI API key")
    
    env_loaded = load_dotenv(env_file)
    if env_loaded:
        print(f"✅ Loaded configuration from {env_file}")
    else:
        print("⚠️  No .env file found, using defaults")
    
    # Initialize artifact store
    ensure_artifact_store()
    print("✅ Artifact store initialized")

    # Load configuration
    cfg = Config.from_env(env_file_path=env_file if env_file.exists() else None)
    print(f"✅ Configuration loaded: {cfg.mode_id()} mode")
    
    # Clean up any existing sandbox containers
    cleanup_sandbox_containers()
    print("✅ Cleaned up existing containers")
    
    # Generate a unique session ID for this conversation
    convo_id = str(uuid.uuid4())[:8]
    print(f"✅ Starting new session: {convo_id}")
    
    # Create session manager
    from .sandbox.session_manager import SessionManager
    session_manager = SessionManager(
        image=cfg.sandbox_image,
        session_storage=cfg.session_storage,
        dataset_access=cfg.dataset_access,
        datasets_path=cfg.datasets_host_ro,
        session_root=cfg.sessions_root,
        tmpfs_size=cfg.tmpfs_size_mb,
        address_strategy=cfg.sandbox_address_strategy,
        compose_network=cfg.compose_network,
        host_gateway=cfg.host_gateway,
    )
    
    # Create tools with session key function
    def get_session_key():
        return convo_id
    
    from .tool_factory.make_tools import make_code_sandbox_tool, make_export_datasets_tool
    code_exec_tool = make_code_sandbox_tool(
        session_manager=session_manager,
        session_key_fn=get_session_key
    )
    export_datasets_tool = make_export_datasets_tool(
        session_manager=session_manager,
        session_key_fn=get_session_key
    )
    
    # Set up FastAPI for artifacts
    app = FastAPI()
    app.include_router(artifacts_router)
    
    # Start artifact server with port fallback
    server_port = None
    
    def run_server():
        nonlocal server_port
        ports_to_try = [8000, 8001, 8002, 8003, 8004]
        for port in ports_to_try:
            try:
                server_port = port
                # Set the server port in environment for URL generation
                os.environ["ARTIFACTS_SERVER_PORT"] = str(port)
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
    time.sleep(2)  # Give server time to start
    
    # Report the actual port used
    if server_port:
        print(f"✅ Artifact server started on http://localhost:{server_port}")
    else:
        print("✅ Artifact server started")

    # Create simple graph
    from langgraph.graph import StateGraph, MessagesState, END
    from langchain_openai import ChatOpenAI
    from langgraph.graph import StateGraph, MessagesState, START, END
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    from langgraph.checkpoint.memory import InMemorySaver

    PROMPT = """
            You are a helpful AI assistant that writes Python code to run in a Docker sandbox.

            Rules:
            1. Always use `print(...)` to show results. Do not rely on implicit printing (e.g. `df.head()` must be wrapped in `print(df.head())`).
            2. This is a simple sandbox with NO datasets - you can only work with data you create or generate in your code.
            3. A writable persistent folder `/session` exists. Use it to save intermediate files that need to be reused across multiple tool calls in the same conversation.
            4. For run-specific outputs (plots, text files, etc.), save them into `/session/artifacts/`. These files will be automatically detected, copied out of the container, and ingested into the artifact store with deduplication and metadata tracking.
            5. Always include required imports, and explicitly create directories if needed (e.g. `Path("/session/artifacts").mkdir(parents=True, exist_ok=True)`).
            6. Handle errors explicitly (e.g. check if files exist before reading).
            7. Be concise and focused: only write code that directly answers the user's request.
            8. The sandbox runs in a persistent container per conversation - variables and imports persist between tool calls in the same session.
            9. Artifacts are automatically processed: files in `/session/artifacts/` are detected after each execution, copied to the host, stored in a content-addressed blobstore, and made available via the artifacts API.
            10. After creating artifacts, you will be able to see links for downloading them. ALWAYS provide them to the user **exactly as is**. Do not modify them or invent URLs. Do not use markdown link syntax like [filename](url). Example: Say "The plot has been saved as <full link>" instead of "[Download plot.png](url)".
            11. EXPORT DATASETS: If you create or modify datasets in `/session/data/`, you can use the `export_datasets` tool to save them to the host filesystem at `./exports/modified_datasets/` with timestamp prefixes.
            12. MEMORY MANAGEMENT: The sandbox automatically cleans up matplotlib figures and old artifacts after each execution to prevent space issues. Your intermediate files in /tmp and /session are preserved. The sandbox has 4GB of tmpfs space available.

            IMPORTANT: This sandbox has NO datasets available. You can only work with data you create, generate, or fetch from external sources in your code.
            """
    
    # Initialize LLM
    llm = ChatOpenAI(model="gpt-4.1", temperature=0)
    coding_agent = create_react_agent(
        model=llm,
        tools=[code_exec_tool, export_datasets_tool],
        prompt=PROMPT
    )
    
    async def call_model(state: MessagesState):
        result = await coding_agent.ainvoke({"messages" : state["messages"]})
        last = result["messages"][-1]

        update = AIMessage(content=last.content)

        return {"messages": [update]}

    builder = StateGraph(MessagesState)

    builder.add_node("chat_model", call_model)
    builder.add_edge(START, "chat_model")
    builder.add_edge("chat_model", END)

    # Compile graph
    graph = builder.compile(checkpointer=InMemorySaver())
    
    print("\n🚀 Interactive Sandbox Ready!")
    print("=" * 60)
    print("Type '/bye' to exit.")
    print("=" * 60)

    # Interactive loop
    while True:
        try:
            usr_msg = input("\n👤 User: ")
            
            if "/bye" in usr_msg.lower():
                print("👋 Goodbye!")
                break
            
            print("\n🤖 AI: ", end="", flush=True)
            
            # Run the conversation
            import asyncio
            async def run_conversation():
                artifacts_log = []
                async for chunk in graph.astream(
                    {"messages": [{"role": "user", "content": usr_msg}]},
                    {"configurable": {"thread_id": convo_id}, "recursion_limit": 25},
                ):
                    print(f"AI: {chunk['chat_model']['messages'][-1].content}")
                    
                    # Collect artifacts from tool messages
                    for message in chunk.get('chat_model', {}).get('messages', []):
                        if hasattr(message, 'artifact') and message.artifact:
                            artifacts_log.extend(message.artifact)
                
                # Handle artifacts if not displayed in chat
                if artifacts_log and not cfg.in_chat_url:
                    artifact_log_path = Path("./artifact_logs") / f"{convo_id}_artifacts.txt"
                    artifact_log_path.parent.mkdir(exist_ok=True)
                    
                    with open(artifact_log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                        f.write(f"User: {usr_msg}\n")
                        f.write("Generated Artifacts:\n")
                        for artifact in artifacts_log:
                            filename = artifact.get('name', 'unknown')
                            size = artifact.get('size', 0)
                            mime = artifact.get('mime', 'unknown')
                            download_url = artifact.get('url', '')
                            f.write(f"  • {filename} ({mime}, {size} bytes)\n")
                            if download_url:
                                f.write(f"    Download: {download_url}\n")
                        f.write("\n")
                    
                    print(f"\n📁 {len(artifacts_log)} artifact(s) logged to: {artifact_log_path}")
            
            asyncio.run(run_conversation())
            print()  # New line after response
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("✅ Session ended")

if __name__ == "__main__":
    main()