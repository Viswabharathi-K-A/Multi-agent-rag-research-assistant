# Process Log

## AI Tools Used

I used Codex as my coding assistant throughout the project for planning, implementation, debugging, testing, understanding concepts, and documentation. I did not record the exact model version used by Codex.

For the application, I used OpenAI GPT-5.1 for the Supervisor and Code agents, and Google Gemini 3.5 Flash-Lite for the Research and Summary agents. I also used RAGAS with an OpenAI judge and embeddings for evaluation.

At the beginning, I instructed Codex to follow the assignment requirements, keep the Python code simple, implement changes incrementally, and ask for approval before running paid API tests.

Instead of asking Codex to build the entire application at once, I divided the implementation into smaller tasks. I asked it to explain the proposed approach before making changes and requested examples whenever I did not understand something.

I also regularly questioned whether additional files or abstractions were necessary. For example, I asked Codex to remove unnecessary helper scripts introduced during deployment and evaluation.

Codex helped generate unit tests, debug errors, interpret execution traces, and prepare documentation. However, I reviewed the generated code and tested the application instead of assuming that every suggestion or implementation was correct.

## Development Process

I started by implementing a multi-agent architecture using LangGraph, consisting of a Supervisor and three specialized agents: Research, Code, and Summary.

The Supervisor selects agents based on the user's request and previous results. Research retrieves information using Chroma-based RAG and Tavily Remote MCP, Code handles programming tasks, and Summary condenses findings. I used shared LangGraph state to maintain agent results, execution traces, and source citations.

During development, I encountered several issues. Generated responses sometimes contained incorrect citation IDs, so I added citation validation, normalization, and limited repair. Domain-restricted web searches required preserving allowed domains across agent decisions within a request and handling Tavily's nullable array schema.

I also found that the Supervisor could finish without calling explicitly requested agents. I added completion checks to address this issue.

After implementing the application, I containerized it using a multi-stage Docker build and deployed it to Google Cloud Run. This involved configuring CPU-only PyTorch, model caching, Chroma indexing, and runtime dependencies.

During deployment testing, the Supervisor initially selected web research for a Raft question. I updated its prompt to describe the available document corpus, allowing the LLM to select document retrieval without introducing hardcoded keyword routing.

## Testing and Evaluation

Throughout development, I used mocked unit tests to verify application behavior while avoiding unnecessary API costs. The latest recorded offline test suite passed **292 tests**. I also performed selected live tests after approving API usage.

For evaluating the RAG pipeline, I used RAGAS with 12 questions and compared two retrieval approaches: top-10 similarity retrieval and top-10 retrieval with continuation chunks.

The continuation approach improved answer relevance from 0.7171 to 0.8939 and context recall from 0.9514 to 1.0000. However, context precision decreased slightly because additional chunks introduced more information. These evaluations measured the document-based Research pipeline, not the complete multi-agent system.

I also tested the application using real OpenAI and Gemini models and verified that Research and Code could access the shared Tavily MCP integration.

For Cloud Run, I tested the public homepage and health endpoint, along with document and web research. I measured cold-start and warm-request performance using identical queries. The first worker text arrived after **75.84 seconds during cold start** and **4.76 seconds during the warm request**.

Finally, I compared OpenAI and Gemini using identical evidence. Both covered five required facts and passed citation-ID validation. Since this was a limited comparison, the results do not establish general model superiority.

## What I Learned

One of the main lessons I learned is that writing code, running it, and verifying that it satisfies the requirements are different activities.

Although Codex generated code that looked correct, some implementations did not behave as expected. For example, the Supervisor occasionally skipped requested agents, and Tavily integration required changes to support the actual API schema. These issues taught me the importance of reviewing code, running tests, and examining execution traces.

I gained a better understanding of LangGraph, shared state, agent orchestration, RAG, MCP, and how different agents communicate their results.

I also learned that citation validation does not guarantee factual correctness. A valid citation ID only confirms that the source exists, not that it supports every claim. Similarly, Python syntax validation does not guarantee successful execution.

Docker and Cloud Run were important learning experiences. Initially, I found multi-stage Docker builds confusing