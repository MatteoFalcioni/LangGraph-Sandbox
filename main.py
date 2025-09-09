from src.graph.make_graph import get_builder
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import uuid

from fastapi import FastAPI
from src.artifacts.store import ensure_artifact_store
from src.artifacts.api import router as artifacts_router

if __name__ == "__main__":

    app = FastAPI()

    env = load_dotenv()
    if env == True: 
        print("Loaded .env file")
    else:
        print("No .env file found")

    ensure_artifact_store() # bootstrap storage

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

        result = graph.invoke(
            {"messages": [{"role": "user", "content": usr_msg}]},
            {"configurable": {"thread_id": f"{convo_id}"}, "recursion_limit" : 25},
        )

        ai_message = result["messages"][-1].content

        print(f'\nAI: {ai_message}\n')