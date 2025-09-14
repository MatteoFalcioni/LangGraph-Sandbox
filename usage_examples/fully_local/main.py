from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid
from pathlib import Path

from fastapi import FastAPI
from src.artifacts.store import ensure_artifact_store
from src.artifacts.api import router as artifacts_router
from src.datasets.startup import initialize_local_datasets
from src.config import Config
from local_ex_graph import get_builder

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
    initialize_local_datasets(cfg)

    app.include_router(artifacts_router) # register endpoints

    builder = get_builder()

    memory = InMemorySaver()

    graph = builder.compile(checkpointer=memory)

    convo_id = str(uuid.uuid4())[:8]

    print("=== Type /bye to exit. ===\n")

    usr_msg = ""

    while True:

        usr_msg = input("User: ")

        if "/bye" in usr_msg.lower():
            break

        print(f"\n--- Processing: {usr_msg} ---")
        
        try:
            # Use streaming to see real-time output and errors
            for chunk in graph.stream(
                {"messages": [{"role": "user", "content": usr_msg}]},
                {"configurable": {"thread_id": f"{convo_id}"}, "recursion_limit": 25},
            ):
                print(f"Chunk: {chunk}")
                
                # Check if this is the final result
                if "messages" in chunk and chunk["messages"]:
                    last_message = chunk["messages"][-1]
                    if hasattr(last_message, 'content') and last_message.content:
                        print(f"\nAI: {last_message.content}")
                        
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "="*50 + "\n")