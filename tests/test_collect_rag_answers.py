"""Test evaluation collection without embeddings, network, or generation APIs."""

import asyncio
from datetime import datetime
import json
from unittest.mock import AsyncMock

import pytest

from scripts import collect_rag_answers as collector


@pytest.fixture
def collection_case(tmp_path, monkeypatch):
    questions = [
        {"id": "first", "question": "How does Raft elect a leader?",
         "reference": "Reference answer kept out of the prompt",
         "sources": [{"file": "raft.pdf", "pages": [6]}]},
        {"id": "second", "question": "How does GFS locate chunks?",
         "reference": "Another reference answer",
         "sources": [{"file": "gfs-sosp2003.pdf", "pages": [3]}]},
    ]
    dataset = tmp_path / "questions.json"
    dataset.write_text(json.dumps(questions), encoding="utf-8")
    source = {
        "source_id": "raft.pdf:p6:c1", "source_kind": "document", "title": "raft",
        "source": "raft.pdf", "content": "Evidence with Unicode: café",
        "metadata": {"page": 6, "chunk_id": "raft.pdf:p6:c1"},
    }
    update = {
        "results": [{"content": "Finding [raft.pdf:p6:c1]", "sources": [source],
                     "success": True, "error": None}],
        "trace": [{"node": "research", "action": "research_completed"}],
    }
    node = AsyncMock(return_value=update)
    monkeypatch.setattr(collector, "research_node", node)
    monkeypatch.setattr(collector, "get_agent_provider_info",
                        lambda role: ("mock-provider", "mock-model"))
    return questions, dataset, tmp_path / "results" / "answers.jsonl", update, node


def test_load_all_and_select_questions(collection_case):
    questions, dataset, _, _, _ = collection_case
    assert collector.load_questions(dataset) == questions
    assert collector.load_questions(dataset, ["second"]) == questions[1:]
    with pytest.raises(ValueError, match="Unknown question IDs"):
        collector.load_questions(dataset, ["missing"])


@pytest.mark.parametrize("data", [
    [], {}, [None],
    [{"id": "q", "question": " ", "reference": "answer", "sources": [{}]}],
    [{"id": "q", "question": "question", "reference": "answer", "sources": []}],
    [{"id": "q", "question": "question", "reference": "answer", "sources": [{}]}] * 2,
])
def test_invalid_dataset_rejected_before_generation(collection_case, data):
    _, dataset, _, _, node = collection_case
    dataset.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        collector.load_questions(dataset)
    node.assert_not_called()


@pytest.mark.asyncio
async def test_saves_evidence_and_keeps_references_out_of_task(collection_case):
    questions, _, output, update, node = collection_case
    assert await collector.collect_answers(questions[:1], output) == 0
    node.assert_awaited_once_with({
        "user_query": questions[0]["question"],
        "source_policy": "documents",
        "current_task": {"agent": "research", "instruction": questions[0]["question"],
                         "retrieval_mode": "documents"},
    })
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["id"] == questions[0]["id"]
    assert row["user_input"] == questions[0]["question"]
    assert row["reference"] == questions[0]["reference"]
    assert row["reference_sources"] == questions[0]["sources"]
    assert row["response"] == update["results"][0]["content"]
    assert row["sources"] == update["results"][0]["sources"]
    assert row["retrieved_contexts"] == ["Evidence with Unicode: café"]
    assert row["trace"] == update["trace"]
    assert row["provider"] == "mock-provider"
    assert row["model"] == "mock-model"
    assert row["retrieval_mode"] == "documents"
    assert row["success"] is True and row["error"] is None
    assert row["duration_seconds"] >= 0
    assert row["measurements"]["outcome"] == "worker_success"
    assert row["measurements"]["generation_calls"] == 0
    assert datetime.fromisoformat(row["completed_at"]).utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_worker_failure_is_saved_and_next_question_runs(collection_case):
    questions, _, output, update, node = collection_case
    failure = {"results": [{"content": "", "sources": update["results"][0]["sources"],
                            "success": False, "error": "Research operation timed out"}],
               "trace": []}
    node.side_effect = [failure, update]
    assert await collector.collect_answers(questions, output) == 1
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["id"] for row in rows] == ["first", "second"]
    assert rows[0]["error"] == "Research operation timed out"
    assert rows[0]["sources"] == failure["results"][0]["sources"]
    assert rows[1]["success"] is True
    assert node.await_count == 2


@pytest.mark.asyncio
async def test_existing_output_is_not_overwritten(collection_case):
    questions, _, output, _, node = collection_case
    output.parent.mkdir()
    output.write_text("Existing results", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await collector.collect_answers(questions, output)
    assert output.read_text(encoding="utf-8") == "Existing results"
    node.assert_not_called()


@pytest.mark.asyncio
async def test_interruption_preserves_completed_rows(collection_case):
    questions, _, output, update, node = collection_case

    async def respond(state):
        if state["user_query"] == questions[1]["question"]:
            rows = output.read_text(encoding="utf-8").splitlines()
            assert len(rows) == 1 and json.loads(rows[0])["id"] == "first"
            raise asyncio.CancelledError()
        return update

    node.side_effect = respond
    with pytest.raises(asyncio.CancelledError):
        await collector.collect_answers(questions, output)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1


def test_cli_requires_explicit_live_flag(collection_case, monkeypatch):
    _, _, _, _, node = collection_case
    monkeypatch.setattr("sys.argv", ["collect_rag_answers"])
    with pytest.raises(SystemExit) as exc:
        collector.main()
    assert exc.value.code == 2
    node.assert_not_called()


@pytest.mark.parametrize("failures", [0, 1])
def test_cli_selection_and_failure_exit(collection_case, monkeypatch, failures):
    questions, dataset, output, _, node = collection_case
    collect = AsyncMock(return_value=failures)
    monkeypatch.setattr(collector, "collect_answers", collect)
    monkeypatch.setattr("sys.argv", [
        "collect_rag_answers", "--run-live", "--questions", str(dataset),
        "--output", str(output), "--ids", "second",
    ])
    if failures:
        with pytest.raises(SystemExit) as exc:
            collector.main()
        assert exc.value.code == 1
    else:
        collector.main()
    collect.assert_awaited_once_with(questions[1:], output)
    node.assert_not_called()
