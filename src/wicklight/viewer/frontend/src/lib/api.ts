// Typed client for the read-only viewer API served by wicklight.viewer.server.
// These shapes mirror the JSON that server.py returns; the timeline and
// step-detail components (DTN-248/249) build on them.

export interface RunSummary {
  run_id: string;
  agent: string | null;
  status: string | null;
  steps: number | null;
  cost_usd: number | null;
  models: string[];
  blocks: number;
  approvals: number;
  started_at: string | null;
  dry_run: boolean;
  counterfactual: boolean;
}

export interface TraceEvent {
  v: number;
  run_id: string;
  step: number;
  timestamp: string;
  type: string;
  explain: string;
  payload: Record<string, unknown>;
}

export interface TraceIssue {
  line: number;
  message: string;
  severity: "error" | "warning";
}

export interface RunEvents {
  run_id: string;
  events: TraceEvent[];
  issues: TraceIssue[];
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const listRuns = (): Promise<RunSummary[]> => getJson("/api/runs");

export const getEvents = (runId: string): Promise<RunEvents> =>
  getJson(`/api/runs/${encodeURIComponent(runId)}/events`);

export const blobUrl = (runId: string, ref: string): string =>
  `/api/runs/${encodeURIComponent(runId)}/blobs/${ref}`;

// Fetch a blob's text (JSON payloads are parsed by the caller). Returns null
// when the blob is absent — hand-written traces (e.g. the sample) have no
// blobs, and the detail panel degrades gracefully rather than erroring.
export async function getBlob(runId: string, ref: string): Promise<string | null> {
  const response = await fetch(blobUrl(runId, ref));
  if (response.status === 404 || response.status === 400) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`blob ${ref}: ${response.status} ${response.statusText}`);
  }
  return response.text();
}

// The recorded request/response/result blob shapes (mirror the Python models).
export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  trusted: boolean;
  tool_call_id: string | null;
  name: string | null;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ModelRequestBlob {
  model: string;
  messages: Message[];
}

export interface ModelResponseBlob {
  content: string;
  tool_calls: ToolCall[];
  stop_reason: string;
}

export interface ToolResultBlob {
  ok: boolean;
  output: string;
  error: string | null;
  sensitive: boolean;
}

export async function getJsonBlob<T>(runId: string, ref: string): Promise<T | null> {
  const text = await getBlob(runId, ref);
  return text === null ? null : (JSON.parse(text) as T);
}
