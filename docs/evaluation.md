# RAG evaluation

## Decision and scope

Retain top-10 similarity retrieval with one continuation per original match. These results are sufficient to move development forward; further retrieval tuning is deferred while the remaining assignment requirements are completed. This is a practical project decision, not a claim that retrieval is optimal or that every answer is correct.

Two complete, live 12-question evaluations are preserved below. Both generated 12 answers successfully and scored all 48 question/metric combinations without execution failures. The measured path is the Research worker's document-only LCEL pipeline, not the full supervisor graph, web retrieval, frontend streaming, or deployed application.

## Dataset and method

- Fixed dataset: [rag_questions.json](../tests/fixtures/rag_questions.json), 12 questions across seven of the 15 corpus papers. It includes factual lookups, explanations, and one Raft/chain-replication comparison. Reference answers were checked against paper passages; source filenames and 1-based PDF pages are recorded in the dataset.
- Corpus/index: 15 distributed systems PDFs, 249 text-bearing pages, 1,891 chunks in local Chroma. Each PDF page is split independently into up to 800 characters with 120-character configured overlap.
- Corpus/query embeddings: local `sentence-transformers/all-MiniLM-L6-v2`, CPU, normalized vectors.
- Answer generation: Google `gemini-3.5-flash-lite`, using the same Research prompt in both runs. The SDK warns that the configured temperature is ignored because this model uses fixed sampling defaults.
- Evaluator: RAGAS `0.4.3`, OpenAI judge `gpt-4.1-mini`, and evaluation embeddings `text-embedding-3-small`. Evaluation embeddings are separate from the local corpus embeddings. Pinned dependencies and environment setup are in [requirements-evaluation.txt](../requirements-evaluation.txt).
- Metrics: `Faithfulness`, `ResponseRelevancy` (output key `answer_relevancy`), `LLMContextPrecisionWithReference`, and `LLMContextRecall` (output key `context_recall`). Means below are unweighted across all 12 questions.
- Collection uses [collect_rag_answers.py](../scripts/collect_rag_answers.py); scoring uses [evaluate_rag.py](../scripts/evaluate_rag.py). Reference answers are never supplied to the Research generator. Scoring receives the findings with inline citations, excluding Python's automatically appended source inventory.
- Gemini calls were paced with at least five seconds between worker starts using a run-specific wrapper. Cached corpus embeddings were warmed before timed retrieval. This pacing and warm-up are not built into the collector CLI.
- Baseline: top-10 similarity matches, no continuation expansion. Scoring completed at `2026-10-26T23:06:37Z`.
- Continuation: the same top-10 retrieval, followed by at most one continuation per match. Prefer the next chunk on the same page; if absent, try the first chunk of the immediately following PDF page in the same paper. Deduplicate, preserve original citation metadata, keep original matches first, and do not recursively expand. Maximum context count is 20 chunks. Scoring completed at `2026-10-27T01:34:22Z`.

## Aggregate results

| Metric | Baseline: top-10 | Top-10 + continuation | Difference |
| --- | ---: | ---: | ---: |
| Faithfulness | 0.9660 | 0.9644 | -0.0016 |
| Answer relevance | 0.7171 | 0.8939 | +0.1767 |
| Context precision | 0.6919 | 0.6709 | -0.0210 |
| Context recall | 0.9514 | 1.0000 | +0.0486 |

| Context/measurement | Baseline | Continuation |
| --- | ---: | ---: |
| Average retrieved chunks | 10.00 | 16.67 |
| Average retrieved text characters | 7,547.5 | 12,415.5 |
| Scoring wall-clock seconds | 312.68 | 385.11 |
| Successful generated/scored answers | 12/12 | 12/12 |

Context characters count source text only, excluding prompt and metadata overhead. The scoring durations measure the evaluator process inside the scoring function, not application response latency or time-to-first-token.

## Per-question results

Each cell shows **baseline / continuation**, rounded to three decimals. No failed or low-scoring questions were removed from the averages.

| Question ID | Faithfulness | Answer relevance | Context precision | Context recall |
| --- | ---: | ---: | ---: | ---: |
| raft-election-trigger | 1.000 / 1.000 | 0.984 / 0.863 | 0.789 / 0.938 | 1.000 / 1.000 |
| raft-randomized-timeouts | 1.000 / 1.000 | 0.964 / 0.965 | 0.844 / 0.869 | 1.000 / 1.000 |
| gfs-chunk-size-tradeoffs | 0.692 / 1.000 | 0.000 / 0.824 | 0.208 / 0.206 | 0.750 / 1.000 |
| gfs-read-path | 1.000 / 1.000 | 0.951 / 0.889 | 0.764 / 0.650 | 1.000 / 1.000 |
| gfs-metadata-persistence | 1.000 / 1.000 | 0.988 / 0.988 | 0.417 / 0.375 | 1.000 / 1.000 |
| spanner-truetime-interval | 0.900 / 1.000 | 0.986 / 0.825 | 0.886 / 0.886 | 1.000 / 1.000 |
| spanner-clock-diversity | 1.000 / 1.000 | 0.978 / 0.934 | 1.000 / 0.833 | 1.000 / 1.000 |
| mapreduce-programming-model | 1.000 / 1.000 | 0.968 / 0.968 | 0.644 / 0.624 | 1.000 / 1.000 |
| borg-master-availability | 1.000 / 1.000 | 0.924 / 0.924 | 0.836 / 0.836 | 1.000 / 1.000 |
| pbft-state-machine-requirements | 1.000 / 0.667 | 0.000 / 0.873 | 0.903 / 0.843 | 0.667 / 1.000 |
| chain-request-routing | 1.000 / 1.000 | 0.864 / 0.790 | 0.637 / 0.617 | 1.000 / 1.000 |
| raft-versus-chain-update-path | 1.000 / 0.906 | 0.000 / 0.885 | 0.375 / 0.375 | 1.000 / 1.000 |

## Precision-recall trade-off and failure analysis

Continuation adds nearby evidence that may complete a sentence or explanation split at a chunk/page boundary. In these runs, average context grew by about 64.5%. Answer relevance increased from 0.7171 to 0.8939, and context recall increased from 0.9514 to 1.0000. Context precision fell from 0.6919 to 0.6709; mean faithfulness was nearly unchanged (0.9660 to 0.9644). More context can introduce irrelevant material, additional input tokens, and cost. Appended continuation chunks also appear later in the ranking used by context precision.

The three baseline answers with zero relevance illustrate the trade-off:

- **GFS chunk-size trade-offs:** the needed chunk `gfs-sosp2003.pdf:p3:c5` ranked 12th, outside the baseline top 10. It explains persistent TCP connections, metadata size, and small-file hot spots. Continuation recovered it from a retrieved adjacent chunk. The new answer covers the missing drawback; faithfulness rose from 0.692 to 1.000 and relevance from 0.000 to 0.824.
- **PBFT requirements:** `Practical Byzantine Fault Tolerance.pdf:p3:c5` ranked third, but the continuation `p3:c6` ranked 81st. The latter supplies the shared initial state and total-order guarantee. The new answer includes both, and relevance rose to 0.873. Nevertheless, the faithfulness judge assigned 0.667. Inspection found the claims in the supplied passage, but individual judge statements/verdicts were not saved, so the discrepancy remains unresolved and the score is reported unchanged.
- **Raft versus chain replication:** the direct Raft update/reply passage ranked 15th, and the direct chain head-to-tail/reply passage ranked 186th. Continuation supplies some additional context but does not recover both direct passages. Relevance rose to 0.885, while faithfulness fell from 1.000 to 0.906. The new answer still contains caveats and potentially unsupported details; this case remains a limitation.

Offline investigation also tested similarity top-20 and MMR with k=10, fetch sizes 50/100, and lambda values 0.5/0.8. None recovered all the required passages for the three difficult questions. MMR sometimes displaced useful adjacent evidence. Those settings were not adopted. Paper/page coverage was used only as an offline diagnostic, not as a substitute for passage completeness or RAGAS scores.

The Research prompt requests uncertainty reporting. That can encourage verbose caveats, but the baseline gaps were real; suppressing caveats would risk unsupported answers. The prompt was held unchanged. RAGAS answer relevance multiplies similarity by zero when all generated evaluator responses classify the answer as noncommittal, which is a plausible explanation for baseline zeros. Those internal evaluator responses were not retained, so that explanation is not confirmed for each question.

## Artifacts and reproduction

The raw local artifacts are:

| Run | Collector output | Scorer output |
| --- | --- | --- |
| Baseline | `data/evaluation/full12_flash_lite_k10_answers.jsonl` | `data/evaluation/full12_flash_lite_k10_scores.json` |
| Continuation | `data/evaluation/full12_continuation_answers.jsonl` | `data/evaluation/full12_continuation_scores.json` |

Collector rows preserve generated responses, retrieved text, source metadata, references, provider/model, status, duration, and trace. Scorer files preserve full-precision per-question scores, averages, evaluator settings, timestamps, and scoring duration. The `data/` directory is ignored by Git: this report preserves both numeric evaluations, but the raw artifacts and corpus must be supplied separately for submission/reproduction. They are not bundled by these links or by a Git checkout.

After preparing the corpus/index, installing each environment's pinned dependencies, and configuring credentials, collection and scoring use this shape:

```powershell
# Live calls incur quota/cost. Use a fresh output path and obtain approval first.
.\.venv\Scripts\python.exe -m scripts.collect_rag_answers --run-live --output data/evaluation/new_answers.jsonl
.\data\evaluation\venv\Scripts\python.exe -m scripts.evaluate_rag --input data/evaluation/new_answers.jsonl --output data/evaluation/new_scores.json --judge-model gpt-4.1-mini --embedding-model text-embedding-3-small --run-live
```

Apply the pacing/warm-up described above when reproducing these runs. Current code reproduces the continuation strategy; the baseline was measured before continuation was added. Existing output files are never overwritten. No live evaluation runs as part of normal pytest.

## Limitations and remaining required measurements

- These are single runs on a small development set used to guide retrieval changes, not a held-out benchmark. There are no repeated-run confidence intervals; generation and LLM judge variability can influence differences. Model aliases may also change behavior over time.
- The test set covers seven papers and only one cross-paper comparison. It does not test web/current-events grounding or full multi-agent output. More questions are optional for now; completing the remaining architecture takes priority.
- RAGAS estimates grounding/relevance rather than proving factual correctness. The baseline cross-paper context recall was 1.000 despite missing explicit passages. The PBFT faithfulness discrepancy further motivates honest reporting and manual review rather than treating scores as ground truth.
- Citation IDs/pages are preserved and tested offline, but generated claim-level citation correctness is not comprehensively validated. PDFs can contain extraction errors, broken words, or imperfect table/column order.
- Per-question collector durations include any pacing wait introduced by the wrapper, so they are not clean retrieval/LLM latency measurements. Separate retrieval, generation, total response latency, TTFT, and Cloud Run cold/warm measurements remain required.
- Actual token usage, request counts, and billed/estimated cost per question were not captured. Those measurements remain required; the context character counts are not token counts or billing estimates.
- The generator was Gemini only. OpenAI was the evaluator, which does not count as demonstrating application routing across two generation providers. Provider quality/latency/cost comparison and exercised, inspectable cost/capability routing remain required.
- RAGAS emits deprecation warnings for the legacy metric/evaluation interface used with pinned version 0.4.3. Both runs completed; compatibility with a future version is not claimed.

## Development priorities

Retain the current retrieval strategy and these results. Do not spend on repeated retrieval tuning unless a concrete blocking defect appears. Prioritize the missing Code and Summary specialists, complete LangGraph execution and failure handling, inspectable two-provider routing, actual MCP sharing between agents, FastAPI/SSE and citation/trace UI, Cloud Run deployment, and the remaining evaluation/README/process-log evidence. The measurements above satisfy the recorded RAGAS experiment, not completion of the whole assignment.
