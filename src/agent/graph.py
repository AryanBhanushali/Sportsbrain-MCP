"""
LangGraph scouting agent.

A ReAct agent that connects to all three data sources (Player Stats,
Transfer Market, Match Events) and answers complex scouting queries
by planning which tools to call and synthesizing the results.

LLM: Qwen3 8B via Ollama (local)
Observability: LangSmith (traces every run automatically)

Usage:
    python -m src.agent.graph                          # interactive CLI
    python -m src.agent.graph "find young PL forwards"  # single query
"""

import os
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env BEFORE any langchain imports — LangSmith reads env vars on import
from dotenv import load_dotenv
load_dotenv()

from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.tools import ALL_TOOLS
from src.agent.prompts import SCOUTING_SYSTEM_PROMPT

# ── Configuration (read from .env) ────────────────────────────────────

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def build_agent():
    """Build and return the compiled LangGraph scouting agent."""

    # LLM with tools bound
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        num_ctx=8192,
        timeout=90,
    ).bind_tools(ALL_TOOLS)

    # ── Graph nodes ───────────────────────────────────────────────────

    def agent_node(state: MessagesState):
        """Call the LLM. It decides whether to use tools or give a final answer."""
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SCOUTING_SYSTEM_PROMPT)] + messages
        response = llm.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(ALL_TOOLS)

    # ── Routing ───────────────────────────────────────────────────────

    def should_continue(state: MessagesState):
        """If the LLM made tool calls, execute them. Otherwise, end."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    # ── Build graph ───────────────────────────────────────────────────

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── CLI interface ─────────────────────────────────────────────────────

def run_query(agent, query: str) -> str:
    """Run a single scouting query and return the final response."""
    result = agent.invoke(
        {
            "messages": [
                SystemMessage(content=SCOUTING_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]
        },
        config={"recursion_limit": 12},
    )
    return result["messages"][-1].content


def main():
    # Show config
    tracing = os.getenv("LANGCHAIN_TRACING_V2", "false")
    project = os.getenv("LANGCHAIN_PROJECT", "default")

    print("Building SportsBrain agent...")
    print(f"  LLM: {OLLAMA_MODEL} via Ollama")
    print(f"  Tools: {len(ALL_TOOLS)} scouting tools")
    print(f"  LangSmith tracing: {tracing}")
    if tracing.lower() == "true":
        print(f"  LangSmith project: {project}")
    print()

    try:
        agent = build_agent()
    except Exception as e:
        print(f"ERROR: Could not build agent: {e}")
        print("Make sure Ollama is running: ollama serve")
        return

    # Single query mode
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"Query: {query}")
        print("-" * 60)
        response = run_query(agent, query)
        print(response)
        return

    # Interactive mode
    print("SportsBrain Scouting Agent")
    print("Type a scouting query, or 'quit' to exit.")
    print("-" * 60)

    while True:
        try:
            query = input("\nScout > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not query or query.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        try:
            response = run_query(agent, query)
            print(f"\n{response}")
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    main()
