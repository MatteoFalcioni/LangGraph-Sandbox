from src.make_graph import get_builder
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

if __name__ == "__main__":

    load_dotenv()
    builder = get_builder()

    memory = InMemorySaver()

    graph = builder.compile(checkpointer=memory)

    init = {"messages": [HumanMessage(content="Hello, Write python code to compute sin(pi/4)")]}
    out = graph.invoke(init, config={"configurable" : {"thread_id": 1}})
    print(out["messages"][-1].content)