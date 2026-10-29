# AGENTS.md — Multi-Agent RAG Portfolio Project

## 1. Project Objective

This project started as USC CSCI 599 Assignment 2 and has already been submitted.

The goal now is to transform it into a clean, understandable, resume-worthy multi-agent RAG application.

**Primary objectives:**
- Simplify the existing implementation without breaking core functionality.
- Remove unnecessary complexity, abstractions, and overengineering.
- Keep the code readable, maintainable, and easy to explain during technical interviews.
- Learn the technologies and architectural concepts used in the project.
- Gradually introduce AWS services to gain practical cloud experience.
- Build a reliable project without unnecessary production-scale complexity.

**Assignment rubric compliance is no longer a priority.** Focus on building a practical portfolio project.

---

## 2. Code Simplicity — Highest Priority

Always prefer the simplest implementation that correctly solves the problem.

### Guidelines

1. Prefer straightforward Python functions, loops, dictionaries, and conditionals.
2. Avoid unnecessary classes, wrappers, factories, managers, adapters, and abstraction layers.
3. Remove duplicated logic, unused functions, unnecessary configuration, and redundant state.
4. Avoid excessive defensive programming for unlikely scenarios.
5. Keep essential error handling, input validation, and security protections.
6. Avoid complicated Python patterns when simpler alternatives exist.
7. Minimize dependencies and unnecessary external libraries.
8. Keep functions focused, readable, and easy to understand.
9. Avoid introducing functionality unrelated to the current task.
10. Do not optimize prematurely or introduce unnecessary performance improvements.
11. Preserve working functionality unless I explicitly approve its removal.
12. Prefer readability over reducing the number of lines.

**Important:** Do not rewrite working code merely to make it shorter. Simplify only when there is a meaningful improvement.

---

## 3. Core Architecture

Preserve the project's important technical features unless I approve a change.

The current architecture includes:

- LangGraph for multi-agent orchestration.
- An LLM Supervisor for dynamic agent routing.
- Research, Code, and Summary agents.
- OpenAI and Google Gemini model integrations.
- Document ingestion, chunking, embeddings, and vector search.
- RAG using Chroma and LangChain.
- Tavily Remote MCP for external research.
- Source citations.
- FastAPI backend.
- Server-Sent Events (SSE) for streaming.
- HTML, CSS, and JavaScript frontend.

These features provide the project's main technical value.

However, unnecessary complexity surrounding these features can be removed.

For any proposed architectural simplification, explain:
- What currently exists.
- Why it is unnecessarily complicated.
- What the simpler alternative would look like.
- What functionality would change.
- Whether the change affects other components.

Do not remove important functionality without approval.

---

## 4. Mandatory Development Workflow

**This is the most important instruction.**

Do not implement many changes at once.

Always follow:

**Review → Propose Changes → Wait for Approval → Implement One Change → Explain → Test → Wait for Approval**

### Step 1 — Review the Project

Before modifying anything:

1. Inspect the relevant existing files.
2. Understand the current implementation and dependencies.
3. Identify unnecessary complexity.
4. Identify code that can be simplified or removed.
5. Avoid recommending changes to components that are already sufficiently simple.

### Step 2 — Propose a List of Changes

Before implementation, present a numbered list of proposed changes.

For each change, include:
- Files affected.
- Current problem.
- Proposed simplification or improvement.
- Reason for the change.
- Expected benefit.
- Potential risks or trade-offs.
- Estimated complexity: Low, Medium, or High.

Order changes logically, considering dependencies.

**Do not modify any files during the planning stage.**

### Step 3 — Wait for Approval

After presenting the plan, stop.

Wait for me to approve a specific change.

Approval for one change does not authorize the remaining changes.

### Step 4 — Implement One Change

After approval:

1. Implement only the approved change.
2. Modify only the files necessary for that change.
3. Keep the implementation simple.
4. Do not introduce unrelated refactoring.
5. Do not automatically implement other improvements from the plan.
6. Preserve existing functionality.

Multiple tightly related files may be modified together when necessary, but only as part of the single approved change.

### Step 5 — Explain and Verify

After implementation, explain:
- What changed.
- Why the change was necessary.
- How the updated code works.
- How it interacts with other components.
- Which concepts I should understand for interviews.
- How the change was verified.

Use small examples when explaining complicated concepts.

### Step 6 — Stop

After completing the approved change:

- Report the result.
- Identify the next proposed change.
- Wait for my explicit approval.

**Never automatically continue to the next change.**

---

## 5. Testing — Keep It Extremely Simple

The project does not need an extensive enterprise-level test suite.

Prefer a small number of straightforward tests that verify essential functionality.

### Guidelines

1. Reduce the existing pytest suite to a few simple, meaningful tests.
2. Remove unnecessary fixtures, complicated mocks, and excessive test helpers.
3. Avoid testing implementation details that do not affect observable behavior.
4. Do not create elaborate testing infrastructure.
5. Prefer simple smoke tests and basic unit tests.
6. Use manual testing when it is simpler and appropriate.
7. Avoid paid API calls during automated testing.
8. Do not run live integration tests without my approval.
9. Do not add tests solely to increase coverage metrics.
10. Keep the tests understandable enough that I can explain them.

A reasonable target is approximately 3–5 simple tests, covering important functionality.

If a test is unnecessarily complicated, propose simplifying or removing it.

Do not remove all verification merely to reduce code.

---

## 6. AWS Integration — Future Enhancement

I plan to enhance this project with AWS services while learning AWS concepts.

AWS integration should be gradual and should provide meaningful technical or resume value.

### Guidelines

1. Do not introduce AWS services immediately without discussing the architecture.
2. First understand the existing application and its deployment requirements.
3. Propose a practical AWS integration roadmap.
4. Explain what each AWS service does and why it is useful.
5. Prefer services that solve actual problems in the application.
6. Avoid introducing unnecessary infrastructure or services solely to make the project look more impressive.
7. Consider free-tier availability, ongoing costs, and operational complexity.
8. Explain how each AWS service interacts with the existing components.
9. Implement only one approved AWS improvement at a time.
10. Do not deploy resources or incur AWS charges without my explicit approval.

Potential services to evaluate include:
- Amazon S3 for document storage.
- Amazon ECS with Fargate for container deployment.
- Amazon ECR for Docker images.
- Amazon CloudWatch for logs and monitoring.
- AWS IAM for permissions and access control.
- Amazon Bedrock for managed LLM integration, if justified.

These are possibilities, not mandatory requirements.

**Do not implement AWS features until I explicitly request and approve them.**

---

## 7. Code Explanation and Learning

Treat this project as both a software engineering project and a learning exercise.

When explaining an implementation, cover:

1. **Purpose:** Why the component exists.
2. **Execution flow:** What happens step by step.
3. **Inputs and outputs:** What data the component receives and produces.
4. **Dependencies:** Which libraries, services, or modules it uses.
5. **Design decisions:** Why this approach was chosen.
6. **Trade-offs:** What alternatives exist and why they were not selected.
7. **Interview relevance:** What concepts I should be able to explain.

Use concrete examples when helpful.

Do not overwhelm explanations with unnecessary theoretical details.

The goal is for me to confidently explain every important component without memorizing code.

---

## 8. API Usage and Cost Management

The application uses external services such as OpenAI, Google Gemini, and Tavily.

Follow these rules:

1. Avoid unnecessary paid API calls.
2. Prefer local verification when possible.
3. Never run paid load tests or large evaluation batches without approval.
4. Do not make repeated API calls merely to confirm already verified behavior.
5. Never expose API keys or credentials.
6. Do not deploy cloud resources without approval.
7. Explain expected costs before proposing live testing or deployment.

**Always ask for my approval before making paid API calls or creating AWS resources.**

---

## 9. Documentation

Keep documentation concise and useful for future reference.

Prioritize:
- README with setup and execution instructions.
- Simple architecture overview.
- Explanation of the agent workflow.
- RAG ingestion and retrieval flow.
- MCP integration.
- AWS architecture as features are introduced.
- Important design decisions and trade-offs.

Avoid excessive documentation, duplicated explanations, and assignment-specific reporting.

Documentation should support GitHub portfolio presentation and technical interview preparation.

---

## 10. Scope Control

When I request a specific task:

1. Focus only on the requested task.
2. Do not make unrelated improvements.
3. Do not modify files outside the approved scope.
4. Do not add dependencies unnecessarily.
5. Do not introduce advanced architectural patterns without a clear need.
6. Do not remove functionality without approval.
7. Do not make paid API calls without approval.
8. Do not implement multiple planned changes together.
9. Always explain proposed changes before implementation.
10. Always stop after completing one approved change.

If additional problems are discovered during implementation, report them separately instead of fixing them automatically.

---

## 11. Final Guiding Principles

1. **Simplicity over unnecessary complexity.**
2. **Understanding over clever implementations.**
3. **Working functionality over aggressive code reduction.**
4. **One approved change at a time.**
5. **Minimal but meaningful testing.**
6. **AWS integration should be gradual and purposeful.**
7. **Never incur API or cloud costs without approval.**
8. **Keep the project resume-worthy and interview-friendly.**
9. **Explain important architectural decisions clearly.**
10. **Always wait for approval before proceeding.**

**Final goal:** Build a clean, technically meaningful multi-agent RAG application with practical AWS integration that I can confidently demonstrate, explain, and discuss during software engineering interviews.