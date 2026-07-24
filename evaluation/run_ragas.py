"""
Evaluation script (hardened).

Runs the golden test set through the MCP-wired agent and evaluates the answers.

Hardening vs. the original:
  - Absolute paths anchored to the project root (not working-directory relative),
    so it writes to the right place no matter where it's launched from.
  - Async runner (the agent is async) with a per-question timeout via
    asyncio.wait_for, replacing the old ThreadPoolExecutor.
  - agent_results.json is checkpointed after EVERY question, so an interrupted
    run leaves a valid partial file on disk instead of nothing.
  - results.md is written defensively: even if RAGAS scoring raises, the raw
    agent results and any computed scores are still flushed to disk.

Usage:
    python evaluation/run_ragas.py                # full run (clean start)
    python evaluation/run_ragas.py --limit 10     # quick smoke test
    python evaluation/run_ragas.py --eval-only    # skip agent, score saved results
"""

import sys
import json
import time
import asyncio
import argparse
from pathlib import Path

# ── Absolute paths anchored to the project root ───────────────────────
# evaluation/ lives directly under the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

GOLDEN_SET = PROJECT_ROOT / "evaluation" / "golden_test_set.json"
AGENT_RESULTS = PROJECT_ROOT / "evaluation" / "agent_results.json"
RESULTS_MD = PROJECT_ROOT / "evaluation" / "results.md"

PER_QUESTION_TIMEOUT = 120  # seconds


def _checkpoint(results: list):
    """Persist agent_results.json after each answer (crash-safe partial saves)."""
    AGENT_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    AGENT_RESULTS.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def run_agent_on_questions(questions: list, limit: int = None) -> list:
    """Run the MCP-wired agent on each question, checkpointing as we go."""
    from src.agent.graph import build_agent, run_query
    from langchain_core.messages import ToolMessage
    from langchain_core.messages import SystemMessage, HumanMessage
    from src.agent.prompts import SCOUTING_SYSTEM_PROMPT

    print("Building agent (loading tools from MCP servers)...")
    agent = await build_agent()

    results = []
    total = min(len(questions), limit) if limit else len(questions)

    for i, q in enumerate(questions[:total]):
        print(f"  [{i+1}/{total}] {q['question'][:70]}...", end=" ", flush=True)
        start = time.time()

        # We need the tool outputs (contexts) for RAGAS, so invoke the graph
        # directly here and pull ToolMessages out of the message history.
        async def _run():
            return await agent.ainvoke(
                {
                    "messages": [
                        SystemMessage(content=SCOUTING_SYSTEM_PROMPT),
                        HumanMessage(content=q["question"]),
                    ]
                },
                config={"recursion_limit": 12},
            )

        try:
            output = await asyncio.wait_for(_run(), timeout=PER_QUESTION_TIMEOUT)
            answer = output["messages"][-1].content
            contexts = [
                msg.content[:2000]
                for msg in output["messages"]
                if isinstance(msg, ToolMessage)
            ]
            elapsed = time.time() - start
            print(f"OK {elapsed:.1f}s")
            results.append({
                "id": q["id"], "question": q["question"],
                "ground_truth": q["ground_truth"], "category": q["category"],
                "answer": answer, "contexts": contexts,
                "latency_s": round(elapsed, 2),
            })

        except asyncio.TimeoutError:
            elapsed = time.time() - start
            print(f"TIMEOUT ({elapsed:.0f}s)")
            results.append({
                "id": q["id"], "question": q["question"],
                "ground_truth": q["ground_truth"], "category": q["category"],
                "answer": f"ERROR: Timed out after {PER_QUESTION_TIMEOUT}s",
                "contexts": [], "latency_s": round(elapsed, 2),
            })

        except Exception as e:
            elapsed = time.time() - start
            print(f"ERROR {e}")
            results.append({
                "id": q["id"], "question": q["question"],
                "ground_truth": q["ground_truth"], "category": q["category"],
                "answer": f"ERROR: {e}", "contexts": [],
                "latency_s": round(elapsed, 2),
            })

        # Checkpoint after EVERY question — partial progress survives a crash.
        _checkpoint(results)

    return results


def _context_to_text(ctx) -> str:
    """Flatten one 'contexts' entry to plain text.

    MCP tools return structured content — a ToolMessage's content is a list of
    typed blocks like [{'type': 'text', 'text': '...'}], not a plain string.
    Handle both that shape and the plain-string shape, so the scorer works
    regardless of how the tool result was serialized.
    """
    if isinstance(ctx, str):
        return ctx
    if isinstance(ctx, dict):
        return str(ctx.get("text", ctx))
    if isinstance(ctx, list):
        return " ".join(_context_to_text(x) for x in ctx)
    return str(ctx)


def _contexts_as_strings(contexts) -> list[str]:
    """Normalize a result's 'contexts' field into a list of plain strings."""
    if not contexts:
        return []
    return [_context_to_text(c) for c in contexts]


RAGAS_SCORES = PROJECT_ROOT / "evaluation" / "ragas_scores.json"


async def try_ragas_evaluation(results: list) -> dict | None:
    """Score each answer with RAGAS one sample at a time, checkpointing as we go.

    Per-sample (not batch) so that a crash resumes instead of restarting: each
    sample's Faithfulness + Answer Relevancy is written to ragas_scores.json
    immediately, and a rerun skips samples already scored. LangSmith tracing is
    disabled here to avoid the compression/memory overhead that destabilized
    the batch run.
    """
    # Disable LangSmith tracing for the scoring loop (kills the zstd memory
    # errors — we don't need traces of the judge calls, only the scores).
    import os as _os
    _os.environ["LANGCHAIN_TRACING_V2"] = "false"
    _os.environ["LANGSMITH_TRACING"] = "false"

    # ── Compatibility shim for RAGAS 0.4.3 (the latest release) ──────────────
    # RAGAS 0.4.3 eagerly imports a Vertex class from a langchain-community path
    # removed in 0.4.x. We judge with local Ollama and never use Vertex, so we
    # register a stand-in for that unused module so `import ragas` succeeds.
    # This unblocks a broken import only; it does not stub or influence scores.
    import sys as _sys
    import types as _types
    _dead = "langchain_community.chat_models.vertexai"
    if _dead not in _sys.modules:
        try:
            import langchain_community.chat_models.vertexai  # noqa: F401
        except ModuleNotFoundError:
            try:
                from langchain_google_vertexai import ChatVertexAI as _ChatVertexAI
            except Exception:
                class _ChatVertexAI:  # placeholder; never instantiated
                    pass
            _shim = _types.ModuleType(_dead)
            _shim.ChatVertexAI = _ChatVertexAI
            _sys.modules[_dead] = _shim

    try:
        from ragas import SingleTurnSample
        from ragas.metrics import Faithfulness, ResponseRelevancy
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_ollama import ChatOllama, OllamaEmbeddings
    except Exception as e:
        print(f"  RAGAS unavailable ({e}), using built-in evaluation")
        return None

    print("  Judge LLM: qwen3:8b via Ollama")
    evaluator_llm = LangchainLLMWrapper(
        ChatOllama(model="qwen3:8b", num_ctx=8192, temperature=0)
    )
    print("  Judge embeddings: qwen3-embedding:0.6b via Ollama")
    evaluator_emb = LangchainEmbeddingsWrapper(
        OllamaEmbeddings(model="qwen3-embedding:0.6b")
    )

    faithfulness = Faithfulness(llm=evaluator_llm)
    relevancy = ResponseRelevancy(llm=evaluator_llm, embeddings=evaluator_emb)

    # Only score non-error answers; keep the id so we can checkpoint/resume.
    to_score = [r for r in results if not r["answer"].startswith("ERROR:")]
    if not to_score:
        return None

    # Resume: load any per-sample scores already on disk.
    done: dict = {}
    if RAGAS_SCORES.exists():
        try:
            done = {str(d["id"]): d for d in json.loads(RAGAS_SCORES.read_text(encoding="utf-8"))}
            if done:
                print(f"  Resuming: {len(done)} samples already scored on disk")
        except Exception:
            done = {}

    print(f"  Scoring {len(to_score)} samples with RAGAS (per-sample, checkpointed)...")

    for i, r in enumerate(to_score):
        rid = str(r["id"])
        if rid in done:
            continue  # already scored in a previous run

        ctx = _contexts_as_strings(r["contexts"]) or ["No tool results"]
        sample = SingleTurnSample(
            user_input=r["question"],
            response=r["answer"],
            retrieved_contexts=ctx,
            reference=r["ground_truth"],
        )

        rec = {"id": r["id"], "faithfulness": None, "answer_relevancy": None}
        try:
            rec["faithfulness"] = float(await faithfulness.single_turn_ascore(sample))
        except Exception as e:
            print(f"    [{i+1}/{len(to_score)}] id={rid} faithfulness failed: {str(e)[:60]}")
        try:
            rec["answer_relevancy"] = float(await relevancy.single_turn_ascore(sample))
        except Exception as e:
            print(f"    [{i+1}/{len(to_score)}] id={rid} relevancy failed: {str(e)[:60]}")

        f = rec["faithfulness"]
        ar = rec["answer_relevancy"]
        print(f"    [{i+1}/{len(to_score)}] id={rid}  faithfulness={f}  answer_relevancy={ar}")

        done[rid] = rec
        # Checkpoint after every sample.
        RAGAS_SCORES.write_text(
            json.dumps(list(done.values()), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Aggregate (ignore NaN/None from failed judge parses).
    import math
    faith_vals = [d["faithfulness"] for d in done.values()
                  if isinstance(d["faithfulness"], (int, float)) and not math.isnan(d["faithfulness"])]
    rel_vals = [d["answer_relevancy"] for d in done.values()
                if isinstance(d["answer_relevancy"], (int, float)) and not math.isnan(d["answer_relevancy"])]

    if not faith_vals and not rel_vals:
        print("  RAGAS produced no valid scores (all failed/NaN)")
        return None

    scores = {}
    if faith_vals:
        scores["faithfulness"] = round(sum(faith_vals) / len(faith_vals), 4)
    if rel_vals:
        scores["answer_relevancy"] = round(sum(rel_vals) / len(rel_vals), 4)
    scores["faithfulness_scored_n"] = len(faith_vals)
    scores["answer_relevancy_scored_n"] = len(rel_vals)
    scores["samples_attempted"] = len(done)
    print(f"  RAGAS done: faithfulness over {len(faith_vals)} samples, "
          f"answer_relevancy over {len(rel_vals)} samples")
    return scores


def builtin_evaluation(results: list) -> dict:
    """Built-in evaluation: keyword overlap, tool usage, latency analysis."""
    import re
    total = len(results)
    errors = sum(1 for r in results if r["answer"].startswith("ERROR:"))
    has_tools = sum(1 for r in results if r["contexts"])
    avg_latency = sum(r["latency_s"] for r in results) / total if total else 0
    avg_contexts = sum(len(r["contexts"]) for r in results) / total if total else 0

    faithful_count = 0
    for r in results:
        if r["answer"].startswith("ERROR:") or not r["contexts"]:
            continue
        context_text = " ".join(_contexts_as_strings(r["contexts"])).lower()
        answer_lower = r["answer"].lower()
        context_numbers = set(re.findall(r'\b\d+\b', context_text))
        answer_numbers = set(re.findall(r'\b\d+\b', answer_lower))
        if len(context_numbers & answer_numbers) >= 2:
            faithful_count += 1

    relevant_count = 0
    stop = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
            "for", "of", "and", "or", "has", "have", "this", "that", "with"}
    for r in results:
        if r["answer"].startswith("ERROR:"):
            continue
        gt_key = set(r["ground_truth"].lower().split()) - stop
        answer_key = set(r["answer"].lower().split()) - stop
        if gt_key and len(gt_key & answer_key) / len(gt_key) > 0.25:
            relevant_count += 1

    valid = total - errors
    return {
        "total_questions": total,
        "successful_runs": valid,
        "errors": errors,
        "success_rate": round(valid / total, 4) if total else 0,
        "tool_usage_rate": round(has_tools / total, 4) if total else 0,
        "faithfulness_proxy": round(faithful_count / valid, 4) if valid else 0,
        "relevancy_proxy": round(relevant_count / valid, 4) if valid else 0,
        "avg_latency_s": round(avg_latency, 2),
        "avg_tool_calls_per_query": round(avg_contexts, 2),
    }


def write_results(scores: dict, results: list, method: str):
    """Write results.md. Written defensively so partial data still persists."""
    cat_stats = {}
    for r in results:
        cat = r["category"]
        s = cat_stats.setdefault(cat, {"count": 0, "errors": 0, "total_latency": 0, "tool_calls": 0})
        s["count"] += 1
        if r["answer"].startswith("ERROR:"):
            s["errors"] += 1
        s["total_latency"] += r["latency_s"]
        s["tool_calls"] += len(r["contexts"])

    avg_latency = sum(r["latency_s"] for r in results) / len(results) if results else 0

    md = "# SportsBrain Evaluation Results\n\n"
    md += f"**Total questions**: {len(results)}  \n"
    md += f"**Average latency**: {avg_latency:.1f}s per query  \n"
    md += f"**Evaluation method**: {method}  \n"
    md += "**Agent**: LangGraph ReAct, tools loaded from 3 MCP servers (stdio)  \n"
    md += "**LLM**: qwen3:8b via Ollama (local)  \n\n"

    md += "## Scores\n\n| Metric | Value |\n|--------|-------|\n"
    for k, v in scores.items():
        md += f"| {k} | {v} |\n"

    md += "\n## Per-Category Breakdown\n\n"
    md += "| Category | Count | Errors | Avg Latency | Avg Tool Calls |\n"
    md += "|----------|-------|--------|-------------|----------------|\n"
    for cat, s in sorted(cat_stats.items()):
        al = s["total_latency"] / s["count"] if s["count"] else 0
        at = s["tool_calls"] / s["count"] if s["count"] else 0
        md += f"| {cat} | {s['count']} | {s['errors']} | {al:.1f}s | {at:.1f} |\n"

    md += "\n## Sample Results (first 10)\n\n"
    for r in results[:10]:
        status = "ERROR" if r["answer"].startswith("ERROR:") else "OK"
        md += f"### Q{r['id']}: {r['question']}\n"
        md += f"**Status**: {status} | **Latency**: {r['latency_s']}s | **Tools used**: {len(r['contexts'])}  \n"
        md += f"**Answer preview**: {r['answer'][:300]}  \n"
        md += f"**Expected**: {r['ground_truth'][:200]}  \n\n"

    RESULTS_MD.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_MD.write_text(md, encoding="utf-8")
    print(f"\nResults written to {RESULTS_MD}")


async def _amain(args):
    # Step 1: load golden set
    if not GOLDEN_SET.exists():
        print(f"ERROR: {GOLDEN_SET} not found. Run: python scripts/generate_golden_set.py")
        return
    questions = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} golden questions")

    # Step 2: run agent (clean start) or load saved results
    if args.eval_only and AGENT_RESULTS.exists():
        print(f"Loading saved results from {AGENT_RESULTS}")
        results = json.loads(AGENT_RESULTS.read_text(encoding="utf-8"))
        if args.limit:
            results = results[:args.limit]
    else:
        results = await run_agent_on_questions(questions, limit=args.limit)
        print(f"\nAgent results saved to {AGENT_RESULTS}")

    # Step 3: score — RAGAS first, else built-in. Defensive: always write
    # results.md, even if RAGAS raises, so nothing is lost.
    print("\nEvaluating answers...")
    try:
        ragas_scores = await try_ragas_evaluation(results)
    except Exception as e:
        print(f"  RAGAS raised unexpectedly ({e}); falling back to built-in")
        ragas_scores = None

    if ragas_scores:
        print(f"\nRAGAS Scores: {ragas_scores}")
        write_results(ragas_scores, results, method="RAGAS (Faithfulness + Answer Relevancy, qwen3:8b judge)")
    else:
        builtin_scores = builtin_evaluation(results)
        print(f"\nBuilt-in Scores: {builtin_scores}")
        write_results(builtin_scores, results, method="Built-in (keyword overlap + tool usage analysis)")


def main():
    parser = argparse.ArgumentParser(description="Evaluation for SportsBrain (MCP-wired agent)")
    parser.add_argument("--limit", type=int, default=None, help="Max questions to evaluate")
    parser.add_argument("--eval-only", action="store_true", help="Skip agent, score saved results")
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()