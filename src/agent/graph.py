"""
LangGraph scouting agent.

A ReAct agent that connects to all three data sources (Player Stats,
Transfer Market, Match Events) by launching them as MCP servers over stdio
and loading their tools through an MCP client. The agent plans which tools
to call and synthesizes the results.

Tools originate from the MCP servers in mcp_servers/ (via MultiServerMCPClient),
NOT from direct database functions. Redis caching lives inside those servers,
so it keeps working transparently.

LLM: Qwen3 8B via Ollama (local)
Observability: LangSmith (traces every run automatically)

Usage:
    python -m src.agent.graph                          # interactive CLI
    python -m src.agent.graph "find young PL forwards"  # single query
"""

import os
import sys
import asyncio
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
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.agent.prompts import SCOUTING_SYSTEM_PROMPT

# ── Configuration (read from .env) ────────────────────────────────────

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Absolute paths to the MCP servers, anchored to the project root so the
# subprocesses can be spawned regardless of the current working directory.
PROJECT_ROOT = Path(__file__).parent.parent.parent
MCP_SERVERS_DIR = PROJECT_ROOT / "mcp_servers"

# Keep a module-level reference to the client so it is not garbage-collected
# while the MCP-backed tools are still in use.
_MCP_CLIENT: MultiServerMCPClient | None = None


def _build_mcp_client() -> MultiServerMCPClient:
    """Configure an MCP client that launches all three servers over stdio.

    sys.executable is used as the command so the servers run under the same
    Python interpreter as the agent — correct both locally and in the
    container.
    """
    return MultiServerMCPClient(
        {
            "player_stats": {
                "command": sys.executable,
                "args": [str(MCP_SERVERS_DIR / "player_stats_server.py")],
                "transport": "stdio",
            },
            "transfer_market": {
                "command": sys.executable,
                "args": [str(MCP_SERVERS_DIR / "transfer_market_server.py")],
                "transport": "stdio",
            },
            "match_events": {
                "command": sys.executable,
                "args": [str(MCP_SERVERS_DIR / "match_events_server.py")],
                "transport": "stdio",
            },
        }
    )


async def load_mcp_tools() -> list:
    """Launch the MCP servers and return their tools as LangChain tools."""
    global _MCP_CLIENT
    _MCP_CLIENT = _build_mcp_client()
    return await _MCP_CLIENT.get_tools()


async def build_agent():
    """Build and return the compiled LangGraph scouting agent.

    Tools are loaded from the three MCP servers via the MCP client.
    """
    tools = await load_mcp_tools()

    # LLM with the MCP-provided tools bound
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        num_ctx=8192,
        timeout=90,
    ).bind_tools(tools)

    # ── Graph nodes ───────────────────────────────────────────────────

    async def agent_node(state: MessagesState):
        """Call the LLM. It decides whether to use tools or give a final answer."""
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SCOUTING_SYSTEM_PROMPT)] + messages
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

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


# ── Query runner ──────────────────────────────────────────────────────

async def run_query(agent, query: str) -> str:
    """Run a single scouting query and return the final response."""
    result = await agent.ainvoke(
        {
            "messages": [
                SystemMessage(content=SCOUTING_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]
        },
        config={"recursion_limit": 12},
    )
    return result["messages"][-1].content


# ── CLI interface ─────────────────────────────────────────────────────

async def _amain():
    tracing = os.getenv("LANGCHAIN_TRACING_V2", "false")
    project = os.getenv("LANGCHAIN_PROJECT", "default")

    print("Building SportsBrain agent...")
    print(f"  LLM: {OLLAMA_MODEL} via Ollama")
    print("  Tools: loaded from 3 MCP servers (stdio)")
    print(f"  LangSmith tracing: {tracing}")
    if tracing.lower() == "true":
        print(f"  LangSmith project: {project}")
    print()

    try:
        agent = await build_agent()
    except Exception as e:
        print(f"ERROR: Could not build agent: {e}")
        print("Make sure Ollama is running (ollama serve) and the MCP servers import cleanly.")
        return

    # Single query mode
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"Query: {query}")
        print("-" * 60)
        response = await run_query(agent, query)
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
            response = await run_query(agent, query)
            print(f"\n{response}")
        except Exception as e:
            print(f"\nError: {e}")


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()