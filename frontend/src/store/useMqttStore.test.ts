import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock the topic API before importing the store.
vi.mock("../services/topicApi", () => ({
  subscribeTopic: vi.fn(),
  unsubscribeTopic: vi.fn(),
  getSubscribedTopics: vi.fn(),
}));

import { useMqttStore } from "./useMqttStore";
import * as topicApi from "../services/topicApi";
import type { MqttMessage } from "../types/mqtt";

const baseMsg = (over: Partial<MqttMessage> = {}): MqttMessage => ({
  topic: "t/a",
  tags: {},
  fields: { value: 1 },
  timestamp: "2024-01-01T00:00:00.000Z",
  ...over,
});

beforeEach(() => {
  useMqttStore.setState({ topics: ["t/a", "t/b"], messages: [] });
  vi.clearAllMocks();
});

describe("useMqttStore.removeTopic", () => {
  it("removes locally only after the backend confirms", async () => {
    (topicApi.unsubscribeTopic as ReturnType<typeof vi.fn>).mockResolvedValue({});
    await useMqttStore.getState().removeTopic("t/a");
    expect(useMqttStore.getState().topics).toEqual(["t/b"]);
  });

  it("keeps the topic and propagates the error when the backend fails", async () => {
    (topicApi.unsubscribeTopic as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("network")
    );
    await expect(useMqttStore.getState().removeTopic("t/a")).rejects.toThrow("network");
    // topic must NOT be silently removed
    expect(useMqttStore.getState().topics).toContain("t/a");
  });
});

describe("useMqttStore message ids", () => {
  it("assigns a unique event_id when one is missing", () => {
    useMqttStore.getState().addMessages([baseMsg(), baseMsg()]);
    const ids = useMqttStore.getState().messages.map((m) => m.event_id);
    expect(ids.every(Boolean)).toBe(true);
    expect(new Set(ids).size).toBe(ids.length); // all unique
  });

  it("preserves an existing event_id", () => {
    useMqttStore.getState().addMessage(baseMsg({ event_id: "server-1" }));
    expect(useMqttStore.getState().messages[0].event_id).toBe("server-1");
  });
});
