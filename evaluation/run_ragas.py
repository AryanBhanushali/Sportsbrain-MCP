"""
RAGAS evaluation script.
Runs the golden test set through the agent, evaluates answers.

Usage:
    python evaluation/run_ragas.py                # full run
    python evaluation/run_ragas.py --limit 10     # quick test
    python evaluation/run_ragas.py --eval-only    # skip agent, evaluate saved results
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

GOLDEN_SET = Path("evaluation/golden_test_set.json")
AGENT_RESULTS = Path("evaluation/agent_results.json")
RESULTS_MD = Path("evaluation/results.md")


def run_agent_on_questions(questions: list, limit: int = None) -> list:
    """Run the scouting agent on each question, capture answers and tool contexts."""
    from src.agent.graph import build_agent
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
    from src.agent.prompts import SCOUTING_SYSTEM_PROMPT

    print("Building agent...")
    agent = build_agent()

    results = []
    total = min(len(questions), limit) if limit else len(questions)

    for i, q in enumerate(questions[:total]):
        print(f"  [{i+1}/{total}] {q['question'][:70]}...", end=" ", flush=True)
        start = time.time()

        def run_single():
            return agent.invoke(
                {
                    "messages": [
                        SystemMessage(content=SCOUTING_SYSTEM_PROMPT),
                        HumanMessage(content=q["question"]),
                    ]
                },
                config={"recursion_limit": 12},
            )

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_single)
                output = future.result(timeout=120)  # 2 minute max per question

            answer = output["messages"][-1].content

            contexts = []
            for msg in output["messages"]:
                if isinstance(msg, ToolMessage):
                    contexts.append(msg.content[:2000])

            elapsed = time.time() - start
            print(f"✓ {elapsed:.1f}s")

            results.append({
                "id": q["id"],
                "question": q["question"],
                "ground_truth": q["ground_truth"],
                "category": q["category"],
                "answer": answer,
                "contexts": contexts,
                "latency_s": round(elapsed, 2),
            })

        except FuturesTimeout:
            elapsed = time.time() - start
            print(f"✗ TIMEOUT ({elapsed:.0f}s)")
            results.append({
                "id": q["id"],
                "question": q["question"],
                "ground_truth": q["ground_truth"],
                "category": q["category"],
                "answer": "ERROR: Timed out after 120s",
                "contexts": [],
                "latency_s": round(elapsed, 2),
            })

        except Exception as e:
            elapsed = time.time() - start
            print(f"✗ {e}")
            results.append({
                "id": q["id"],
                "question": q["question"],
                "ground_truth": q["ground_truth"],
                "category": q["category"],
                "answer": f"ERROR: {e}",
                "contexts": [],
                "latency_s": round(elapsed, 2),
            })

    return results


def try_ragas_evaluation(results: list) -> dict | None:
    """Try RAGAS evaluation. Returns scores dict or None if RAGAS unavailable."""
    try:
        from ragas import evaluate
        from ragas.metrics import Faithfulness, ResponseRelevancy
        from ragas import EvaluationDataset, SingleTurnSample
        from ragas.llms import LangchainLLMWrapper
        from langchain_ollama import ChatOllama
    except Exception as e:
        print(f"  RAGAS unavailable ({e}), using built-in evaluation")
        return None

    print("  Judge LLM: qwen3:8b via Ollama")

    evaluator_llm = LangchainLLMWrapper(
        ChatOllama(model="qwen3:8b", num_ctx=8192, temperature=0)
    )

    samples = []
    for r in results:
        if r["answer"].startswith("ERROR:"):
            continue
        samples.append(
            SingleTurnSample(
                user_input=r["question"],
                response=r["answer"],
                retrieved_contexts=r["contexts"] if r["contexts"] else ["No tool results"],
                reference=r["ground_truth"],
            )
        )

    if not samples:
        return None

    print(f"  Evaluating {len(samples)} samples with RAGAS...")
    dataset = EvaluationDataset(samples=samples)

    try:
        eval_result = evaluate(
            dataset=dataset,
            metrics=[Faithfulness(llm=evaluator_llm), ResponseRelevancy(llm=evaluator_llm)],
        )
        return {k: round(v, 4) for k, v in eval_result.items() if isinstance(v, (int, float))}
    except Exception as e:
        print(f"  RAGAS evaluation failed: {e}")
        return None


def builtin_evaluation(results: list) -> dict:
    """Built-in evaluation: keyword overlap, tool usage, latency analysis."""
    total = len(results)
    errors = sum(1 for r in results if r["answer"].startswith("ERROR:"))
    has_tools = sum(1 for r in results if r["contexts"])
    avg_latency = sum(r["latency_s"] for r in results) / total if total else 0
    avg_contexts = sum(len(r["contexts"]) for r in results) / total if total else 0

    # Faithfulness proxy: does the answer reference data from tool results?
    faithful_count = 0
    for r in results:
        if r["answer"].startswith("ERROR:") or not r["contexts"]:
            continue
        # Check if answer contains specific numbers/names from tool results
        context_text = " ".join(r["contexts"]).lower()
        answer_lower = r["answer"].lower()
        # Extract numbers from context and check if they appear in answer
        import re
        context_numbers = set(re.findall(r'\b\d+\b', context_text))
        answer_numbers = set(re.findall(r'\b\d+\b', answer_lower))
        number_overlap = len(context_numbers & answer_numbers)
        if number_overlap >= 2:
            faithful_count += 1

    # Relevancy: does the answer address the question's key terms?
    relevant_count = 0
    for r in results:
        if r["answer"].startswith("ERROR:"):
            continue
        gt_words = set(r["ground_truth"].lower().split())
        answer_words = set(r["answer"].lower().split())
        # Remove common stop words
        stop = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or", "has", "have", "this", "that", "with"}
        gt_key = gt_words - stop
        answer_key = answer_words - stop
        if gt_key:
            overlap = len(gt_key & answer_key) / len(gt_key)
            if overlap > 0.25:
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
    """Write results to results.md"""
    cat_stats = {}
    for r in results:
        cat = r["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"count": 0, "errors": 0, "total_latency": 0, "tool_calls": 0}
        cat_stats[cat]["count"] += 1
        if r["answer"].startswith("ERROR:"):
            cat_stats[cat]["errors"] += 1
        cat_stats[cat]["total_latency"] += r["latency_s"]
        cat_stats[cat]["tool_calls"] += len(r["contexts"])

    avg_latency = sum(r["latency_s"] for r in results) / len(results) if results else 0

    md = "# SportsBrain Evaluation Results\n\n"
    md += f"**Total questions**: {len(results)}  \n"
    md += f"**Average latency**: {avg_latency:.1f}s per query  \n"
    md += f"**Evaluation method**: {method}  \n"
    md += f"**LLM**: qwen3:8b via Ollama (local)  \n\n"

    md += "## Scores\n\n"
    md += "| Metric | Score |\n|--------|-------|\n"
    for k, v in scores.items():
        md += f"| {k} | {v} |\n"

    md += "\n## Per-Category Breakdown\n\n"
    md += "| Category | Count | Errors | Avg Latency | Avg Tool Calls |\n"
    md += "|----------|-------|--------|-------------|----------------|\n"
    for cat, s in sorted(cat_stats.items()):
        avg_lat = s["total_latency"] / s["count"] if s["count"] else 0
        avg_tools = s["tool_calls"] / s["count"] if s["count"] else 0
        md += f"| {cat} | {s['count']} | {s['errors']} | {avg_lat:.1f}s | {avg_tools:.1f} |\n"

    md += "\n## Sample Results (first 10)\n\n"
    for r in results[:10]:
        status = "✗ ERROR" if r["answer"].startswith("ERROR:") else "✓"
        md += f"### Q{r['id']}: {r['question']}\n"
        md += f"**Status**: {status} | **Latency**: {r['latency_s']}s | **Tools used**: {len(r['contexts'])}  \n"
        md += f"**Answer preview**: {r['answer'][:300]}  \n"
        md += f"**Expected**: {r['ground_truth'][:200]}  \n\n"

    with open(RESULTS_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\nResults written to {RESULTS_MD}")


def main():
    parser = argparse.ArgumentParser(description="Evaluation for SportsBrain")
    parser.add_argument("--limit", type=int, default=None, help="Max questions to evaluate")
    parser.add_argument("--eval-only", action="store_true", help="Skip agent, evaluate saved results")
    args = parser.parse_args()

    # Step 1: Load golden set
    if not GOLDEN_SET.exists():
        print(f"ERROR: {GOLDEN_SET} not found. Run: python scripts/generate_golden_set.py")
        return
    questions = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} golden questions")

    # Step 2: Run agent (or load saved results)
    if args.eval_only and AGENT_RESULTS.exists():
        print(f"Loading saved results from {AGENT_RESULTS}")
        results = json.loads(AGENT_RESULTS.read_text(encoding="utf-8"))
        if args.limit:
            results = results[:args.limit]
    else:
        results = run_agent_on_questions(questions, limit=args.limit)
        AGENT_RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nAgent results saved to {AGENT_RESULTS}")

    # Step 3: Try RAGAS first, fall back to built-in
    print("\nEvaluating answers...")
    ragas_scores = try_ragas_evaluation(results)

    if ragas_scores:
        print(f"\nRAGAS Scores: {ragas_scores}")
        write_results(ragas_scores, results, method="RAGAS (Faithfulness + ResponseRelevancy)")
    else:
        builtin_scores = builtin_evaluation(results)
        print(f"\nBuilt-in Scores: {builtin_scores}")
        write_results(builtin_scores, results, method="Built-in (keyword overlap + tool usage analysis)")


if __name__ == "__main__":
    main()
