import type { MqttMessage } from "../types/mqtt";

export type ChartPoint = { x: number; y: number };

/** Stable identity for a message: prefer the event id, fall back to topic+time. */
export function messageId(msg: MqttMessage): string {
  return msg.event_id ?? `${msg.topic}|${msg.timestamp}`;
}

/** Extract a numeric value from a message, or null when there is none. */
export function extractValue(msg: MqttMessage): number | null {
  const raw =
    msg.fields?.value ??
    msg.value ??
    msg.payload ??
    (msg.fields ? Object.values(msg.fields)[0] : undefined) ??
    null;
  if (raw == null) return null;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

/**
 * Collect the points that have not been plotted yet, grouped by topic.
 *
 * `seen` is mutated to record which message ids have been consumed, so calling
 * this repeatedly with the same buffer yields each event exactly once. Reset
 * `seen` (a fresh Set) when the selected topics or historical baseline change.
 *
 * The buffer is newest-first; points are emitted oldest-first so charts append
 * in chronological order.
 */
export function collectNewPoints(
  messages: MqttMessage[],
  topics: string[],
  seen: Set<string>
): Record<string, ChartPoint[]> {
  const result: Record<string, ChartPoint[]> = {};
  const wanted = new Set(topics);

  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (!wanted.has(msg.topic)) continue;

    const id = messageId(msg);
    if (seen.has(id)) continue;

    const value = extractValue(msg);
    if (value == null) continue;

    seen.add(id);
    (result[msg.topic] ??= []).push({ x: Date.parse(msg.timestamp), y: value });
  }

  return result;
}
