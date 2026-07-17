import { describe, it, expect } from "vitest";
import { backoffDelay, parseEnvelope, EventDeduper } from "./wsProtocol";

describe("backoffDelay", () => {
  it("stays within the equal-jitter window and grows with attempts", () => {
    // rng=0 -> lower bound (exp/2); rng=1 -> upper bound (exp)
    expect(backoffDelay(0, { base: 1000, rng: () => 0 })).toBe(500);
    expect(backoffDelay(0, { base: 1000, rng: () => 1 })).toBe(1000);
    expect(backoffDelay(1, { base: 1000, rng: () => 0 })).toBe(1000);
    expect(backoffDelay(2, { base: 1000, rng: () => 1 })).toBe(4000);
  });

  it("is capped", () => {
    expect(backoffDelay(20, { base: 1000, cap: 30_000, rng: () => 1 })).toBe(30_000);
  });

  it("produces different values across attempts (jitter is applied)", () => {
    const a = backoffDelay(3, { base: 1000, rng: () => 0.1 });
    const b = backoffDelay(3, { base: 1000, rng: () => 0.9 });
    expect(a).not.toBe(b);
  });
});

describe("parseEnvelope", () => {
  it("parses a valid envelope", () => {
    const env = parseEnvelope(
      JSON.stringify({
        version: 1,
        event_id: "e1",
        event_type: "duplicate",
        occurred_at: "2024-01-01T00:00:00Z",
        data: { x: 1 },
      })
    );
    expect(env?.event_id).toBe("e1");
    expect(env?.event_type).toBe("duplicate");
  });

  it("returns null for malformed JSON", () => {
    expect(parseEnvelope("{not json")).toBeNull();
  });

  it("returns null when required fields are missing", () => {
    expect(parseEnvelope(JSON.stringify({ data: 1 }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ event_type: "x" }))).toBeNull();
  });
});

describe("EventDeduper", () => {
  it("treats each id as new only once", () => {
    const d = new EventDeduper();
    expect(d.isNew("a")).toBe(true);
    expect(d.isNew("a")).toBe(false);
    expect(d.isNew("b")).toBe(true);
  });

  it("evicts oldest ids beyond the bound", () => {
    const d = new EventDeduper(2);
    d.isNew("a");
    d.isNew("b");
    d.isNew("c"); // evicts "a"
    expect(d.isNew("a")).toBe(true); // seen again because evicted
  });
});
