/**
 * A server-sent-events reader for `POST /api/ask/stream`.
 *
 * `EventSource` cannot be used: it only issues GET requests, and the question
 * travels in a POST body. So the response body is read as a stream and parsed
 * here.
 *
 * The parser is a pure function over strings — no network, no React — because
 * the failure it has to survive is boring and certain: chunk boundaries fall
 * wherever the network puts them, and an event can arrive split across two
 * reads. That is exactly the kind of thing worth a unit test and not worth
 * debugging in a live demo.
 */

export interface SSEEvent {
  event: string;
  data: string;
}

const DELIMITER = /\r?\n\r?\n/;

export function createSSEParser() {
  let buffer = "";

  return {
    /** Feed a chunk; get back whatever complete events it completed. */
    push(chunk: string): SSEEvent[] {
      buffer += chunk;
      const parts = buffer.split(DELIMITER);
      // The final part is either an incomplete event or an empty string. Either
      // way it stays in the buffer until the next chunk finishes it.
      buffer = parts.pop() ?? "";
      return parts.map(parseBlock).filter((e): e is SSEEvent => e !== null);
    },

    /** Anything left when the connection closes without a trailing blank line. */
    flush(): SSEEvent[] {
      const rest = buffer;
      buffer = "";
      const event = parseBlock(rest);
      return event ? [event] : [];
    },
  };
}

function parseBlock(block: string): SSEEvent | null {
  let event = "message";
  const data: string[] = [];

  for (const rawLine of block.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(":")) continue; // blank or comment/keep-alive

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // "data: x" and "data:x" both mean x — one leading space is part of the
    // protocol, not the payload.
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");

    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

/**
 * Read an SSE response body, calling `onEvent` with each parsed event.
 *
 * Errors are left to the caller: a dropped connection mid-run is a real state
 * the UI has to show, not something to swallow here.
 */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();

  const handle = ({ event, data }: SSEEvent) => {
    if (signal?.aborted) return;
    try {
      onEvent(event, JSON.parse(data));
    } catch {
      // A malformed payload is the backend's problem to fix, not a reason to
      // tear down a run that may still be producing valid events.
      onEvent(event, null);
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true })).forEach(handle);
      if (signal?.aborted) break;
    }
    parser.flush().forEach(handle);
  } finally {
    reader.releaseLock();
  }
}
