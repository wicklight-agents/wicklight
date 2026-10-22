// Formatting helpers and the badge vocabulary. Every badge pairs an icon and a
// text label with its color, so status is never conveyed by color alone
// (DTN-248 accessibility requirement).

import type { TraceEvent } from "./api";
import type { StepFlag } from "./steps";

export interface Totals {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export function totals(events: TraceEvent[]): Totals {
  let inputTokens = 0;
  let outputTokens = 0;
  let costUsd = 0;
  for (const event of events) {
    if (event.type !== "model_responded") continue;
    const p = event.payload;
    if (typeof p["input_tokens"] === "number") inputTokens += p["input_tokens"];
    if (typeof p["output_tokens"] === "number") outputTokens += p["output_tokens"];
    if (typeof p["cost_usd"] === "number") costUsd += p["cost_usd"];
  }
  return { inputTokens, outputTokens, costUsd };
}

export function duration(events: TraceEvent[]): string | null {
  const times = events
    .map((event) => Date.parse(event.timestamp))
    .filter((t) => !Number.isNaN(t));
  if (times.length < 2) return null;
  const ms = Math.max(...times) - Math.min(...times);
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function cost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export interface Badge {
  label: string;
  icon: string;
  tone: "danger" | "warn" | "ok" | "info" | "muted";
}

// Icon + label + tone per flag; tone maps to color, icon/label carry meaning
// without it.
const FLAG_BADGES: Record<StepFlag, Badge> = {
  blocked: { label: "blocked", icon: "⨯", tone: "danger" },
  error: { label: "error", icon: "!", tone: "danger" },
  retry: { label: "retried", icon: "↻", tone: "warn" },
  limit: { label: "limit", icon: "⚠", tone: "warn" },
  waived: { label: "waived", icon: "~", tone: "warn" },
  approved: { label: "approved", icon: "✓", tone: "ok" },
  dry_run: { label: "dry run", icon: "◌", tone: "info" },
  sensitive: { label: "sensitive", icon: "🔒", tone: "info" },
};

export function flagBadge(flag: StepFlag): Badge {
  return FLAG_BADGES[flag];
}

// The run outcome, styled with the same icon+label+tone vocabulary.
export function outcomeBadge(status: string | null): Badge {
  switch (status) {
    case "completed":
      return { label: "completed", icon: "✓", tone: "ok" };
    case "error":
      return { label: "error", icon: "!", tone: "danger" };
    case "stopped":
      return { label: "stopped", icon: "⨯", tone: "danger" };
    case "limit":
      return { label: "limit reached", icon: "»", tone: "warn" };
    default:
      return { label: status ?? "running", icon: "…", tone: "muted" };
  }
}
