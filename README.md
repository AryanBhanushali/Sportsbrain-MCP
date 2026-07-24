# SportsBrain - MCP-Powered Football Scouting Platform

A unified scouting agent that exposes football data sources as MCP servers, answers complex plain-English queries across player stats, transfer valuations, and match events, and proves answer quality with a rigorous evaluation pipeline.

The agent answers queries like "Find me Premier League forwards under 25 with 10+ goals and check their market valuations" by calling the right tools across multiple MCP servers and synthesizing a scouting report.

## The problem

Football scouts query multiple data sources manually: one for match stats, one for transfer valuations, one for injury histories. Each query takes 10-15 minutes across different UIs. This system exposes each data source as an MCP server, lets scouts ask complex questions in plain English through a web UI, and proves the quality of its answers with an evaluation pipeline.

## Architecture

```
MCP Server 1: Player Stats    (FBref -> SQLite -> 3 tools)
MCP Server 2: Transfer Market (Transfermarkt -> SQLite -> 3 tools)
MCP Server 3: Match Events    (Statsbomb -> SQLite -> 3 tools)
        |
        |  launched as stdio subprocesses; tools loaded via
        |  MultiServerMCPClient (langchain-mcp-adapters)
        v
LangGraph ReAct Agent --> loads all 9 tools from the MCP servers
        |                  plans multi-step queries across sources
        |                  Qwen3 8B via Ollama (local)
        v
Redis --> caches tool results inside each MCP server
        |
        v
LangSmith --> traces every run (latency, tokens, tools called)
        |
        v
Evaluation --> 163-question golden test set, scored with RAGAS
        |      (Faithfulness + Answer Relevancy, local judge)
        v
FastAPI + web UI --> containerized REST API + scouting-desk frontend
        |
        v
Docker -> Amazon ECR -> AWS EKS (Kubernetes), with a GitHub Actions pipeline
```

## How it works

**MCP Servers:** Three MCP servers expose football data through standardized tool interfaces (3 tools each, 9 total). Server 1 wraps FBref season stats (2,839 players across Big 5 leagues). Server 2 wraps Transfermarkt valuations (508 top players with career value history). Server 3 wraps Statsbomb match events (per-match goals, passes, tackles, dribbles from La Liga 2020/21 and Bundesliga 2023/24). All data lives in a single SQLite database with indexed tables.

**LangGraph Agent:** A ReAct agent bound to Qwen3 8B via Ollama. At startup it launches the three MCP servers as stdio subprocesses and loads their 9 tools through a `MultiServerMCPClient` (from `langchain-mcp-adapters`) — so every tool call travels the MCP protocol rather than calling the database directly. The agent receives a natural language scouting query, decides which tools to call and in what order, executes them, and synthesizes the results into a scouting report. Multi-source queries (stats + valuations) require multiple tool calls across different servers, planned by the agent.

**Redis Cache:** Each MCP server checks Redis before hitting SQLite. Player stats cache for 1 hour, transfer valuations for 24 hours. Repeated tool calls return instantly from cache.

**LangSmith Observability:** Every agent run is traced with full message history, latency per step, token usage, and tool selection decisions.

**Web UI:** A single-page scouting desk (served by FastAPI at `/`) lets non-technical users type plain-English queries and get back a formatted scouting report, with a live status indicator and an example-query gallery.

## Evaluation results

Evaluated on a 163-question golden test set generated deterministically from actual database data. Operational metrics cover all 163 questions; answer-quality metrics use RAGAS (Faithfulness + Answer Relevancy) with a local Qwen3 8B judge and Qwen3 embeddings.

| Metric                 | Score           | Notes                                       |
| ---------------------- | --------------- | ------------------------------------------- |
| Success Rate           | 99.4% (162/163) | 1 timeout (agent tool-loop, capped at 120s) |
| Tool Usage Rate        | 96.3%           | fraction of answers grounded in tool output |
| RAGAS Faithfulness     | 0.660           | over 159 samples (3 judge-parse failures)   |
| RAGAS Answer Relevancy | 0.832           | over 162 samples                            |
| Avg Latency            | 25.8s           | local 8B model on laptop GPU (RTX 4070)     |

Notes on methodology:

- **RAGAS scoring uses a local judge.** Faithfulness and Answer Relevancy were computed with RAGAS using Qwen3 8B (via Ollama) as the judge LLM and `qwen3-embedding:0.6b` for relevancy — no cloud API. A local 8B judge is a strict grader, and a handful of samples fail to parse and are excluded from the average (159 of 162 scored for faithfulness).
- **Per-sample and checkpointed.** Each question is scored individually and written to `evaluation/ragas_scores.json`, so the ~162-sample run is resumable.

Full breakdown by category in [`evaluation/results.md`](evaluation/results.md).

## Stack

| Layer         | Technology                                                     |
| ------------- | -------------------------------------------------------------- |
| Agent         | LangGraph ReAct agent, 9 tools loaded from MCP servers         |
| MCP           | langchain-mcp-adapters (MultiServerMCPClient, stdio)           |
| LLM           | Qwen3 8B via Ollama (local, no API costs)                      |
| Data Layer    | 3 MCP servers backed by SQLite                                 |
| Cache         | Redis 8                                                        |
| Observability | LangSmith                                                      |
| Evaluation    | 163-question golden set; RAGAS Faithfulness + Answer Relevancy |
| API + UI      | FastAPI + single-page scouting-desk frontend                   |
| Deployment    | Docker, Amazon ECR, AWS EKS (Kubernetes), GitHub Actions CI/CD |

## Running it

### Prerequisites

- Python 3.12
- Docker Desktop
- Ollama with `qwen3:8b` (and `qwen3-embedding:0.6b` for evaluation)
- Node.js (for MCP Inspector, optional)

### Setup

1. Clone the repo:

```bash
git clone https://github.com/AryanBhanushali/Sportsbrain-MCP.git
cd Sportsbrain-MCP
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
python scripts/load_data.py --all
```

7. Pull the models:

```bash
ollama pull qwen3:8b
ollama pull qwen3-embedding:0.6b   # only needed for evaluation
```

### Running the agent (CLI)

```bash
python -m src.agent.graph
# Example: Scout > Find me PL forwards under 25 with 10+ goals and check their valuations
```

### Running the API + web UI

```bash
uvicorn src.api.main:app
# Web UI:  http://localhost:8000/
# API:     POST http://localhost:8000/query {"question": "Compare Haaland and Igor Thiago"}
```

### Running with Docker

```bash
docker compose up --build
# API + UI at http://localhost:8000
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
python evaluation/run_ragas.py              # Run agent + RAGAS scoring (resumable)
python evaluation/run_ragas.py --eval-only  # Re-score existing answers only
python evaluation/run_ragas.py --limit 10   # Quick test on 10 questions
```

## Deployment (AWS EKS + CI/CD)

The app is containerized and was deployed to AWS EKS to validate the cloud path, then torn down. See [`docs/`](docs/) for deployment proof (cluster, pods, health, UI).

- **Image:** built from the Dockerfile (with the SQLite DB baked in), pushed to Amazon ECR.
- **Kubernetes:** `k8s/` holds the app + Redis Deployments, a LoadBalancer Service, ConfigMap, and Secret. Deployed on a single t3.medium node; pods healthy and `/health` served through the cluster.
- **CI/CD:** `.github/workflows/deploy.yml` defines the full build -> ECR -> EKS rollout pipeline, set to manual dispatch as a demonstration.
- **Inference note:** the t3.medium node is CPU-only, so the cluster deployment demonstrates the app serving (`/health`, UI, Redis connectivity); live `/query` inference requires pointing `OLLAMA_BASE_URL` at a GPU/cloud LLM backend.

## API

| Endpoint  | Method | Description                                             |
| --------- | ------ | ------------------------------------------------------- |
| `/`       | GET    | Scouting-desk web UI                                    |
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
│   ├── player_stats_server.py      MCP Server #1: FBref player stats (3 tools)
│   ├── transfer_market_server.py   MCP Server #2: Transfermarkt valuations (3 tools)
│   └── match_events_server.py      MCP Server #3: Statsbomb match events (3 tools)
├── src/
│   ├── agent/
│   │   ├── graph.py                LangGraph ReAct agent; loads tools from MCP servers
│   │   └── prompts.py              scouting system prompt
│   ├── cache/
│   │   └── redis_client.py         Redis caching layer
│   └── api/
│       └── main.py                 FastAPI REST endpoints + UI
├── static/
│   └── index.html                  scouting-desk web UI
├── scripts/
│   ├── load_data.py                CSV/JSON to SQLite loader
│   ├── generate_golden_set.py      generates eval questions from DB
│   └── test_agent_traces.py        populates LangSmith with test traces
├── evaluation/
│   ├── golden_test_set.json        163 scouting questions + ground truth
│   ├── run_ragas.py                evaluation script (agent run + RAGAS scoring)
│   ├── agent_results.json          agent answers (generated)
│   ├── ragas_scores.json           per-sample RAGAS scores (generated)
│   └── results.md                  evaluation scores + breakdown
├── data/
│   ├── raw/                        downloaded CSVs (gitignored)
│   └── sportsbrain.db              SQLite database (gitignored)
├── docs/                           deployment proof screenshots
├── k8s/                            Kubernetes manifests
├── .github/workflows/              CI/CD pipeline
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
> Calls `search_players` (player-stats server) for performance data, then `get_player_valuation` (transfer-market server) for each result. Combines stats and market value into one report.

**Comparison:**

> "Compare Haaland and Igor Thiago"
> Calls `compare_players` for side-by-side stats, then `get_player_valuation` for both.

## Performance notes

The agent runs on Qwen3 8B locally via Ollama, so responses take 20-40 seconds on a laptop GPU (RTX 4070, 8GB VRAM). Cloud LLM APIs would reduce this to 2-5 seconds. The `/health` endpoint is instant, and cached tool results return in under 1ms from Redis.

## What I'd do differently

- **Broader Statsbomb coverage.** Free data is limited to specific teams (Barcelona in La Liga, Leverkusen in Bundesliga). Full API access would enable cross-league match event analysis.
- **Faster inference.** A cloud LLM like GPT-4o-mini would reduce query latency from ~26s to a few seconds, and would also make RAGAS evaluation dramatically faster (local 8B judging of 162 samples is slow).
- **Stronger evaluation judge.** RAGAS scoring here uses a local Qwen3 8B judge, which is strict and occasionally fails to parse a sample. A larger or hosted judge model would give more stable faithfulness scores.
- **Position data in Transfermarkt.** The Kaggle dataset has corrupted position/club columns. Cross-referencing with FBref at query time would fill this gap.
