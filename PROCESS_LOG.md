# Process log (draft for owner review)

## AI tools used

I used Codex as a coding assistant for planning, implementation, explanations,
debugging, testing, and documentation. The exact coding-assistant model version
was not recorded, so I cannot reliably identify it. The application's configured
models were OpenAI GPT-5.1 for Supervisor and Code, and Google Gemini 3.5
Flash-Lite for Research and Summary. These runtime models are separate from the
assistant used during development. RAGAS used an OpenAI judge and evaluation
embeddings; that evaluator does not count toward the two-generation-provider
requirement.

I supplied repository instructions emphasizing simple Python, assignment
compliance, incremental changes, and explicit approval before paid API tests.
Instead of asking for the entire project at once, I requested plans, explanations,
and focused changes. I repeatedly asked what remained and questioned whether
additional files or abstractions were necessary. For example, I challenged the
cloud/container helper scripts accumulating under evaluation and requested their
removal.

Codex helped inspect framework behavior, generate mocked tests, interpret traces,
and compare implementation claims with actual evidence. It also drafted
architecture, evaluation, setup, and process documentation. I treated those drafts
as material requiring review, especially when they described my personal learning.
The workflow depended on my feedback about observed behavior and priorities,
rather than accepting generated code or completion statements without checking.

## Development narrative

The application grew around a LangGraph Supervisor coordinating Research, Code,
and Summary specialists. Research combined document retrieval with LCEL generation
and Tavily Remote MCP. The implementation preserved source metadata so findings
could carry citations through later workers and final synthesis. Keeping these
responsibilities distinct made the execution flow easier to inspect.

Several iterations addressed problems exposed by live behavior. Citation failures
led to exact-ID validation, conservative normalization, and bounded citation repair
using the same evidence. Domain restrictions needed persistent state and support
for Tavily's nullable array schema. A workflow that skipped an explicitly requested
specialist motivated requested-agent completion checks. These changes addressed
observed defects rather than introducing a generic orchestration framework.

Deployment introduced different concerns: Linux dependencies, CPU-only PyTorch,
model caching, bundled Chroma data, non-root execution, and Cloud Run's injected
port. The multi-stage image rebuilt the index from the supplied PDFs and kept
runtime model downloads disabled. Cloud Run was initially private; public access
was enabled after I approved it.

After deployment, a natural Raft question selected web research. The Supervisor
prompt was updated to describe the distributed-systems corpus and prefer documents
for its foundational topics. Subsequent tests selected document retrieval. The fix
retained LLM source selection instead of adding a keyword router.

## Verification narrative

Normal tests used mocked model and MCP boundaries to avoid unnecessary charges.
The last full offline suite passed 279 tests. After the corpus-awareness prompt
change, 48 existing Supervisor and graph tests passed. Those tests checked
implementation behavior but could not establish whether a live model would choose
appropriate sources. Live tests therefore required separate approval and bounded
request counts.

Two 12-question RAGAS runs evaluated document-only Research, comparing top-10
retrieval with continuation expansion. Continuation improved answer relevance and
context recall, with more context and lower precision. These measurements did not
evaluate the whole multi-agent workflow. Other checks exercised real providers,
local Research/Code MCP sharing, and selected browser paths. A deployed C++ trace
showed an empty search returning failure, followed by Supervisor redelegation and
successful research.

Cloud Run verification included unauthenticated homepage and health checks. An
approved identical-query pair correlated client timings with startup logs and
instance identity: first worker text arrived after 75.84 seconds cold and 4.76
seconds warm. Both requests completed without stream errors. A separate one-call
comparison supplied identical evidence to OpenAI and Gemini; both covered five
required facts and passed citation-ID validation. Token counts supported dated
list-price estimates. Single observations, different provider tokenization, and
limited workloads prevent broad performance or quality conclusions.

## What was learned

A central lesson from the recorded iterations is that implementation, execution,
and requirement verification are separate activities. Generated code can look
plausible while overlooking a real API schema or allowing the Supervisor to omit
requested work. Asking for explanations and examining actual traces helped expose
those gaps. I need to be able to explain the resulting architecture myself rather
than rely on the assistant's description.

I also need to distinguish citation identity from evidence support. A valid source
ID proves that the reference exists in supplied evidence, but not that every
nearby claim follows from it. Similarly, Python syntax inspection is not code
execution, and a successful HTTP response is not proof of factual correctness or
complete orchestration. The evaluation report preserves these limitations rather
than presenting every successful request as a fully verified answer.

Simplicity required active scope control. Moving unnecessary helper scripts into
another folder would not reduce the number of concepts to maintain; removing
one-off scripts was more consistent with my instructions. Conversely, the metrics
module serves required measurements and remains useful application code.

Finally, cold-start and warm latency must be measured separately. Application
logs alone missed most startup delay, while client timing and instance logs made
it visible. Before submission, I must review these personal reflections, verify
that they match my understanding, and practice explaining the design and trade-offs.
