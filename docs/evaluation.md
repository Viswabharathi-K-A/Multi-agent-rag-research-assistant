# RAG evaluation

## Decision and scope

Retain top-10 similarity retrieval with one continuation per original match. These results are sufficient to move development forward; further retrieval tuning is deferred while the remaining assignment requirements are completed. This is a practical project decision, not a claim that retrieval is optimal or that every answer is correct.

Two complete, live 12-question evaluations are preserved below. Both generated 12 answers successfully and scored all 48 question/metric combinations without execution failures. The measured path is the Research worker's document-only LCEL pipeline, not the full supervisor graph, web retrieval, frontend streaming, or deployed application.

## Dataset and method

- Fixed dataset: [rag_questions.json](../tests/fixtures/rag_questions.json), 12 questions across seven of the 15 corpus papers. It includes factual lookups, explanations, and one Raft/chain-replication comparison. Reference answers were checked against paper passages; source filenames and 1-based PDF pages are recorded in the dataset.
- Corpus/index: 15 distributed systems PDFs, 249 text-bearing pages, 1,891 chunks in local Chroma. Each PDF page is split independently into up to 800 characters with 120-character configured overlap.
- Corpus/query embeddings: local `sentence-transformers/all-MiniLM-L6-v2`, CPU, normalized vectors.
- Answer generation: Google `gemini-3.5-flash-lite`, using the same Research prompt in both runs. The SDK warns that the configured temperature is ignored because this model uses fixed sampling defaults.
- Evaluator: RAGAS `0.4.3`, OpenAI judge `gpt-4.1-mini`, and evaluation embeddings `text-embedding-3-small`. Evaluation embeddings are separate from the local corpus embeddings. Pinned dependencies and environment setup are in [requirements.txt](../requirements.txt).
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

After preparing the corpus/index, installing the shared environment's pinned dependencies, and configuring credentials, collection and scoring use this shape:

```powershell
# Live calls incur quota/cost. Use a fresh output path and obtain approval first.
.\.venv\Scripts\python.exe -m scripts.collect_rag_answers --run-live --output data/evaluation/new_answers.jsonl
.\.venv\Scripts\python.exe -m scripts.evaluate_rag --input data/evaluation/new_answers.jsonl --output data/evaluation/new_scores.json --judge-model gpt-4.1-mini --embedding-model text-embedding-3-small --run-live
```

Apply the pacing/warm-up described above when reproducing these runs. Current code reproduces the continuation strategy; the baseline was measured before continuation was added. Existing output files are never overwritten. No live evaluation runs as part of normal pytest.

## Dependency consolidation

The recorded runs originally used separate application and scoring environments to avoid dependency conflicts. On 2026-10-27 the project consolidated into one `requirements.txt` and the main `.venv`, after a clean temporary environment passed all 96 offline tests, RAGAS metric imports, graph compilation, provider construction, and tool binding. The shared set uses OpenAI SDK 2.54.0, jiter 0.14.0, pydantic-settings 2.16.1, and python-dotenv 1.2.4. Configured generation/judge model IDs did not change. The historical scores above were not regenerated during consolidation. The former separate scoring environment used different transitive pins; these results are preserved as measured, not claimed as new measurements under the consolidated environment. Subsequent Linux image checks and deployed provider calls are recorded below; the historical RAGAS scores were not rerun in the deployed image.

## Deployed request measurements

Existing Cloud Logging `request_metrics` entries from Cloud Run revision
`csci599-multi-agent-00002-xpp` provide the following observations. They were
read without submitting new queries. The C++ request is identified by the user's
supplied trace; the document request is consistent with the user's reported
successful Raft test. Metrics intentionally omit query text and answers.

| Request | Completed (UTC) | Retrieval seconds | LLM seconds | Server total seconds | Server first worker token seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| C++ standard, web | 2026-10-28 07:04:25 | 9.88 | 17.43 | 29.61 | 21.01 |
| Document/Raft check | 2026-10-28 07:12:41 | 2.64 | 17.06 | 19.80 | 6.67 |

Request IDs are `d05a31e51d194a139f29f9a932f6c04c` (C++) and
`b58eb68f0a2b469f94f6884b97f9805c` (documents). Both recorded
`response_ready`, four model invocations, no unfinished invocations, and no
missing token usage. This status indicates a response was produced, not that
its factual correctness was independently verified.

The C++ trace shows an empty first web retrieval followed by a successful search
with revised keywords. Both retrieval operations completed at the transport
level; an empty evidence set still caused the first Research attempt to fail.
The document request used one document retrieval and two Research model calls;
the current implementation permits one citation repair without retrieving again.
Model-call counts alone do not prove the reason for the second generation.

| Request | Provider/model | Role | Calls | Input tokens | Output tokens | Summed model seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| C++ | OpenAI / `gpt-5.1` | Supervisor | 3 | 8,268 | 1,266 | 14.79 |
| C++ | Google / `gemini-3.5-flash-lite` | Research | 1 | 3,062 | 734 | 2.64 |
| Documents | OpenAI / `gpt-5.1` | Supervisor | 2 | 8,163 | 834 | 11.13 |
| Documents | Google / `gemini-3.5-flash-lite` | Research | 2 | 10,343 | 2,036 | 5.93 |

`app/metrics.py` measures model invocations and retrieval operations, and
`app/main.py` logs the request snapshot when the SSE stream ends. LLM seconds
sum completed invocation durations; server total includes additional graph and
streaming overhead. First worker token measures application arrival to the first
worker text fragment, not the Supervisor's first structured token or the final
answer's first token. Server timers exclude pre-application instance startup and
browser/network delays. These requests have no confirmed cold/warm labels and
are individual observations, not a steady-state latency benchmark.

Both generation providers were exercised in deployment. Their tasks, prompts,
context sizes, and output lengths differ, so these observations do not establish
a controlled provider speed, quality, or cost comparison.

### Generation cost estimates

Standard paid-tier text prices checked on 2026-10-28, in USD per million tokens:

| Model | Input | Output | Official source |
| --- | ---: | ---: | --- |
| `gpt-5.1` | $1.25 | $10.00 | [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-5.1) |
| `gemini-3.5-flash-lite` | $0.30 | $2.50 | [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) |

For each provider, estimated generation cost equals
`(input_tokens * input_rate + output_tokens * output_rate) / 1,000,000`.
Applying this formula to the reported usage above gives:

| Request | OpenAI estimate | Google estimate | Total generation estimate |
| --- | ---: | ---: | ---: |
| C++ web | $0.02299500 | $0.00275360 | $0.02574860 |
| Document/Raft check | $0.01854375 | $0.00819290 | $0.02673665 |

These are list-price generation estimates, not actual bills or complete service
costs. All reported input is priced as uncached; cached-token details, account
tier, credits, and discounts were not captured. Gemini lists free-tier token
usage separately, so eligible free usage may incur no generation charge.
Output rates are applied to the reported output totals; unreported billable usage
cannot be reconstructed from these logs. Tavily quota/charges, Cloud Run,
Artifact Registry, and build costs are excluded. Corpus embeddings run locally;
RAGAS judge/embedding costs belong to the earlier evaluation and are excluded.

### Confirmed cold/warm request pair

Two explicitly approved live requests used the identical query:
"How does Raft elect a leader? Explain in three concise sentences and cite your sources."
An in-memory Python client timed `POST /chat` using `perf_counter`, parsed SSE
events as they arrived, and immediately repeated the request after stream closure.
There were no automatic client retries, health warm-up requests, or Tavily calls.

The previous instance shut down at `2026-10-28T07:27:49Z`. The first request
started at `07:29:28.598Z`; Cloud Run logged a new AUTOSCALING instance at
`07:29:29.480Z`, application startup at `07:29:48.988Z`, and startup completion
at `07:30:35.710Z`. Embedding initialization accounted for 46.72 seconds.
Both requests ran on revision `csci599-multi-agent-00002-xpp` and the same
instance ID ending `143e07af72b1b73060b2a88a`. These logs establish the first
request as cold and the immediate repeat as warm, rather than inferring this
from response speed alone.

| Measurement (seconds) | Cold | Warm |
| --- | ---: | ---: |
| Client response headers | 66.92 | 0.15 |
| Client first worker text (TTFT) | 75.84 | 4.76 |
| Client final-answer event | 81.64 | 10.70 |
| Client complete stream | 81.65 | 10.71 |
| Server retrieval | 2.39 | 0.05 |
| Server summed model invocations | 9.52 | 10.41 |
| Server first worker text | 8.98 | 4.61 |
| Server total | 14.78 | 10.55 |

Cold request ID: `1fcddb90dba149d095a7d86f8b995936`.
Warm request ID: `666f2a82b51e4459ba7cfa61429c991c`, started at
`2026-10-28T07:30:50.249Z`. Each completed with a final-answer event, no stream
error, and Supervisor -> Research -> Supervisor execution. Research retrieved
17 chunks for the cold request and 18 for the warm request. The Supervisor
generated different retrieval instructions despite the identical user query,
so these are observed complete-workflow timings rather than identical internal
workloads. Final answer text was not retained by this timing client, and this
test does not independently establish claim-level correctness.

| Request | OpenAI input/output tokens | Google input/output tokens | Generation estimate (USD) |
| --- | ---: | ---: | ---: |
| Cold | 8,372 / 444 | 5,463 / 269 | $0.01721640 |
| Warm | 8,681 / 449 | 5,764 / 295 | $0.01780795 |

Each request made two OpenAI Supervisor calls and one Google Research call,
with complete reported usage and no unfinished calls. Estimates use the dated
standard prices and exclusions above; combined generation estimate is $0.03502435.
The cold server timer starts after initialization, explaining why it misses most
of the client-observed delay. Warm model time was slightly higher even though
retrieval and end-to-end latency were lower. This single pair demonstrates a
successful cold start and a warm response; 10.71 seconds is the observed warm
total, not a statistically established steady-state average or percentile.
No browser rendering timings, repeated-run distribution, or concurrent-load
measurements were collected.

### Same-evidence provider comparison

On `2026-10-28T07:34:25Z`, an explicitly approved local comparison made exactly
one generation call to each deployed model, sequentially, with retries disabled
and a 512-token output cap. Neither call used the supervisor graph, new retrieval,
web search, citation repair, or a paid judge. The question was dataset item
`raft-election-trigger`: "According to the Raft paper, what causes a follower to
start an election, and what does it do when becoming a candidate?"

Both calls received the identical 15 source records, in their saved order, from
the first row of `data/evaluation/full12_continuation_answers.jsonl`. These
included IDs, source text, and metadata. Reference answers were not sent.
The system prompt was:

> Answer the question using only the supplied evidence. Use at most 120 words. Cite factual claims using exact document source IDs in separate brackets, for example [raft.pdf:p5:c1]. Do not invent source IDs. State uncertainty when evidence is insufficient.

The human message was `json.dumps({'question': row['user_input'], 'sources':
row['sources']}, ensure_ascii=False)`. Combined system/human text contained
16,149 characters; SHA-256 of system text, newline, and human text was
`2a7e727c083d89ac0832f8444ab66bc044a2c9fbd39c615cab1becc4efba2b67`.
Both clients requested temperature zero, but Gemini warned that it ignores this
parameter and uses fixed sampling defaults. Thus message text and output caps
were matched; provider sampling behavior was not identical.

| Model | Local invocation seconds | Input tokens | Output tokens | Estimated generation USD | Citation IDs valid | Required facts covered |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| OpenAI `gpt-5.1` | 2.52 | 4,131 | 131 | $0.00647375 | Yes | 5/5 |
| Google `gemini-3.5-flash-lite` | 1.12 | 4,505 | 131 | $0.00167900 | Yes | 5/5 |

Both finished normally without reaching the output cap. Both reported zero
cached input tokens; OpenAI reported zero reasoning output tokens. Input token
counts differ because providers tokenize the same messages differently. Costs
use the standard prices above; the combined estimate was $0.00815275.

Manual review against `raft.pdf:p6:c1` checked five facts: no communication during
the election timeout triggers an election; the follower increments its term,
becomes a candidate, votes for itself, and sends RequestVote RPCs in parallel to
the other servers. Both answers included all five. OpenAI used a paragraph and
four bullets, citing `raft.pdf:p6:c1`, `raft.pdf:p5:c4`, `raft.pdf:p10:c3`, and
`raft.pdf:p4:c1`. Gemini used a paragraph and four bullets, citing
`raft.pdf:p6:c1` for all five facts. Both passed the existing document-citation
validator without normalization or repair. The direct passage supports both
answers' central claims; OpenAI's additional citations are not all independently
sufficient for the claims beside them. Its "other RPCs" wording also generalizes
the passage's reference to communication from a leader or candidate. The 5/5
check is factual coverage, not a claim of perfect citation entailment or a new
RAGAS score.

Gemini was faster and had a lower list-price estimate on this example, with the
same required factual coverage. This supports the cost-conscious Research
assignment for this narrow task, not a general superiority claim. This was one
question, one call per provider, OpenAI first, over the local network; it cannot
measure variance, order/cache effects, deployed latency, code reasoning quality,
or Supervisor decision quality. Raw answers were inspected in the execution
output; no extra repository artifact or helper script was added.

### Deployed shared-MCP verification

Approved request `05cedebe7fd446029cc78c538d57e4f0` completed on 2026-10-28
at 08:09:48 UTC. Research searched official Python documentation for TaskGroup;
Code independently invoked its technical web tool for asyncio.timeout. Both
agent traces identify the same remote `tavily_search` tool, retrieving five
sources each. Summary then completed. Eight generation calls and two searches
were within the approved 12-call/four-search budget; no client reruns occurred.
Server total was 39.62 s, first worker text 13.16 s, summed model time 28.84 s,
and retrieval time 6.68 s. Client complete-stream time was 117.13 s, including
pre-application delay; no separate cold/warm label was established for this run.
OpenAI reported 34,076 input/1,394 output tokens, Google 13,641 input/529 output,
with no missing usage or unfinished calls. Standard-price generation estimate
was $0.06194980, excluding search/cloud charges and billing discounts.

The saved trace, source excerpts, final answer, and usage summary are in
`data/evaluation/deployed-mcp-sharing.json`. Both shared-tool invocations and all
three worker completion events are present. The final answer gives the requested
summary but omits the requested code example, so this verifies deployed sharing
and orchestration execution, not complete satisfaction of every output request.

## Limitations and remaining required measurements

- These are single runs on a small development set used to guide retrieval changes, not a held-out benchmark. There are no repeated-run confidence intervals; generation and LLM judge variability can influence differences. Model aliases may also change behavior over time.
- The test set covers seven papers and only one cross-paper comparison. It does not test web/current-events grounding or full multi-agent output. Additional questions are optional; completing the remaining deployment measurements and submission evidence takes priority.
- RAGAS estimates grounding/relevance rather than proving factual correctness. The baseline cross-paper context recall was 1.000 despite missing explicit passages. The PBFT faithfulness discrepancy further motivates honest reporting and manual review rather than treating scores as ground truth.
- Citation IDs/pages are preserved and tested offline, but generated claim-level citation correctness is not comprehensively validated. PDFs can contain extraction errors, broken words, or imperfect table/column order.
- Historical RAGAS collector durations include any pacing wait introduced by the wrapper. The deployed measurements above separately record retrieval, generation, server total, and first worker token. One confirmed cold/warm pair now includes client TTFT/total; repeated-run steady-state variability remains unmeasured.
- Historical RAGAS runs did not capture token usage or request counts. The deployed requests above capture model invocation counts and reported tokens, with standard list-price generation estimates. Actual bills and complete per-query service costs remain unmeasured. Invocation counts do not include hidden SDK retries, and context characters are not token counts.
- Historical RAGAS generation was Gemini only; the OpenAI evaluator does not count as a second application generation provider. Deployed requests demonstrate OpenAI and Google generation; the same-evidence comparison above covers one local question, not a broad or deployed provider benchmark.
- RAGAS emits deprecation warnings for the legacy metric/evaluation interface used with pinned version 0.4.3. Both runs completed; compatibility with a future version is not claimed.

## Development priorities

Retain the current retrieval strategy and these results. Do not spend on repeated retrieval tuning unless a concrete blocking defect appears. Research, Code, Summary, LangGraph orchestration, shared MCP access, FastAPI/SSE, and the frontend are implemented; Cloud Run is deployed with public homepage/health checks verified. One confirmed cold/warm pair, generation cost estimates, and a one-question same-evidence provider comparison are recorded above with their limitations. Complete corpus attribution/reproduction materials and reconcile README, architecture, and process-log status with the deployed evidence. The RAGAS experiment evaluates document Research; it does not establish full-workflow answer quality or general reliability of deployed MCP sharing beyond the specific check above.
