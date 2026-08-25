import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import RecommendationsManager from "./RecommendationsManager";
import {
  applyClassAction,
  getClassRecommendations,
} from "../../services/classRecommendationApi";

vi.mock("../../services/classRecommendationApi", () => ({
  getClassRecommendations: vi.fn(),
  applyClassAction: vi.fn(),
}));

const getClasses = vi.fn();
vi.mock("../../store/useInfluxStore", () => ({
  useInfluxStore: (selector: (state: object) => unknown) =>
    selector({
      classes: [
        {
          class_id: "temperature-id",
          name: "Temperature",
          topics: ["reference/topic"],
          profile_version: 3,
        },
      ],
      getClasses,
    }),
}));

const recommendation = {
  recommendation_id: "rec-1",
  canonical_topic: "candidate/topic",
  original_topic: "candidate/topic",
  class_id: "temperature-id",
  class_name: "Temperature",
  rank: 1,
  overall_score: 0.88,
  channel_scores: {
    key: 0.95,
    value: 0.72,
    key_value: 0.92,
    schema: 0.94,
    numeric_key: 0.96,
    stream_context: 0.81,
  },
  valid_channels: ["key", "value", "key_value", "schema", "numeric_key", "stream_context"],
  coverage: {
    candidate_pair_count: 4,
    class_prototype_count: 5,
    matched_pair_count: 3,
    candidate_coverage: 0.75,
    prototype_coverage: 0.6,
  },
  matched_pairs: [
    {
      candidate: { source: "field", normalized_key: "temp", datatype: "numeric" },
      prototype: { source: "field", normalized_key: "temperature", datatype: "numeric" },
      prototype_id: "temperature-id:field:temperature:numeric",
      scores: { key: 0.97, value: 0.42, key_value: 0.94, schema: 0.99, numeric_key: 0.97 },
      compatibility_score: 0.858,
    },
  ],
  unmatched_candidate_pairs: [
    { source: "tag", normalized_key: "serial", datatype: "string" },
  ],
  unmatched_prototypes: [],
  class_profile_version: 3,
  topic_representation_version: 2,
  duplicate_pending: true,
  algorithm_version: "pair-greedy-equal-mean-v1",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getClassRecommendations).mockResolvedValue({
    class_name: "Temperature",
    recommendations: [recommendation],
  });
  vi.mocked(applyClassAction).mockResolvedValue({
    event_id: "event-1",
    action_type: "RECOMMENDATION_ACCEPT",
    canonical_topic: "candidate/topic",
    class_id: "temperature-id",
    class_name: "Temperature",
    class_profile_version: 4,
  });
});

it("shows factual pair evidence, coverage, and pending duplicate state without vectors", async () => {
  const { container } = render(<RecommendationsManager />);

  expect(
    await screen.findByRole("heading", { name: /candidate\/topic/ }),
  ).toBeInTheDocument();
  expect(screen.getByText("Duplicate review pending")).toBeInTheDocument();
  expect(screen.getByText(/Coverage 3 \/ 4 pairs/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show pair evidence" }));
  expect(screen.getByText("field/temp:numeric")).toBeInTheDocument();
  expect(screen.getByText("field/temperature:numeric")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/centroid|embedding|vector|dsn|credential|sql/i);
});

it("sends an exact versioned accept action and refreshes class state", async () => {
  render(<RecommendationsManager />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Accept Recommendation" }),
  );

  await waitFor(() =>
    expect(applyClassAction).toHaveBeenCalledWith("Temperature", {
      action: "RECOMMENDATION_ACCEPT",
      topic: "candidate/topic",
      topic_representation_version: 2,
      class_profile_version: 3,
      recommendation_id: "rec-1",
    }),
  );
  expect(getClasses).toHaveBeenCalled();
});

it("labels manual member removal distinctly from recommendation rejection", async () => {
  render(<RecommendationsManager />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Remove member reference/topic" }),
  );
  await waitFor(() =>
    expect(applyClassAction).toHaveBeenCalledWith("Temperature", {
      action: "MANUAL_REMOVE",
      topic: "reference/topic",
    }),
  );
  expect(screen.getByRole("button", { name: "Reject Recommendation" })).toBeInTheDocument();
});
