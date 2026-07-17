import { describe, it, expect } from "vitest";
import { collectNewPoints, extractValue, messageId } from "./chartPoints";
import type { MqttMessage } from "../types/mqtt";

const msg = (over: Partial<MqttMessage>): MqttMessage => ({
  topic: "t/a",
  tags: {},
  fields: { value: 1 },
  timestamp: "2024-01-01T00:00:00.000Z",
  ...over,
});

describe("extractValue", () => {
  it("reads fields.value then value then payload", () => {
    expect(extractValue(msg({ fields: { value: 5 } }))).toBe(5);
    expect(extractValue(msg({ fields: {}, value: 7 }))).toBe(7);
    expect(extractValue(msg({ fields: {}, payload: 9 }))).toBe(9);
  });

  it("returns null when no numeric value exists", () => {
    expect(extractValue(msg({ fields: {}, value: "abc" }))).toBeNull();
  });
});

describe("collectNewPoints", () => {
  it("produces exactly one point per live event", () => {
    const messages = [
      msg({ event_id: "e2", timestamp: "2024-01-01T00:00:02.000Z", fields: { value: 2 } }),
      msg({ event_id: "e1", timestamp: "2024-01-01T00:00:01.000Z", fields: { value: 1 } }),
    ];
    const seen = new Set<string>();
    const result = collectNewPoints(messages, ["t/a"], seen);
    expect(result["t/a"]).toHaveLength(2);
  });

  it("does not re-append on repeated calls with the same buffer", () => {
    const messages = [msg({ event_id: "e1" })];
    const seen = new Set<string>();
    expect(collectNewPoints(messages, ["t/a"], seen)["t/a"]).toHaveLength(1);
    // second render, same buffer -> nothing new
    expect(collectNewPoints(messages, ["t/a"], seen)["t/a"]).toBeUndefined();
  });

  it("keeps messages with the same topic+timestamp but distinct event ids", () => {
    const messages = [
      msg({ event_id: "e2", fields: { value: 2 } }),
      msg({ event_id: "e1", fields: { value: 1 } }),
    ];
    const seen = new Set<string>();
    expect(collectNewPoints(messages, ["t/a"], seen)["t/a"]).toHaveLength(2);
  });

  it("only includes selected topics", () => {
    const messages = [msg({ topic: "t/a", event_id: "a" }), msg({ topic: "t/b", event_id: "b" })];
    const seen = new Set<string>();
    const result = collectNewPoints(messages, ["t/a"], seen);
    expect(result["t/a"]).toHaveLength(1);
    expect(result["t/b"]).toBeUndefined();
  });

  it("a fresh seen-set (topic/selection change) re-emits points", () => {
    const messages = [msg({ event_id: "e1" })];
    const seen = new Set<string>();
    collectNewPoints(messages, ["t/a"], seen);
    // simulate selection change resetting dedup scope
    const freshSeen = new Set<string>();
    expect(collectNewPoints(messages, ["t/a"], freshSeen)["t/a"]).toHaveLength(1);
  });

  it("messageId falls back to topic+timestamp without an event id", () => {
    expect(messageId(msg({ event_id: undefined }))).toBe("t/a|2024-01-01T00:00:00.000Z");
  });
});
