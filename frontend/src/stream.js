// Read fetch's POST response as SSE; chunks may split frames or UTF-8 characters.
export async function* readEvents(response) {
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body) {
    throw new Error("The server did not return an event stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/)
          .filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).replace(/^ /, ""));
        if (!lines.length) continue; // Ignore keepalive comments.
        const event = JSON.parse(lines.join("\n"));
        yield event;
        if (event.type === "done" || event.type === "error") return;
      }
      if (done) throw new Error("The connection ended before the response completed.");
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // A failed connection may already be closed.
    }
    reader.releaseLock();
  }
}
