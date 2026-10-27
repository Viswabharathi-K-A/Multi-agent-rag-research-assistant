"use strict";

const chatForm = document.getElementById("chat-form");
const sendButton = document.getElementById("send-button");
const queryInput = document.getElementById("query");
const messages = document.getElementById("messages");
const traceLog = document.getElementById("trace-log");
const routingLog = document.getElementById("routing-log");
const citations = document.getElementById("citations");
let turnNumber = 0;

function addText(parent, label, text) {
    const section = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = label;
    const body = document.createElement("p");
    body.textContent = text;
    section.append(heading, body);
    parent.append(section);
    return body;
}

function addPanelTurn(parent, label) {
    const details = document.createElement("details");
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = label;
    details.append(summary);
    parent.append(details);
    return details;
}

chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = queryInput.value.trim();
    if (!query || sendButton.disabled) return;
    if (query.length > 12000) {
        queryInput.setCustomValidity("Use at most 12,000 characters.");
        queryInput.reportValidity();
        return;
    }
    queryInput.setCustomValidity("");
    sendButton.disabled = true;
    queryInput.disabled = true;
    sendButton.textContent = "Working…";
    const turn = ++turnNumber;
    const label = `Turn ${turn}: ${query}`;
    const turnMessages = document.createElement("section");
    messages.append(turnMessages);
    addText(turnMessages, "You", query);
    const status = addText(turnMessages, "Status", "Connecting…");
    const turnTrace = addPanelTurn(traceLog, label);
    const turnRouting = addPanelTurn(routingLog, label);
    const turnSources = addPanelTurn(citations, label);
    const workerText = new Map();
    const sourceLinks = new Map();
    let terminal = false;
    let reader;

    function handleEvent(frame) {
        const dataLines = frame.split(/\r?\n/)
            .filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).replace(/^ /, ""));
        if (!dataLines.length) return; // SSE comments/keepalive pings.
        const {type, data} = JSON.parse(dataLines.join("\n"));
        if (type === "start") {
            status.textContent = "Running agents…";
        } else if (type === "token") {
            if (!workerText.has(data.agent)) {
                workerText.set(data.agent, addText(turnMessages, `${data.agent} — working output`, ""));
            }
            workerText.get(data.agent).append(document.createTextNode(data.text));
        } else if (type === "trace") {
            const detail = data.details;
            addText(turnTrace, `${data.agent}: ${data.event}`,
                [detail.detail, detail.reason, detail.tool ? `Tool: ${detail.tool}` : ""]
                    .filter(Boolean).join("\n"));
        } else if (type === "routing") {
            addText(turnRouting, `${data.agent}: ${data.provider} / ${data.model}`, data.reason);
        } else if (type === "citation") {
            const source = document.createElement("details");
            source.id = `source-${turn}-${turnSources.children.length}`;
            const summary = document.createElement("summary");
            summary.textContent = `[${data.source_id}] ${data.document}`
                + (data.page == null ? "" : ` — PDF page ${data.page}`);
            source.append(summary);
            if (/^https?:\/\//i.test(data.document)) {
                const link = document.createElement("a");
                link.href = data.document;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = "Open web source";
                source.append(link);
            }
            const excerpt = document.createElement("p");
            excerpt.textContent = data.excerpt || "No excerpt supplied.";
            source.append(excerpt);
            turnSources.append(source);
            // Search-local web IDs can collide; do not guess an ambiguous target.
            if (sourceLinks.has(data.source_id)) sourceLinks.set(data.source_id, null);
            else sourceLinks.set(data.source_id, source);
        } else if (type === "done") {
            const answer = addText(turnMessages, "Final answer", "");
            // Link known citation IDs using DOM nodes, never generated HTML.
            for (const part of data.final_answer.split(/(\[[^\]\n]+\])/g)) {
                const source = sourceLinks.get(part.slice(1, -1));
                if (part.startsWith("[") && part.endsWith("]") && source) {
                    const link = document.createElement("a");
                    link.href = `#${source.id}`;
                    link.textContent = part;
                    link.addEventListener("click", () => { source.open = true; });
                    answer.append(link);
                } else {
                    answer.append(document.createTextNode(part));
                }
            }
            status.textContent = "Complete. Worker output above is intermediate.";
            terminal = true;
        } else if (type === "error") {
            status.textContent = `Error: ${data.message} Any partial worker output is incomplete.`;
            terminal = true;
        }
    }

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json", "Accept": "text/event-stream"},
            body: JSON.stringify({query}),
        });
        if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
        if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body) {
            throw new Error("The server did not return an event stream.");
        }
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!terminal) {
            const {value, done} = await reader.read();
            buffer += decoder.decode(value, {stream: !done});
            let boundary;
            while (!terminal && (boundary = /\r?\n\r?\n/.exec(buffer))) {
                const frame = buffer.slice(0, boundary.index);
                buffer = buffer.slice(boundary.index + boundary[0].length);
                handleEvent(frame);
            }
            if (done) {
                if (!terminal) throw new Error("The connection ended before the response completed.");
                break;
            }
        }
    } catch (error) {
        status.textContent = `Error: ${error.message} Any partial worker output is incomplete.`;
    } finally {
        if (reader) {
            try {
                await reader.cancel();
            } catch {
                // The connection may already be closed after a network failure.
            }
            reader.releaseLock();
        }
        sendButton.disabled = false;
        queryInput.disabled = false;
        sendButton.textContent = "Send";
        queryInput.focus();
    }
});

queryInput.addEventListener("input", () => queryInput.setCustomValidity(""));
sendButton.disabled = false;
