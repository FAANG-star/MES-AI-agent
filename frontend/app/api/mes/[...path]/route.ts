/**
 * The browser's only way to the backend.
 *
 * Two reasons this is a proxy rather than a direct call from the page:
 *
 *  1. **It works in the composed stack.** Inside Docker the API answers to
 *     `http://backend:8000`, a hostname the browser cannot resolve. Calling it
 *     server-side means the page needs no public API URL, and no CORS.
 *  2. **The surface stays controlled.** The same principle as the MES tool
 *     layer: a fixed list of routes may be reached, and anything else is a 404
 *     here rather than a request the backend has to refuse. A UI bug cannot
 *     turn into an unexpected call.
 *
 * The streaming route is forwarded as a stream — the analysis panel fills in
 * step by step, so buffering it would undo the point of having it.
 */

import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API = process.env.MES_API_URL ?? "http://localhost:8000";

const GETTABLE = new Set(["health", "machines", "tools", "agent", "traces"]);
const POSTABLE = new Set(["ask", "ask/stream", "understand"]);

function upstream(path: string[]): string {
  return `${API}/api/${path.map(encodeURIComponent).join("/")}`;
}

function notAllowed(path: string) {
  return Response.json(
    { error: `This interface does not call '${path}'.` },
    { status: 404 },
  );
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join("/");
  // `traces` and `traces/{run_id}` are both reachable; nothing deeper is.
  const allowed = GETTABLE.has(joined) || (path[0] === "traces" && path.length === 2);
  if (!allowed) return notAllowed(joined);

  try {
    const response = await fetch(upstream(path), {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    return new Response(response.body, {
      status: response.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch (error) {
    return unreachable(error);
  }
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join("/");
  if (!POSTABLE.has(joined)) return notAllowed(joined);

  const body = await request.text();
  const streaming = joined === "ask/stream";

  try {
    const response = await fetch(upstream(path), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: streaming ? "text/event-stream" : "application/json",
      },
      body,
      cache: "no-store",
      // The run takes as long as the local model takes; on CPU that is tens of
      // seconds. Whatever default the runtime has, it must not cut in here.
      signal: AbortSignal.timeout(600_000),
    });

    if (!streaming) {
      return new Response(response.body, {
        status: response.status,
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    }

    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        // `no-transform` keeps a proxy from re-chunking the stream, and
        // `x-accel-buffering` turns off nginx's buffer if one is in front.
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  } catch (error) {
    return unreachable(error);
  }
}

/**
 * A dead backend is a state the UI must be able to say out loud.
 *
 * Answering with an empty body would leave the page showing a spinner for a
 * question that will never be answered.
 */
function unreachable(error: unknown) {
  const detail = error instanceof Error ? error.message : String(error);
  return Response.json(
    { error: "The MES backend is not reachable.", detail, api: API },
    { status: 502 },
  );
}
