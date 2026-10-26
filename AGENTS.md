
# AGENTS.md — CSCI 599 Assignment 2

## 1. Project Objective

This repository contains my USC CSCI 599 Assignment 2 multi-agent RAG application.

The goal is to build a complete, reliable, and rubric-compliant project while keeping the implementation as simple, concise, and understandable as possible.

This is also a learning and resume project. I need to understand the architecture, code, execution flow, and design decisions well enough to explain them confidently during technical interviews.

Before making architectural decisions, read the assignment description, grading rubric, and relevant supporting materials in `docs/`.

The assignment requirements take priority over preferences for shorter code.

---

## 2. Code Simplicity — Highest Priority

**Build the simplest correct implementation that fully satisfies the assignment requirements.**

### Mandatory Rules

1. Prefer simple, readable code over sophisticated or overly abstract implementations.
2. Use straightforward Python functions, loops, dictionaries, and conditionals whenever possible.
3. Avoid unnecessary classes, wrappers, factories, managers, interfaces, adapters, and helper functions.
4. Do not create generic frameworks for a specific integration.
5. Avoid speculative defensive programming for hypothetical situations.
6. Handle realistic failures, actual API behavior, and required security concerns.
7. Keep functions focused and easy to understand.
8. Use meaningful variable names and clear control flow.
9. Minimize dependencies and reuse existing libraries.
10. Avoid clever one-liners and unnecessarily advanced Python patterns.
11. Do not add functionality that is unrelated to the current task.
12. Do not sacrifice correctness, security, reliability, or rubric compliance merely to reduce line count.

### Simplicity Checklist

Before implementing anything, ask:

- Can this be done with fewer moving parts?
- Is this abstraction genuinely necessary?
- Am I solving an actual requirement or a hypothetical future problem?
- Would a simpler implementation be equally correct?
- Can I explain this code clearly to a graduate CS student?

If a simpler implementation meets the same requirements, choose it.

Do not impose arbitrary line limits. Optimize for readability and conceptual simplicity rather than the smallest possible number of lines.

---

## 3. Assignment and Rubric Compliance

The complete assignment description and grading rubric are the authoritative sources for project requirements.

The project includes:

- LangGraph-based multi-agent orchestration with an LLM supervisor.
- At least three genuinely specialized agents: Research, Code, and Summary.
- Distinct agent responsibilities, prompts, and appropriate tool access.
- Document ingestion, chunking, embeddings, and vector retrieval.
- A grounded RAG pipeline using LangChain LCEL and a supported vector store.
- Source citations and evidence preservation.
- Tavily Remote MCP integration for real-time research.
- Actual MCP tool sharing or A2A integration, as required by the rubric.
- At least two LLM providers with justified and inspectable routing.
- FastAPI backend and SSE streaming.
- A simple frontend using HTML, CSS, and JavaScript.
- RAGAS-based evaluation.
- Google Cloud Run deployment.

Do not assume a requirement is complete merely because related code exists.

Verify implementation and tests against the actual assignment.

Never remove a required feature to simplify the code.

Clearly distinguish required features from optional enhancements.

---

## 4. Step-by-Step Development Workflow

**Work like a technical mentor teaching me while building the project.**

Do not implement an entire feature or modify many files at once unless I explicitly approve it.

Follow this workflow:

**Plan → Explain → Implement one file → Explain code → Test → Wait for approval → Next file**

### Step A — Present a Plan

Before implementing a new feature or performing a substantial refactor:

1. Inspect the existing relevant code.
2. Read the applicable assignment requirements.
3. Explain what we are building and why.
4. Explain how the component fits into the overall architecture.
5. Identify every file that needs to be created or modified.
6. Present the implementation order, file by file.
7. Explain important dependencies and design decisions.
8. Describe the tests needed.
9. Identify any expected paid API calls.
10. Wait for my approval before modifying files.

Keep the plan practical and concise.

### Step B — Implement One File

After I approve the plan:

1. Implement only the next approved file.
2. Explain its purpose.
3. Use the simplest correct implementation.
4. Show the complete updated file, not just a diff, unless I request otherwise.
5. Explain each function and important code section.
6. Explain how it interacts with other project files.
7. Explain relevant framework concepts where necessary.
8. Run focused offline tests when practical.
9. Report the results.
10. Stop and wait for my approval before continuing.

If two files must change together to maintain correctness, explain why and request approval first.

### Step C — Approval Checkpoint

At the end of every implementation step, report:

- File completed.
- What changed.
- Why the design was chosen.
- Important code explanations.
- Tests run and their actual results.
- Remaining work.
- Next proposed file.

**Do not automatically proceed to the next file.**

### Exceptions

Small bug fixes, import corrections, or tightly coupled changes may be grouped when necessary, but explain them.

If I explicitly request a complete implementation across multiple files, follow that request instead.

---

## 5. Code Explanation and Teaching

Assume I understand basic programming but am learning the frameworks and architectural patterns used in this project.

For every implemented file, explain:

### Purpose
Why the file exists and what responsibility it has.

### Functions
What each important function does, including inputs and outputs.

### Execution Flow
How the code executes step by step.

### Dependencies
Which libraries, modules, APIs, or services the file interacts with.

### Design Decisions
Why the implementation was chosen over alternatives.

### Testing
What tests verify and how to run them.

### Interview Relevance
What concepts I should understand well enough to explain during interviews.

Use small examples and execution walkthroughs when useful.

Avoid unnecessarily lengthy explanations of basic syntax.

---

## 6. API Usage and Cost Management

This project uses paid or quota-limited services, including OpenAI, Google Gemini, and Tavily.

**Do not make unnecessary API calls.**

### Rules

1. Prefer mocked tests, fixtures, and predefined responses.
2. Normal unit tests must not make paid API requests.
3. Mark live integration tests with `@pytest.mark.live`.
4. Do not run live tests automatically.
5. Do not repeatedly call APIs to verify functionality already tested.
6. Use real APIs only when mocks cannot meaningfully verify integration.
7. Keep approved live tests minimal in prompt size, search results, and request count.
8. Do not invoke LLMs for tasks that deterministic Python can reliably perform.
9. Avoid unnecessary retries and repeated searches.
10. Never run paid load tests, stress tests, or large evaluation batches without approval.
11. Record token usage, latency, and estimated cost when practical.
12. Never expose API keys in code, logs, traces, or documentation.
13. Do not compromise assignment requirements to save API credits.

### Before Any Paid API Test

Explain:

- Why the live test is necessary.
- Which provider or API will be called.
- The estimated number of requests.
- What successful verification would demonstrate.

**Wait for my explicit approval before making paid API calls.**

Do not interpret permission to implement a feature as permission to spend API credits.

---

## 7. Testing Standards

Use focused, deterministic tests wherever possible.

Tests should cover:

- Normal behavior.
- Important edge cases.
- Meaningful failure scenarios.
- State updates and agent routing.
- Citation preservation.
- API response handling.
- Relevant integration boundaries.

Prefer mocks over real external services.

Run focused tests after each file when practical.

Run the broader offline suite after completing a feature.

Do not claim a test passed unless it was actually executed.

Clearly report skipped tests and unverified integrations.

Do not introduce unnecessarily complex testing infrastructure.

---

## 8. Architecture and Design Decisions

Prefer the simplest architecture that satisfies the rubric.

For this project:

- Keep agent responsibilities clearly separated.
- Use LangGraph for orchestration.
- Use genuine MCP integration rather than replacing it with direct API calls.
- Preserve source attribution throughout retrieval and generation.
- Keep LLM routing explicit and inspectable.
- Avoid unnecessary state fields and duplicated data.
- Avoid excessive abstraction layers around external services.
- Use deterministic logic where an LLM is unnecessary.
- Keep error handling practical and understandable.
- Consider Google Cloud Run compatibility when choosing dependencies.

Do not redesign working components without identifying a concrete problem.

When additional complexity is necessary, explain why.

---

## 9. Documentation and Interview Preparation

Document important implementation steps throughout development.

The documentation should help me revise the project for technical interviews and eventually prepare a comprehensive project-review PDF.

Record:

- Architecture and component responsibilities.
- Important implementation decisions.
- Data flow between agents.
- RAG ingestion and retrieval flow.
- MCP communication.
- LLM routing decisions.
- Testing strategy and results.
- Significant bugs and fixes.
- Deployment steps.
- Trade-offs and limitations.

Keep documentation concise, organized, and accurate.

Avoid duplicating large code files unnecessarily.

Do not claim functionality is implemented or verified when it is not.

---

## 10. Recommendations and Improvements

After reviewing or completing a component, suggest improvements when relevant.

Categorize them as:

- **P0 — Required:** Necessary for assignment or rubric compliance.
- **P1 — Important:** Meaningful correctness, reliability, or maintainability improvements.
- **P2 — Optional:** Enhancements that are not necessary for the assignment.

For significant suggestions, explain:

- The problem.
- The proposed improvement.
- Why it matters.
- The implementation complexity.
- Any trade-offs.

Do not automatically implement unrelated suggestions.

Wait for my approval.

---

## 11. Scope Control

When I request a specific task:

1. Focus on that task.
2. Do not rewrite unrelated components.
3. Do not introduce unrelated features.
4. Do not perform unnecessary refactoring.
5. Do not install dependencies without a clear need.
6. Do not make architectural changes without explaining them.
7. Do not run paid tests without approval.
8. Do not continue to another implementation step without approval.

If an existing component already satisfies the requirements and is sufficiently simple, leave it unchanged.

---

## 12. Final Guiding Principles

1. **Rubric compliance is mandatory.**
2. **Simplicity and readability are top priorities.**
3. **Correctness and reliability must be preserved.**
4. **Implement incrementally, one file at a time.**
5. **Explain the code so I can learn it.**
6. **Use mocked tests by default.**
7. **Never make paid API calls without approval.**
8. **Document important decisions for interview preparation.**
9. **Avoid unnecessary abstractions and overengineering.**
10. **Wait for approval before proceeding to the next step.**

**The goal is not simply to finish the assignment. The goal is to build a complete, understandable, technically sound project that I can confidently explain in an interview.**
