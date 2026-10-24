
# CSCI 599 Assignment 2 — Implementation Notes

## Step 1: Project Foundation

### Objective

Establish a modular Python/FastAPI project for a
multi-agent technical research assistant.

### Architectural decisions

- FastAPI serves the API and frontend.
- LangGraph will orchestrate three specialized agents.
- Chroma will store embedded document chunks.
- Tavily Remote MCP will provide live retrieval.
- OpenAI and Google will provide LLM generation.
- Server-Sent Events will stream output and traces.
- Google Cloud Run will host the application.
- The initial application will be stateless.

### Files implemented

- app/config.py: Typed environment configuration.
- app/schemas.py: Request, citation, routing and
  streaming event contracts.
- app/main.py: FastAPI entry point and health endpoint.
- app/static/: Frontend shell and inspection panels.
- tests/test_health.py: Foundation tests.

### Verification checklist

- [ ] Python 3.13 environment created
- [ ] Dependencies installed
- [ ] pip check passed
- [ ] FastAPI server started
- [ ] Homepage loaded
- [ ] Health endpoint returned HTTP 200
- [ ] Four automated tests passed

### Problems encountered

Record actual errors and their solutions here.

### Interview concepts

1. Why use FastAPI for an agentic AI backend?
2. What does ASGI provide compared with WSGI?
3. What is the purpose of application lifespan?
4. Why separate configuration from application logic?
5. How do Pydantic models validate API data?
6. Why use SSE rather than returning one final response?
7. How should API credentials be managed in production?
8. Why can Cloud Run containers not be treated as
   durable conversation storage?
