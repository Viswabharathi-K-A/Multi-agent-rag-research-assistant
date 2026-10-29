import { useRef, useState } from "react";
import { readEvents } from "./stream.js";

function FinalAnswer({ turn }) {
  return turn.answer.split(/(\[[^\]\n]+\])/g).map((part, index) => {
    const matches = turn.sources.filter(source => source.source_id === part.slice(1, -1));
    // Search-local source IDs can collide; link only unambiguous references.
    if (part.startsWith("[") && part.endsWith("]") && matches.length === 1) {
      const id = `source-${turn.id}-${turn.sources.indexOf(matches[0])}`;
      return <a key={index} href={`#${id}`} onClick={() => {
        document.getElementById(id).open = true;
      }}>{part}</a>;
    }
    return part;
  });
}

export default function App() {
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState([]);
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  async function submit(event) {
    event.preventDefault();
    const question = query.trim();
    if (!question || busy) return;
    const id = turns.length + 1;
    setBusy(true);
    setTurns(previous => [...previous, {
      id, query: question, status: "Connecting...", workers: {},
      traces: [], routing: [], sources: [], answer: null,
    }]);

    function update(change) {
      setTurns(previous => previous.map(turn => turn.id === id ? { ...turn, ...change(turn) } : turn));
    }

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ query: question }),
      });
      for await (const { type, data } of readEvents(response)) {
        if (type === "start") {
          update(() => ({ status: "Running agents..." }));
        } else if (type === "token") {
          update(turn => ({ workers: {
            ...turn.workers, [data.agent]: (turn.workers[data.agent] || "") + data.text,
          } }));
        } else if (type === "trace") {
          update(turn => ({ traces: [...turn.traces, data] }));
        } else if (type === "routing") {
          update(turn => ({ routing: [...turn.routing, data] }));
        } else if (type === "citation") {
          update(turn => ({ sources: [...turn.sources, data] }));
        } else if (type === "done") {
          update(() => ({ answer: data.final_answer, status: "Complete. Worker output above is intermediate." }));
        } else if (type === "error") {
          throw new Error(data.message);
        }
      }
    } catch (error) {
      update(() => ({ status: `Error: ${error.message} Any partial worker output is incomplete.` }));
    } finally {
      setBusy(false);
      // Focus after React has enabled the textarea again.
      requestAnimationFrame(() => input.current?.focus());
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Multi-Agent Research Assistant</h1>
        <p>LangGraph / RAG / MCP / LLM Routing</p>
      </header>
      <main className="workspace">
        <section className="chat-panel" aria-label="Chat">
          <h2>Research Assistant</h2>
          <div className="messages" aria-live="polite">
            {!turns.length && <p className="welcome">Ask a question about technical documentation or code.</p>}
            {turns.map(turn => <section key={turn.id}>
              <h3>You</h3><p>{turn.query}</p>
              <h3>Status</h3><p>{turn.status}</p>
              {Object.entries(turn.workers).map(([agent, text]) => <section key={agent}>
                <h3>{agent} - working output</h3><p>{text}</p>
              </section>)}
              {turn.answer !== null && <section>
                <h3>Final answer</h3><p><FinalAnswer turn={turn} /></p>
              </section>}
            </section>)}
          </div>
          <form id="chat-form" onSubmit={submit}>
            <label htmlFor="query">Your question</label>
            <textarea id="query" ref={input} rows={3} required maxLength={12000}
              placeholder="Ask a technical question..." value={query} disabled={busy}
              onChange={event => setQuery(event.target.value)} />
            <button type="submit" disabled={busy || !query.trim()}>{busy ? "Working..." : "Send"}</button>
          </form>
        </section>
        <aside className="inspection-panel" aria-label="Execution inspection">
          <section>
            <h2>Agent Execution Trace</h2>
            <div id="trace-log">{turns.map(turn => <details key={turn.id} open>
              <summary>Turn {turn.id}: {turn.query}</summary>
              {turn.traces.map((trace, index) => <div key={index}>
                <h3>Node: {trace.agent}</h3>
                <p><strong>Event / Decision:</strong> {trace.event}</p>
                {trace.details.detail && <p><strong>Details:</strong> {trace.details.detail}</p>}
                {trace.details.reason && <p><strong>Reason:</strong> {trace.details.reason}</p>}
                {trace.details.tool && <p><strong>Tool:</strong> {trace.details.tool}</p>}
              </div>)}
            </details>)}</div>
          </section>
          <section>
            <h2>LLM Routing</h2>
            <div id="routing-log">{turns.map(turn => <details key={turn.id} open>
              <summary>Turn {turn.id}: {turn.query}</summary>
              {turn.routing.map((route, index) => <div key={index}>
                <h3>{route.agent}: {route.provider} / {route.model}</h3>
                <p>{route.reason}</p>
              </div>)}
            </details>)}</div>
          </section>
          <section>
            <h2>Sources</h2>
            <div id="citations">{turns.map(turn => <details key={turn.id} open>
              <summary>Turn {turn.id}: {turn.query}</summary>
              {turn.sources.map((source, index) => <details key={index} id={`source-${turn.id}-${index}`}>
                <summary>[{source.source_id}] {source.document}
                  {source.page != null && ` - PDF page ${source.page}`}</summary>
                {/^https?:\/\//i.test(source.document) && <a href={source.document}
                  target="_blank" rel="noopener noreferrer">Open web source</a>}
                <p>{source.excerpt || "No excerpt supplied."}</p>
              </details>)}
            </details>)}</div>
          </section>
        </aside>
      </main>
    </div>
  );
}
