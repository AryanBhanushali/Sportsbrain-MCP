"""
FastAPI endpoints for SportsBrain.
Serves the scouting agent via a REST API and a browser UI for non-technical users.

The agent loads its tools from the three MCP servers (spawned as stdio
subprocesses at startup), so the query path runs through the MCP protocol.

Run locally: uvicorn src.api.main:app --reload
  UI:  http://localhost:8000/
  API: POST http://localhost:8000/query  {"question": "..."}
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.agent.graph import build_agent, run_query
from src.cache.redis_client import get_cache_stats

# static/ lives at the project root (same level as src/, data/)
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

app = FastAPI(
    title="SportsBrain",
    description="MCP-powered football scouting platform",
    version="1.0.0",
)

agent = None


@app.on_event("startup")
async def startup():
    global agent
    # build_agent() is async: it launches the MCP servers and loads their tools.
    agent = await build_agent()


class QueryRequest(BaseModel):
    question: str = Field(..., example="Find me Premier League forwards under 25 with 10+ goals")


class QueryResponse(BaseModel):
    answer: str
    latency_s: float


@app.get("/")
def index():
    """Serve the scouting-desk UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    cache = get_cache_stats()
    return {
        "status": "ok",
        "agent_loaded": agent is not None,
        "cache": cache,
    }


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    start = time.time()
    answer = await run_query(agent, req.question)
    elapsed = round(time.time() - start, 2)
    return QueryResponse(answer=answer, latency_s=elapsed)