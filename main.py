from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid
from pathlib import Path

from fastapi import FastAPI
from src.artifacts.store import ensure_artifact_store
from src.artifacts.api import router as artifacts_router
from src.datasets.startup import initialize_local_datasets
from src.datasets.cache import clear_cache
from src.config import Config
from langgraph_app.make_graph import get_builder

if __name__ == "__main__":

    app = FastAPI()

    env = load_dotenv()
    if env == True: 
        print("Loaded .env file")
    else:
        print("No .env file found")

    ensure_artifact_store() # bootstrap storage

    # Initialize LOCAL_RO datasets if using that mode
    # You can now specify a custom env file path:
    # cfg = Config.from_env(Path("custom.env"))
    # Or use the default behavior (system env + .env file via dotenv):
    cfg = Config.from_env()
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
            # Clear the dataset cache when exiting
            clear_cache(cfg, convo_id)
            break

        result = graph.invoke(
            {"messages": [{"role": "user", "content": usr_msg}]},
            {"configurable": {"thread_id": f"{convo_id}"}, "recursion_limit" : 25},
        )

        ai_message = result["messages"][-1].content

        print(f'\nAI: {ai_message}\n')

    # in your app with UI you can then read artifacts produced in the session and stored in the db 
    # Example: reading artifacts produced during the session
    '''for m in result["messages"]:
        if m.type == "tool" and "artifacts" in m.content:
            for art in m.content["artifacts"]:
                meta = get_metadata(art["id"])
                print("Artifact available:", meta)
            if meta["mime"].startswith("text/"):
                print("Preview:", read_text(art["id"], max_bytes=200))'''