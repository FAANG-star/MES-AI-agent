import { describe, expect, it } from "vitest";

import { createSSEParser } from "@/lib/sse";

/**
 * The parser exists because chunk boundaries are not event boundaries.
 *
 * Everything here is a real shape the backend emits, split in a way the
 * network is entitled to split it.
 */
describe("the SSE parser", () => {
  it("reads one complete event", () => {
    const parser = createSSEParser();
    const events = parser.push('event: accepted\ndata: {"run_id":"abc"}\n\n');

    expect(events).toEqual([{ event: "accepted", data: '{"run_id":"abc"}' }]);
  });

  it("reads several events from one chunk", () => {
    const parser = createSSEParser();
    const events = parser.push(
      'event: accepted\ndata: {"a":1}\n\nevent: understanding\ndata: {"b":2}\n\n',
    );

    expect(events.map((e) => e.event)).toEqual(["accepted", "understanding"]);
  });

  it("holds an event that arrives split across two chunks", () => {
    const parser = createSSEParser();

    expect(parser.push('event: tool_result\ndata: {"step":1,')).toEqual([]);
    expect(parser.push('"tool":"get_part_information"}\n\n')).toEqual([
      { event: "tool_result", data: '{"step":1,"tool":"get_part_information"}' },
    ]);
  });

  it("holds an event split inside the delimiter itself", () => {
    const parser = createSSEParser();

    expect(parser.push('event: answer\ndata: {"ok":true}\n')).toEqual([]);
    expect(parser.push("\n")).toHaveLength(1);
  });

  it("joins a multi-line data field", () => {
    const parser = createSSEParser();
    const [event] = parser.push("event: run\ndata: line one\ndata: line two\n\n");

    expect(event.data).toBe("line one\nline two");
  });

  it("accepts data with no space after the colon", () => {
    const parser = createSSEParser();
    const [event] = parser.push('event:answer\ndata:{"x":1}\n\n');

    expect(event).toEqual({ event: "answer", data: '{"x":1}' });
  });

  it("keeps a leading space inside the payload, dropping only the protocol's own", () => {
    const parser = createSSEParser();
    const [event] = parser.push("event: run\ndata:   padded\n\n");

    expect(event.data).toBe("  padded");
  });

  it("ignores keep-alive comments", () => {
    const parser = createSSEParser();

    expect(parser.push(": keep-alive\n\n")).toEqual([]);
  });

  it("handles CRLF line endings", () => {
    const parser = createSSEParser();
    const [event] = parser.push('event: run\r\ndata: {"ok":true}\r\n\r\n');

    expect(event).toEqual({ event: "run", data: '{"ok":true}' });
  });

  it("defaults to 'message' when no event name is sent", () => {
    const parser = createSSEParser();
    const [event] = parser.push("data: bare\n\n");

    expect(event.event).toBe("message");
  });

  it("releases a trailing event that never got its blank line", () => {
    const parser = createSSEParser();
    parser.push('event: run\ndata: {"ok":true}');

    expect(parser.flush()).toEqual([{ event: "run", data: '{"ok":true}' }]);
    expect(parser.flush()).toEqual([]);
  });
});
