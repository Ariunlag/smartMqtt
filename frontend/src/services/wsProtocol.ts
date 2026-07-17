export const EVENT_SCHEMA_VERSION = 1;

export interface EventEnvelope<T = unknown> {
  version: number;
  event_id: string;
  event_type: string;
  occurred_at: string;
  data: T;
}

export interface BackoffOptions {
  base?: number; // first-step delay (ms)
  cap?: number; // maximum delay (ms)
  rng?: () => number; // injectable for deterministic tests
}

/**
 * Capped exponential backoff with jitter.
 *
 * Uses "equal jitter": half of the exponential window plus a random amount up
 * to the other half. Keeps a floor (never 0) so reconnects don't hot-spin, and
 * never exceeds `cap`.
 */
export function backoffDelay(attempt: number, opts: BackoffOptions = {}): number {
  const base = opts.base ?? 1000;
  const cap = opts.cap ?? 30_000;
  const rng = opts.rng ?? Math.random;
  const exp = Math.min(cap, base * 2 ** Math.max(0, attempt));
  const jittered = exp / 2 + rng() * (exp / 2);
  return Math.min(cap, Math.round(jittered));
}

/** Parse and validate an event envelope; returns null for malformed input. */
export function parseEnvelope(raw: string): EventEnvelope | null {
  let obj: unknown;
  try {
    obj = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  const e = obj as Record<string, unknown>;
  if (typeof e.event_type !== "string") return null;
  if (typeof e.event_id !== "string") return null;
  return {
    version: typeof e.version === "number" ? e.version : 0,
    event_id: e.event_id,
    event_type: e.event_type,
    occurred_at: typeof e.occurred_at === "string" ? e.occurred_at : "",
    data: e.data,
  };
}

/** Bounded LRU-ish set for idempotent event handling by event_id. */
export class EventDeduper {
  private seen = new Set<string>();
  private order: string[] = [];
  private max: number;

  constructor(max = 1000) {
    this.max = max;
  }

  /** Returns true the first time an id is seen, false on repeats. */
  isNew(id: string): boolean {
    if (this.seen.has(id)) return false;
    this.seen.add(id);
    this.order.push(id);
    if (this.order.length > this.max) {
      const evicted = this.order.shift();
      if (evicted !== undefined) this.seen.delete(evicted);
    }
    return true;
  }
}
