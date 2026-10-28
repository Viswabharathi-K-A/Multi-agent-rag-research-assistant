# Process Log

## AI Tools Used

I used Codex as my coding assistant throughout the project for planning, writing code, debugging, testing, understanding concepts, and preparing documentation. I did not record the exact model version used by Codex, so I cannot confirm it.

For the application itself, I used OpenAI GPT-5.1 for the Supervisor and Code agents, and Google Gemini 3.5 Flash-Lite for the Research and Summary agents. These are the models used by my application, not necessarily the model used by Codex during development. I also used RAGAS with an OpenAI judge and embeddings for evaluation.

At the beginning, I provided Codex with instructions to keep the code simple, follow the assignment requirements, implement changes incrementally, and ask for approval before running tests that would consume paid API credits.

Instead of asking Codex to build the entire application in one go, I divided the implementation into smaller tasks. I first asked it to explain the approach, reviewed the proposed changes, and then proceeded with implementation. Whenever I came across something I did not understand, I asked Codex to explain it with examples.

I also regularly checked whether the implementation was following the assignment requirements and whether additional files or functions were actually necessary. For example, Codex introduced several helper scripts for cloud deployment and evaluation. I questioned whether these scripts were required and eventually asked it to remove the unnecessary ones.

Codex was also useful for generating unit tests, understanding error messages, debugging execution traces, and writing documentation. However, I reviewed its suggestions and compared them with the actual application behavior instead of assuming that the generated implementation was always correct.

## Development Process

I started by designing the multi-agent architecture using LangGraph. The application consists of a Supervisor agent and three specialized agents: Research, Code, and Summary.

The Supervisor is responsible for understanding the user's query, selecting the appropriate agent, and deciding whether additional work is required. The Research agent retrieves information from the local document corpus using RAG and from the web using Tavily MCP. It then uses LCEL to generate responses based on the retrieved information. The Code agent handles programming-related tasks, while the Summary agent summarizes information from other agents.

One of the important parts of the implementation was maintaining a shared state between the agents. This allowed the Supervisor to access the outputs of previously executed agents and decide what to do next. I also worked on preserving source metadata and citations so that information retrieved by the Research agent could be referenced in the final response.

During development, I encountered several issues that required changes to the initial implementation.

One issue was related to citations. Sometimes the generated responses contained incorrect citation IDs or citations that did not match the retrieved sources. To address this, I added citation validation, normalization, and a limited repair mechanism that uses the already retrieved evidence.

Another issue occurred with domain-restricted web searches. The application needed to preserve the allowed domains across requests and handle the nullable array format expected by Tavily MCP.

I also noticed that the Supervisor could sometimes finish execution without calling all the agents explicitly requested by the user. To address this, I added checks to ensure that the Supervisor considers the required agents before completing the workflow.

For these issues, I discussed the possible solutions with Codex, reviewed the implementation, and tested the changes. I tried to avoid introducing unnecessary complexity while fixing the actual problems.

After completing the main application, I worked on containerizing it using Docker and deploying it to Google Cloud Run.

During this process, I learned about multi-stage Docker builds, Linux dependencies, CPU-only PyTorch, model caching, Chroma vector storage, and running containers as a non-root user. The Docker build also needed to prepare the vector database from the provided PDF corpus and ensure that the required models were available without downloading them during runtime.

Initially, the Cloud Run service was deployed with private access. After reviewing the deployment, I approved changing it to public access so the application could be accessed through the browser.

After deployment, I tested the application with a question related to Raft. Although the local document corpus contained relevant distributed systems material, the Supervisor initially selected web research. I updated the Supervisor prompt to provide more information about the available document corpus. After this change, the Supervisor selected document retrieval for similar questions.

I preferred this approach because it allowed the LLM to continue deciding which source to use rather than introducing a hardcoded keyword-based routing mechanism.

## Testing and Evaluation

Throughout development, I used unit tests and mocked external API calls whenever possible to avoid unnecessary API usage and costs.

The last complete offline test suite passed **279 tests**. After modifying the Supervisor prompt to improve document selection, I also ran 48 existing Supervisor and graph tests, which passed.

However, I understood that passing unit tests alone does not guarantee that the actual LLM will make the correct decisions. For this reason, I also performed selected live tests after approving the API usage.

For evaluating the RAG pipeline, I used RAGAS with a dataset of 12 questions. I performed two evaluation runs to compare the original top-10 retrieval approach with an approach that expanded the retrieved context using continuation chunks.

The continuation approach improved answer relevance and context recall, but it also retrieved more context and reduced context precision. These results helped me understand the trade-off between retrieving more information and keeping the retrieved context relevant.

This evaluation focused on the document-based Research pipeline and did not measure the complete multi-agent workflow.

I also tested the application using real LLM providers and checked whether the Research and Code agents could work with the shared MCP setup.

During one deployed test involving a C++ question, the initial web search returned no results. The Research agent reported the failure, after which the Supervisor assigned another research task that completed successfully. This helped me verify how the system handled a failed agent execution.

For Cloud Run, I tested the homepage and health endpoint without authentication. I also measured the difference between cold-start and warm-request performance using two identical queries.

The first worker response took **75.84 seconds** during the cold start, compared with **4.76 seconds** for the warm request. Both requests completed without streaming errors.

I compared the client-side timing measurements with Cloud Run startup logs and instance information to better understand where the delay occurred.

I also performed a small comparison between OpenAI and Gemini by providing the same evidence to both models. Both models covered the five required facts and passed citation-ID validation. I recorded token usage and estimated the API costs using the available pricing information.

Since these comparisons involved only a limited number of requests, I cannot conclude that one model is generally faster, cheaper, or more accurate than the other.

## What I Learned

One of the main things I learned from this project is that writing code, running the application, and verifying whether it satisfies the requirements are three different things.

Even when Codex generated code that looked correct, there were situations where the implementation did not behave as expected. For example, the Supervisor sometimes skipped an explicitly requested agent, and the Tavily integration needed changes to handle the actual API schema.

These issues showed me why it is important to test the application and inspect execution traces instead of relying only on the generated code.

I also gained a better understanding of how multi-agent systems work, particularly how LangGraph manages shared state, how the Supervisor makes routing decisions, and how agents communicate their results.

Another important concept I learned was the difference between citation validation and factual correctness. A citation validator can check whether a source ID exists in the retrieved evidence, but it cannot guarantee that the source actually supports every claim in the generated response.

Similarly, checking whether generated Python code is syntactically valid does not mean the code will execute correctly. A successful API response also does not necessarily mean that the application completed every requested task.

I learned the importance of keeping the implementation simple. During development, Codex sometimes suggested additional helper files or abstractions. I reviewed whether they were actually useful and removed unnecessary scripts. At the same time, I retained components such as the metrics module because they were needed for collecting evaluation measurements.

Docker and Cloud Run were also important learning areas for me. Initially, I found multi-stage Docker builds confusing, especially the difference between building an image and running a container. By going through the Dockerfile and asking for explanations, I developed a better understanding of how dependencies are installed during the build process and how the final container runs the application.

The Cloud Run performance tests also helped me understand why cold-start latency and warm-request latency should be measured separately. Looking only at application logs did not capture the complete startup delay, so I used client-side measurements along with Cloud Run logs.

Overall, this project helped me gain practical experience with LangGraph, multi-agent orchestration, RAG, MCP, LLM integration, testing, evaluation, Docker, and cloud deployment.

More importantly, I learned that AI coding assistants are useful for speeding up development and understanding unfamiliar concepts, but I still need to review the generated code, verify its behavior, and understand the design decisions myself.