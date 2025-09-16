#!/usr/bin/env python3
"""
LangGraph Sandbox - Main Entry Point

This is the main entry point for the LangGraph Sandbox package.
It provides a simple interactive sandbox for code execution.

Usage:
    langgraph-sandbox                    # Run interactive sandbox
    python src/main.py                   # Run interactive sandbox
    python src/main.py --help            # Show help
"""

import sys
import os
import uuid
import threading
import time
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

from src.artifacts.store import ensure_artifact_store
from src.artifacts.api import router as artifacts_router
from src.config import Config
from src.sandbox.container_utils import cleanup_sandbox_containers
from src.artifacts.reader import fetch_artifact_urls

def main():
    """Main entry point for the LangGraph Sandbox."""
    
    print("🐳 LangGraph Sandbox - Interactive Code Execution Environment")
    print("=" * 60)
    
    # Load environment configuration
    env_file = Path("simple_sandbox.env")
    if not env_file.exists():
        env_file = Path("example.env")
    
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
    from src.sandbox.session_manager import SessionManager
    session_manager = SessionManager(
        image=cfg.sandbox_image,
        session_storage=cfg.session_storage,
        dataset_access=cfg.dataset_access,
        datasets_path=cfg.datasets_host_ro,
        session_root=cfg.sessions_root,
        tmpfs_size=cfg.tmpfs_size_mb,
    )
    
    # Create tools with session key function
    def get_session_key():
        return convo_id
    
    from src.tool_factory.make_tools import make_code_sandbox_tool, make_export_datasets_tool
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
    
    # Start artifact server
    def run_server():
        try:
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
        except Exception as e:
            print(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Give server time to start
    print("✅ Artifact server started on http://localhost:8000")

    # Create simple graph
    from langgraph.graph import StateGraph, END
    from langchain_openai import ChatOpenAI
    from langgraph.graph.message import add_messages
    from typing import TypedDict, Annotated
    
    class State(TypedDict):
        messages: Annotated[list, add_messages]
    
    # Initialize LLM
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    # Create graph
    def call_model(state: State):
        return {"messages": [llm.invoke(state["messages"])]}
    
    def call_tool(state: State):
        messages = state["messages"]
        last_message = messages[-1]
        
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            tool_call = last_message.tool_calls[0]
            tool_name = tool_call["name"]
            
            if tool_name == "code_sandbox":
                result = code_exec_tool.invoke({"code": tool_call["args"]["code"]})
                return {"messages": [result]}
            elif tool_name == "export_datasets":
                result = export_datasets_tool.invoke({"container_path": tool_call["args"]["container_path"]})
                return {"messages": [result]}
        
        return {"messages": []}
    
    # Build graph
    workflow = StateGraph(State)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", call_tool)
    workflow.add_edge("agent", "tools")
    workflow.add_edge("tools", "agent")
    workflow.set_entry_point("agent")
    
    # Add tools to LLM
    llm_with_tools = llm.bind_tools([code_exec_tool, export_datasets_tool])
    
    # Compile graph
    graph = workflow.compile(checkpointer=InMemorySaver())
    
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
                async for chunk in graph.astream(
                    {"messages": [{"role": "user", "content": usr_msg}]},
                    {"configurable": {"thread_id": convo_id}, "recursion_limit": 25},
                ):
                    if "agent" in chunk and chunk["agent"]["messages"]:
                        last_msg = chunk["agent"]["messages"][-1]
                        if hasattr(last_msg, 'content') and last_msg.content:
                            print(last_msg.content, end="", flush=True)
                    elif "tools" in chunk and chunk["tools"]["messages"]:
                        last_msg = chunk["tools"]["messages"][-1]
                        if hasattr(last_msg, 'content') and last_msg.content:
                            print(f"\n{last_msg.content}")
            
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