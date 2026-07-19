# SportsBrain - MCP-Powered Football Scouting Platform

A unified scouting agent that exposes football data sources as MCP servers, answers complex plain-English queries across player stats, transfer valuations, and match events, and proves answer quality with a rigorous evaluation pipeline.

The agent answers queries like "Find me Premier League forwards under 25 with 10+ goals and check their market valuations" by calling the right tools across multiple data sources and synthesizing a scouting report.

## The problem

Football scouts query multiple data sources manually: one for match stats, one for transfer valuations, one for injury histories. Each query takes 10-15 minutes across different UIs. This system exposes each data source as an MCP server, lets scouts ask complex questions in plain English, and proves the quality of its answers with an evaluation pipeline.

## Architecture

```
MCP Server 1: Player Stats   (FBref -> SQLite -> 3 tools)
MCP Server 2: Transfer Market (Transfermarkt -> SQLite -> 3 tools)
MCP Server 3: Match Events    (Statsbomb -> SQLite -> 3 tools)
        |
        v
LangGraph ReAct Agent --> connects to all 7 tools
        |                  plans multi-step queries across sources
        |                  Qwen3 8B via Ollama (local)
        v
Redis --> caches tool results (1hr stats, 24hr valuations)
        |
        v
LangSmith --> traces every run (latency, tokens, tools called)
        |
        v
Evaluation --> 163-question golden test set
        |      faithfulness, relevancy, tool usage scoring
        v
FastAPI + Docker Compose --> containerized REST API
```

## How it works

**MCP Servers:** Three MCP servers expose football data through standardized tool interfaces. Server 1 wraps FBref season stats (2,839 players across Big 5 leagues). Server 2 wraps Transfermarkt valuations (508 top players with career value history). Server 3 wraps Statsbomb match events (per-match goals, passes, tackles, dribbles from La Liga 2020/21 and Bundesliga 2023/24). All data lives in a single SQLite database with indexed tables.

**LangGraph Agent:** A ReAct agent with 7 tools bound to Qwen3 8B via Ollama. The agent receives a natural language scouting query, decides which tools to call and in what order, executes them, and synthesizes the results into a scouting report. Multi-source queries (stats + valuations) require multiple tool calls planned by the agent.

**Redis Cache:** Every tool call checks Redis before hitting SQLite. Player stats cache for 1 hour, transfer valuations for 24 hours. Repeated queries return instantly from cache.

**LangSmith Observability:** Every agent run is traced with full message history, latency per step, token usage, and tool selection decisions.

## Evaluation results

Evaluated on a 163-question golden test set generated from actual database data:

| Metric          | Score                                |
| --------------- | ------------------------------------ |
| Success Rate    | 99.4% (162/163)                      |
| Tool Usage Rate | 96.9%                                |
| Faithfulness    | 75.9%                                |
| Relevancy       | 82.1%                                |
| Avg Latency     | 32.7s (local 8B model on laptop GPU) |

Full breakdown by category in [`evaluation/results.md`](evaluation/results.md).

## Stack

| Layer         | Technology                                                |
| ------------- | --------------------------------------------------------- |
| Agent         | LangGraph ReAct agent with 7 tools                        |
| LLM           | Qwen3 8B via Ollama (local, no API costs)                 |
| Data Layer    | 3 MCP servers backed by SQLite                            |
| Cache         | Redis 8                                                   |
| Observability | LangSmith                                                 |
| Evaluation    | 163-question golden set, faithfulness + relevancy scoring |
| API           | FastAPI                                                   |
| Orchestration | Docker Compose                                            |

## Running it

### Prerequisites

- Python 3.12
- Docker Desktop
- Ollama with `qwen3:8b` model
- Node.js (for MCP Inspector, optional)

### Setup

1. Clone the repo:

```bash
git clone https://github.com/AryanBhanushali/sportsbrain-mcp.git
cd sportsbrain-mcp
```

2. Create virtual environment:

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=sportsbrain
REDIS_URL=redis://localhost:6379
```

5. Start Redis:

```bash
docker compose up redis -d
```

6. Load data into SQLite:

```bash
python scripts/load_data.py
python scripts/load_data.py --all
```

7. Pull the LLM:

```bash
ollama pull qwen3:8b
```

### Running the agent (CLI)

```bash
python -m src.agent.graph
# Example: Scout > Find me PL forwards under 25 with 10+ goals and check their valuations
```

### Running the API

```bash
uvicorn src.api.main:app --reload
# POST http://localhost:8000/query {"question": "Compare Haaland and Igor Thiago"}
```

### Running with Docker

```bash
docker compose up --build
# API at http://localhost:8000
# Requires Ollama running on host
```

### Testing MCP servers individually

```bash
mcp dev mcp_servers/player_stats_server.py
# In the browser Inspector: set Command to "python", Arguments to "mcp_servers/player_stats_server.py"
```

### Running the evaluation

```bash
python scripts/generate_golden_set.py       # Generate 163 questions from DB
python evaluation/run_ragas.py              # Run all questions (~90 min)
python evaluation/run_ragas.py --limit 10   # Quick test
```

## API

| Endpoint  | Method | Description                                             |
| --------- | ------ | ------------------------------------------------------- |
| `/health` | GET    | Service health + cache stats                            |
| `/query`  | POST   | Natural language scouting query, returns agent response |

### Example

```
POST /query
{"question": "Find me Premier League forwards under 25 with 10+ goals"}

-> {
    "answer": "Here are the PL forwards under 25 with 10+ goals...",
    "latency_s": 34.2
}
```

## Data

| Source        | Coverage                                       | Records                              |
| ------------- | ---------------------------------------------- | ------------------------------------ |
| FBref         | Big 5 leagues 2025-2026 season stats           | 2,839 players, 52 stat columns       |
| Transfermarkt | Top player valuations + career history         | 508 players, 9,764 valuation points  |
| Statsbomb     | Match events (La Liga 20/21, Bundesliga 23/24) | ~700 matches, per-player event stats |

## Project structure

```
sportsbrain-mcp/
├── mcp_servers/
│   ├── player_stats_server.py      MCP Server #1: FBref player stats
│   ├── transfer_market_server.py   MCP Server #2: Transfermarkt valuations
│   └── match_events_server.py      MCP Server #3: Statsbomb match events
├── src/
│   ├── agent/
│   │   ├── graph.py                LangGraph ReAct agent
│   │   ├── tools.py                7 LangChain tool definitions
│   │   └── prompts.py              scouting system prompt
│   ├── cache/
│   │   └── redis_client.py         Redis caching layer
│   └── api/
│       └── main.py                 FastAPI REST endpoints
├── scripts/
│   ├── load_data.py                CSV/JSON to SQLite loader
│   ├── generate_golden_set.py      generates eval questions from DB
│   └── test_agent_traces.py        populates LangSmith with test traces
├── evaluation/
│   ├── golden_test_set.json        163 scouting questions + ground truth
│   ├── run_ragas.py                evaluation script
│   ├── agent_results.json          agent answers (generated)
│   └── results.md                  evaluation scores + breakdown
├── data/
│   ├── raw/                        downloaded CSVs (gitignored)
│   └── sportsbrain.db              SQLite database (gitignored)
├── k8s/                            Kubernetes manifests (Week 7)
├── .github/workflows/              CI/CD pipeline (Week 7)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Example queries

**Single source:**

> "How many goals does Erling Haaland have this season?"
> Calls `get_player_stats`, returns 27 goals in 35 matches for Manchester City.

**Multi-source:**

> "Find me PL forwards under 25 with 10+ goals and check their market valuations"
> Calls `search_players` for performance data, then `get_player_valuation` for each result. Combines stats and market value into one report.

**Comparison:**

> "Compare Haaland and Igor Thiago"
> Calls `compare_players` for side-by-side stats, then `get_player_valuation` for both. Highlights key differences: Haaland (27 goals, 200M valuation) vs Thiago (22 goals, valuation unavailable).

## Performance notes

The agent runs on Qwen3 8B locally via Ollama, so responses take 20-40 seconds on a laptop GPU (RTX 4070, 8GB VRAM). Cloud LLM APIs would reduce this to 2-5 seconds. The `/health` endpoint is instant, and cached tool results return in under 1ms from Redis.

## What I'd do differently

- **Broader Statsbomb coverage.** Free data is limited to specific teams (Barcelona in La Liga, Leverkusen in Bundesliga). Full API access would enable cross-league match event analysis.
- **Faster inference.** A cloud LLM like GPT-4o-mini would reduce query latency from 30s to 3s.
- **Stronger evaluation judge.** The built-in evaluation uses keyword overlap. A 70B model via HuggingFace would give more nuanced faithfulness scores.
- **Position data in Transfermarkt.** The Kaggle dataset has corrupted position/club columns. Cross-referencing with FBref at query time would fill this gap.
