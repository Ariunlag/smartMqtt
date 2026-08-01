import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SemanticOperationsPanel from "./SemanticOperationsPanel";
import {
  deriveDiscoveryState,
  derivePersistenceState,
  deriveProcessingState,
  deriveSummaryState,
} from "./semanticOperationsState";

const api = vi.hoisted(() => ({
  getSemanticProcessingStatus: vi.fn(),
  getSemanticDiscoveryStatus: vi.fn(),
  getSemanticPersistenceStatus: vi.fn(),
  getSemanticReviewState: vi.fn(),
  getSemanticClasses: vi.fn(),
  getSemanticReviewConstraints: vi.fn(),
}));

vi.mock("../../services/semanticReviewApi", () => api);

const processing = {
  running: true,
  enabled: true,
  queue_size: 0,
  queue_capacity: 256,
  submitted_count: 8,
  processed_count: 7,
  failed_count: 4,
  dropped_count: 0,
  last_processed_topic: "topic/A",
  last_error_topic: "topic/old",
  last_error_message: null,
};

const discovery = {
  running: true,
  enabled: true,
  request_pending: false,
  pool_version: 9,
  last_processed_version: 9,
  run_count: 3,
  published_count: 2,
  failed_count: 5,
  stale_discard_count: 1,
  candidate_count: 2,
  noise_topic_count: 1,
  last_error_message: null,
};

const persistence = {
  enabled: true,
  running: true,
  restored: true,
  degraded: false,
  schema_version: 1,
  current_generation: 12,
  persisted_generation: 12,
  save_pending: false,
  save_count: 6,
  restore_count: 1,
  failed_save_count: 3,
  failed_restore_count: 2,
  last_saved_at: "2026-07-31T12:00:00Z",
  last_restored_at: "2026-07-31T11:00:00Z",
  last_error_message: null,
  compatibility_error: null,
};

const reviewState = {
  candidates: [
    {
      representation_name: "key_value",
      member_topics: ["topic/A", "topic/B"],
      candidate_index: 0,
    },
  ],
  available_unknown_topics: ["topic/A", "topic/B", "topic/C"],
};

function resolveAll() {
  api.getSemanticProcessingStatus.mockResolvedValue(processing);
  api.getSemanticDiscoveryStatus.mockResolvedValue(discovery);
  api.getSemanticPersistenceStatus.mockResolvedValue(persistence);
  api.getSemanticReviewState.mockResolvedValue(reviewState);
  api.getSemanticClasses.mockResolvedValue({
    classes: [
      { class_id: "temperature", semantic_class_name: "Temperature" },
      { class_id: "humidity", semantic_class_name: "Humidity" },
    ],
  });
  api.getSemanticReviewConstraints.mockResolvedValue({
    constraints: [{ topic: "topic/C", semantic_class_name: "Temperature" }],
  });
}

beforeEach(() => {
  vi.useRealTimers();
  for (const request of Object.values(api)) request.mockReset();
  resolveAll();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("semantic operations status derivation", () => {
  it("uses only the allowed deterministic display states", () => {
    expect(deriveProcessingState(null)).toBe("STARTING");
    expect(deriveProcessingState({ ...processing, enabled: false })).toBe("DISABLED");
    expect(deriveProcessingState({ ...processing, queue_size: 2 })).toBe("BUSY");
    expect(deriveProcessingState({ ...processing, running: false })).toBe("STOPPED");
    expect(
      deriveDiscoveryState({ ...discovery, last_error_message: "failed" }),
    ).toBe("DEGRADED");
    expect(derivePersistenceState({ ...persistence, save_pending: true })).toBe("BUSY");
    expect(deriveSummaryState(true, 1, false)).toBe("BUSY");
    expect(deriveSummaryState(true, 0, false)).toBe("HEALTHY");
  });

  it("does not mark recovered services degraded from historical counters", () => {
    expect(deriveProcessingState(processing)).toBe("HEALTHY");
    expect(deriveDiscoveryState(discovery)).toBe("HEALTHY");
    expect(derivePersistenceState(persistence)).toBe("HEALTHY");
  });
});

describe("SemanticOperationsPanel loading", () => {
  it("isolates endpoint failures and retains latest successful endpoint data", async () => {
    render(<SemanticOperationsPanel />);
    const summary = await screen.findByRole("article", {
      name: "Semantic state summary",
    });
    expect(within(summary).getByText("Known classes").nextSibling).toHaveTextContent("2");

    api.getSemanticClasses.mockRejectedValueOnce(new Error("classes unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("classes unavailable")).toBeInTheDocument();
    expect(within(summary).getByText("Known classes").nextSibling).toHaveTextContent("2");
    expect(within(summary).getByText("DEGRADED")).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Processing" })).getByText("HEALTHY"))
      .toBeInTheDocument();
  });

  it("performs a manual refresh", async () => {
    render(<SemanticOperationsPanel />);
    await screen.findByText("Semantic operations");
    await waitFor(() => expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(2));
  });

  it("does not render sensitive or vector fields from oversized responses", async () => {
    api.getSemanticPersistenceStatus.mockResolvedValue({
      ...persistence,
      payload: "raw-secret-payload",
      dsn: "postgresql://secret",
      sql: "select secret",
    });
    api.getSemanticReviewState.mockResolvedValue({
      ...reviewState,
      embeddings: "vector-secret",
      centroid: "centroid-secret",
    });
    const { container } = render(<SemanticOperationsPanel />);
    await screen.findByText("Generation");
    await waitFor(() => expect(api.getSemanticReviewState).toHaveBeenCalled());

    const text = container.textContent?.toLowerCase() ?? "";
    for (const sensitive of [
      "raw-secret-payload",
      "postgresql://secret",
      "select secret",
      "vector-secret",
      "centroid-secret",
    ]) {
      expect(text).not.toContain(sensitive);
    }
  });

  it("polls every five seconds without overlapping cycles", async () => {
    vi.useFakeTimers();
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const delayedValues = [
      processing,
      discovery,
      persistence,
      reviewState,
      { classes: [] },
      { constraints: [] },
    ];
    Object.values(api).forEach((request, index) => {
      request.mockImplementationOnce(async () => {
        await pending;
        return delayedValues[index];
      });
    });

    render(<SemanticOperationsPanel />);
    expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      release();
      await pending;
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_999);
    });
    expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.getSemanticProcessingStatus).toHaveBeenCalledTimes(2);
  });

  it("clears its polling timer on unmount", () => {
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const { unmount } = render(<SemanticOperationsPanel />);
    unmount();
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    clearIntervalSpy.mockRestore();
  });
});
