import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";
import { useConnectionStore } from "../store/useConnectionStore";
import { useMqttStore } from "../store/useMqttStore";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useGroupStore } from "../store/useGroupStore";
import { useInfluxStore } from "../store/useInfluxStore";

class MockWebSocket {
  static OPEN = 1;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(data: string) {
    this.onmessage?.({ data });
  }
}

const latest = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

const envelope = (event_type: string, data: unknown, event_id: string) =>
  JSON.stringify({
    version: 1,
    event_id,
    event_type,
    occurred_at: "2024-01-01T00:00:00Z",
    data,
  });

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  MockWebSocket.instances = [];
  useConnectionStore.setState({ status: "connecting", lastConnectedAt: null });

  // Neutralize REST fetchers so resync doesn't hit the network.
  vi.spyOn(useMqttStore.getState(), "getTopics").mockResolvedValue();
  vi.spyOn(useDuplicateStore.getState(), "getDuplicates").mockResolvedValue();
  vi.spyOn(useGroupStore.getState(), "fetchGroups").mockResolvedValue();
  vi.spyOn(useInfluxStore.getState(), "getMeasurements").mockResolvedValue();
  vi.spyOn(useInfluxStore.getState(), "getClasses").mockResolvedValue();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useWebSocket", () => {
  it("connects and reports connected status", () => {
    renderHook(() => useWebSocket(true));
    act(() => latest().open());
    expect(useConnectionStore.getState().status).toBe("connected");
  });

  it("reconnects after the socket closes and resyncs REST baseline", () => {
    renderHook(() => useWebSocket(true));
    act(() => latest().open());
    expect(useMqttStore.getState().getTopics).not.toHaveBeenCalled(); // no resync on first connect

    const before = MockWebSocket.instances.length;
    act(() => latest().close());
    expect(useConnectionStore.getState().status).toBe("reconnecting");

    // advance past the (capped) backoff so a new socket is created
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances.length).toBe(before + 1);

    act(() => latest().open());
    expect(useConnectionStore.getState().status).toBe("connected");
    expect(useMqttStore.getState().getTopics).toHaveBeenCalledTimes(1); // resync after reconnect
  });

  it("goes offline after repeated failed reconnects", () => {
    renderHook(() => useWebSocket(true));
    act(() => latest().open());
    for (let i = 0; i < 4; i++) {
      act(() => latest().close());
      act(() => vi.advanceTimersByTime(30_000));
    }
    expect(useConnectionStore.getState().status).toBe("offline");
  });

  it("handles duplicate events idempotently", () => {
    const addDuplicate = vi
      .spyOn(useDuplicateStore.getState(), "addDuplicate")
      .mockImplementation(() => {});
    renderHook(() => useWebSocket(true));
    act(() => latest().open());

    const evt = envelope("duplicate", { topics: ["a", "b"], score: 0.9, status: "PENDING" }, "dup-1");
    act(() => {
      latest().emit(evt);
      latest().emit(evt); // same event_id -> ignored
    });
    expect(addDuplicate).toHaveBeenCalledTimes(1);
  });

  it("ignores malformed messages without throwing", () => {
    const addDuplicate = vi
      .spyOn(useDuplicateStore.getState(), "addDuplicate")
      .mockImplementation(() => {});
    renderHook(() => useWebSocket(true));
    act(() => latest().open());

    expect(() => act(() => latest().emit("{not-json"))).not.toThrow();
    expect(addDuplicate).not.toHaveBeenCalled();
  });
});
