"""
Fires a set of diverse scouting queries to populate LangSmith with trace data.
Run: python scripts/test_agent_traces.py

After running, check smith.langchain.com → sportsbrain project to see:
  - Which tools were called per query
  - Latency per step (LLM call vs tool execution)
  - Token usage per run
  - Full message history for each trace
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.agent.graph import build_agent, run_query

TEST_QUERIES = [
    # Single-source queries (1 tool call each)
    "Who are the top scorers in the Premier League this season?",
    "What is Bukayo Saka's current market valuation?",

    # Multi-source queries (2+ tool calls)
    "Find me La Liga forwards under 23 with 5+ goals and check their market value",
    "Compare Cole Palmer and Florian Wirtz — stats and valuation",

    # Edge cases
    "Tell me about a player named Xyznotreal",
    "Which Bundesliga defenders have the most interceptions?",
]


def main():
    print("Building agent...")
    agent = build_agent()
    print(f"Running {len(TEST_QUERIES)} test queries...\n")

    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"[{i}/{len(TEST_QUERIES)}] {query}")
        try:
            response = run_query(agent, query)
            # Print first 150 chars of response as preview
            preview = response[:150].replace("\n", " ")
            print(f"  ✓ {preview}...")
        except Exception as e:
            print(f"  ✗ Error: {e}")
        print()

    print("Done. Check smith.langchain.com → sportsbrain project for traces.")


if __name__ == "__main__":
    main()
