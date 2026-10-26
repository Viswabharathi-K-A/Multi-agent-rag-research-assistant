"""Collect Research-worker outputs for later RAGAS scoring; no scoring runs here.

From the repository root, after approving live generation costs:
python -m scripts.collect_rag_answers --run-live --ids raft-election-trigger

Omit --ids to collect all questions. Choose a new --output path for each run.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from app.agents.research import research_node
from app.config import PROJECT_ROOT
from app.llm import get_agent_provider_info


def load_questions(path: Path, ids: list[str] | None = None) -> list[dict]:
    """Validate the fixed dataset and select IDs before any generation calls."""
    questions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions:
        raise ValueError("Question dataset must be a nonempty JSON list")
    seen = set()
    for question in questions:
        if not isinstance(question, dict) or any(
            not isinstance(question.get(key), str) or not question[key].strip()
            for key in ("id", "question", "reference")
        ):
            raise ValueError("Each question needs nonempty id, question, and reference strings")
        if not isinstance(question.get("sources"), list) or not question["sources"]:
            raise ValueError("Each question needs reference sources")
        if question["id"] in seen:
            raise ValueError(f"Duplicate question ID: {question['id']}")
        seen.add(question["id"])
    if ids:
        unknown = set(ids) - seen
        if unknown:
            raise ValueError(f"Unknown question IDs: {', '.join(sorted(unknown))}")
        questions = [question for question in questions if question["id"] in ids]
    return questions


async def collect_answers(questions: list[dict], output_path: Path) -> int:
    """Run sequential document-only tasks and save each result immediately.

    JSONL keeps completed rows readable if a later request is interrupted. An
    existing output is never overwritten. Worker failures are saved, not retried.
    """
    provider, model = get_agent_provider_info("research")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    with output_path.open("x", encoding="utf-8") as output:
        for question in questions:
            started = perf_counter()
            update = await research_node({
                "user_query": question["question"],
                "current_task": {
                    "agent": "research", "instruction": question["question"],
                    "retrieval_mode": "documents",
                },
            })
            elapsed = perf_counter() - started
            result = update["results"][0]
            sources = result.get("sources", [])
            row = {
                "id": question["id"], "user_input": question["question"],
                "reference": question["reference"], "reference_sources": question["sources"],
                "response": result["content"],
                "retrieved_contexts": [source["content"] for source in sources],
                "sources": sources, "success": result["success"], "error": result["error"],
                "provider": provider, "model": model, "retrieval_mode": "documents",
                "duration_seconds": elapsed,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "trace": update["trace"],
            }
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            failures += int(not result["success"])
            status = "ok" if result["success"] else "failed"
            print(f"{question['id']}: {status} ({elapsed:.2f}s)", flush=True)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path,
                        default=PROJECT_ROOT / "tests/fixtures/rag_questions.json")
    parser.add_argument("--output", type=Path,
                        default=PROJECT_ROOT / "data/evaluation/rag_answers.jsonl")
    parser.add_argument("--ids", nargs="+", help="Question IDs to run; default: all")
    parser.add_argument("--run-live", action="store_true",
                        help="Explicitly enable generation calls that may incur API costs")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Generation is disabled; use --run-live only after approving API costs")
    questions = load_questions(args.questions, args.ids)
    failures = asyncio.run(collect_answers(questions, args.output))
    print(f"Saved {len(questions)} results to {args.output}; {failures} failed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
