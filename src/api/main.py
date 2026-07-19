"""
FastAPI endpoints for SportsBrain.
Serves the scouting agent via REST API.

Run locally: uvicorn src.api.main:app --reload
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.agent.graph import build_agent, run_query
from src.cache.redis_client import get_cache_stats

app = FastAPI(
    title="SportsBrain",
    description="MCP-powered football scouting platform",
    version="1.0.0",
)

agent = None


@app.on_event("startup")
async def startup():
    global agent
    agent = build_agent()


class QueryRequest(BaseModel):
    question: str = Field(..., example="Find me Premier League forwards under 25 with 10+ goals")


class QueryResponse(BaseModel):
    answer: str
    latency_s: float


@app.get("/health")
def health():
    cache = get_cache_stats()
    return {
        "status": "ok",
        "agent_loaded": agent is not None,
        "cache": cache,
    }


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    start = time.time()
    answer = run_query(agent, req.question)
    elapsed = round(time.time() - start, 2)
    return QueryResponse(answer=answer, latency_s=elapsed)
