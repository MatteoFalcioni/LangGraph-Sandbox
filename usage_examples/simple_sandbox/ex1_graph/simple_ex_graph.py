from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
from ex1_graph.tools import code_exec_tool, export_datasets_tool

from ex1_graph.prompt import PROMPT

load_dotenv("simple_sandbox.env")

llm = ChatOpenAI(model="gpt-5")

coding_agent = create_react_agent(
    model=llm,
    tools=[code_exec_tool, export_datasets_tool],
    prompt=PROMPT
)

def call_model(state: MessagesState):
    result = coding_agent.invoke({"messages" : state["messages"]})
    last = result["messages"][-1]

    update = AIMessage(content=last.content)

    return {"messages": [update]}

def get_builder() -> StateGraph:
    builder = StateGraph(MessagesState)

    builder.add_node("chat_model", call_model)
    builder.add_edge(START, "chat_model")
    builder.add_edge("chat_model", END)

    return builder


if __name__ == "__main__":

    checkpointer = InMemorySaver()

    builder = get_builder()
    graph = builder.compile(checkpointer=checkpointer)
    
    init = {"messages": [HumanMessage(content="Hello, Write python code to compute sin(pi/4)")]}
    out = graph.invoke(init, config={"configurable" : {"thread_id": 1}})
    print(out["messages"][-1].content)
