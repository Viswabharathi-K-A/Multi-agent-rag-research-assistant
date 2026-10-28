# Process log

## AI tools used

I used Codex as a coding assistant for planning, implementation, code explanation,
debugging, test generation, and documentation. The exact coding-assistant model
version was not recorded, so I cannot reliably identify it. The application itself
uses OpenAI for the Supervisor and Code agents and Google Gemini for Research and
Summary by default. Those runtime models are separate from the coding assistant.
RAGAS also uses an OpenAI judge and evaluation embeddings; evaluator usage does
not count as demonstrating two application generation providers.

My prompts were incremental rather than a single request to generate the entire
assignment. For example, I asked, “can you tell me what changes you have made in
each file now,” and repeatedly asked for the next plan and remaining issues. This
helped keep architectural decisions explainable. I also supplied repository
instructions emphasizing simple code, rubric compliance, focused offline tests,
and explicit approval before paid API calls.

I challenged interpretations instead of accepting every proposed change. One
example was: “I am not getting, we already incorporating mcp sharing in our
architecture right? Our research and code agents both can make tavily mcp tool
call.” This prompted clarification and verification of existing sharing rather
than treating another abstraction as necessary. The resulting development process
used AI-generated code as a proposal to inspect and test, not as evidence that a
requirement was complete.

## Development narrative

Two prompt → code generation → verification cycles illustrate the development.

**Cycle 1: grounding and citation recovery.** I approved live testing with “ok, I
am giving you permission to do all the 7 test now.” After the results exposed
problems, I asked, “ok make a plan to fix all these issues,” followed by “fix first
4 fixes.” Codex generated changes separating concise web search queries from task
instructions, preserving domain restrictions, validating web citations, and adding
one citation-only repair attempt in Research and Summary. The generated logic used
`validate_document_citations(content, sources)` and
`validate_web_citations(content, sources)` before accepting findings. Repair reused
the same evidence rather than performing another search. I subsequently requested,
“ok you can now do the retest,” making verification another explicit step.

**Cycle 2: release preparation and MCP compatibility.** After reviewing pending
work, I asked, “so check the release checklist and impelement the changes.” Codex
extended Tavily domain-schema handling with
`domain_options = [domain_schema] + domain_schema.get("anyOf", [])`, checking for
a string-array branch before passing `include_domains`. It also generated a
Dockerfile, setup/deployment instructions, a process-log draft, and a measurement
template. The Dockerfile rebuilds the document index on Linux and caches embedding
assets during the build. These deliverables were reviewed as preparation, not
presented as proof of deployment. Docker-engine availability prevented the build
verification step, leaving that part of the cycle explicitly incomplete.

## Verification narrative

I authorized tests and requested reconsideration based on the reported outcomes;
Codex executed the commands and reported their results. In Cycle 1, offline tests
checked source modes, citation rejection and repair, unchanged evidence, domain
restrictions, and worker failures. The approved live retest then passed restricted
web Research, mixed document/web Research, and mixed-evidence Summary. However,
the complete browser workflow was only partial: the Supervisor skipped explicitly
requested Summary work. That distinction prevented a successful HTTP response from
being mistaken for successful orchestration.

Further iteration introduced persisted `required_agents`, derived pending/failed
status, and one bounded Supervisor reconsideration before premature completion.
Graph regressions checked both recovery and honest incomplete termination. That
version passed 275 offline tests. It still needed a new live check of requirement
extraction; mocked decisions cannot establish real-model interpretation.

In Cycle 2, nullable-schema regressions tested either `anyOf` ordering, incompatible
schemas, unchanged discovery metadata, and continued local domain filtering. The
focused MCP/sharing suite passed 50 tests, followed by 279 passing offline tests
in the full suite. Local Chroma inspection confirmed 1,891 chunks and matching
embedding-model metadata. Docker inspection reported an unavailable engine, so no
Linux build, container startup, or Cloud Run success was claimed.

Separately, two live 12-question RAGAS experiments measured document-only Research.
Continuation improved answer relevance and recall with more context and slightly
lower precision. Those results do not evaluate the entire multi-agent application.

## What was learned

The main lesson from these iterations is that code generation, test execution,
and requirement verification are separate activities. An assistant can produce a
plausible implementation while overlooking actual API schemas or a specialist
that the user explicitly requested. Asking for the remaining issues and requesting
a retest was therefore more useful than repeatedly accepting completion claims.
The MCP discussion also showed the importance of identifying an existing capability
before adding another layer: Research and Code already shared a real Remote MCP
client; the missing work included evidence and compatibility, not replacing the
architecture.

I learned to distinguish citation identity from evidence support. An exact source
ID proves that a reference exists in supplied evidence, but not that the passage
supports every generated claim. Similarly, Python AST inspection establishes
syntax and structure, not runtime correctness or security. RAGAS scores provide
useful measurements but can disagree with inspected passages and should not be
treated as unquestionable ground truth.

The work also reinforced the value of honest limits. Mocked tests cannot prove
live tool selection, configured provider names cannot prove actual calls, and a
Dockerfile cannot prove a working deployment. Paid calls require a budget, and
unknown latency or cost should remain unknown instead of being filled with
estimates lacking evidence. Before submission, I need to review this draft,
confirm the personal conclusions in my own words, and complete the outstanding
deployment and measurement evidence.
