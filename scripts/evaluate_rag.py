"""Score saved Research answers in the separate evaluation environment.

Run from the project root with data/evaluation/venv/Scripts/python.exe:
  -m scripts.evaluate_rag --input data/evaluation/rag_answers.jsonl
  --output data/evaluation/ragas_scores.json --judge-model MODEL
  --embedding-model MODEL --run-live

Live scoring uses OpenAI generation and embedding APIs. Model IDs must be chosen
explicitly and API costs approved first. This script never regenerates answers.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from time import perf_counter


def load_answers(path: Path) -> list[dict]:
    """Read collector JSONL and reject malformed or duplicate evaluation rows."""
    rows = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            raise ValueError("Each result needs a nonempty question ID")
        if row["id"] in seen:
            raise ValueError(f"Duplicate question ID: {row['id']}")
        seen.add(row["id"])
        if not isinstance(row.get("success"), bool):
            raise ValueError(f"Missing success status: {row['id']}")
        if row["success"]:
            for key in ("user_input", "reference", "response"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f"Missing {key}: {row['id']}")
            contexts = row.get("retrieved_contexts")
            if not isinstance(contexts, list) or not contexts or any(
                not isinstance(text, str) or not text.strip() for text in contexts
            ):
                raise ValueError(f"Missing retrieved contexts: {row['id']}")
        rows.append(row)
    if not any(row["success"] for row in rows):
        raise ValueError("No successful answers to evaluate")
    return rows


def score_answers(rows: list[dict], judge_model: str, embedding_model: str) -> dict:
    """Score successful rows; report failed generation IDs separately from means."""
    # Lazy imports allow validation and --help without RAGAS or API credentials.
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import (
        Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy,
    )
    from ragas.run_config import RunConfig

    successful = [row for row in rows if row["success"]]
    samples = []
    for row in successful:
        # The collector preserves the full worker output. Score the findings,
        # excluding Python's appended inventory of all retrieved sources.
        response = row["response"].split(
            "\n\nRetrieved sources (not independent claim verification):\n", 1
        )[0].strip()
        if not response:
            raise ValueError(f"No findings before source appendix: {row['id']}")
        samples.append({
            "user_input": row["user_input"], "response": response,
            "reference": row["reference"], "retrieved_contexts": row["retrieved_contexts"],
        })
    metrics = [Faithfulness(), ResponseRelevancy(),
               LLMContextPrecisionWithReference(), LLMContextRecall()]
    started = perf_counter()
    result = evaluate(
        dataset=EvaluationDataset.from_list(samples), metrics=metrics,
        llm=ChatOpenAI(model=judge_model, temperature=0, max_retries=0, timeout=120),
        embeddings=OpenAIEmbeddings(model=embedding_model, max_retries=0),
        run_config=RunConfig(max_workers=1, max_retries=1, timeout=120),
        raise_exceptions=True, show_progress=True,
    )
    if len(result.scores) != len(successful):
        raise ValueError("RAGAS score count differs from answer count")
    scores = []
    for row, values in zip(successful, result.scores):
        values = {metric.name: float(values[metric.name]) for metric in metrics}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError(f"RAGAS returned a non-finite score: {row['id']}")
        scores.append({"id": row["id"], "metrics": values})
    return {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "judge_provider": "openai", "judge_model": judge_model,
        "embedding_model": embedding_model, "duration_seconds": perf_counter() - started,
        "total_questions": len(rows), "scored_questions": len(scores),
        "failed_generation_ids": [row["id"] for row in rows if not row["success"]],
        "mean_metrics": {
            metric.name: sum(row["metrics"][metric.name] for row in scores) / len(scores)
            for metric in metrics
        },
        "scores": scores,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--run-live", action="store_true")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Scoring is disabled; --run-live requires prior API cost approval")
    rows = load_answers(args.input)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required for evaluator and embedding calls")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        report = score_answers(rows, args.judge_model, args.embedding_model)
        report["input_file"] = str(args.input)
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    print(f"Scored {report['scored_questions']}/{report['total_questions']} answers; saved {args.output}")


if __name__ == "__main__":
    main()
