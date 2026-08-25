import { describe, expect, it } from "vitest";
import { shortenTopic } from "./lineChartService";

describe("shortenTopic", () => {
  it("leaves short topics untouched", () => {
    expect(shortenTopic("room/temp")).toBe("room/temp");
  });

  it("keeps the two trailing segments when the full topic is too long", () => {
    expect(shortenTopic("site/floor1/room3/sensor-a/temperature")).toBe(
      "…/sensor-a/temperature",
    );
  });

  it("falls back to one trailing segment when two still overflow", () => {
    expect(
      shortenTopic("site/floor1/room3/very-long-sensor-name/temperature"),
    ).toBe("…/temperature");
  });

  it("never exceeds the requested width, even without separators", () => {
    const label = shortenTopic("a".repeat(80), 24);
    expect(label.length).toBeLessThanOrEqual(24);
    expect(label.startsWith("…")).toBe(true);
  });

  it("truncates a single overlong segment rather than returning it whole", () => {
    const label = shortenTopic(`prefix/${"b".repeat(60)}`, 24);
    expect(label.length).toBeLessThanOrEqual(24);
  });
});
