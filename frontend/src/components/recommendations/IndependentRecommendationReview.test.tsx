import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import IndependentRecommendationReview from "./IndependentRecommendationReview";
import { submitRecommendedClassFeedback } from "../../services/classRecommendationApi";
import type { RecommendedClassCandidate } from "../../types/api_models";

const setClassNameInput = vi.fn();
const setSelectedMeasurements = vi.fn().mockResolvedValue(undefined);
const saveClass = vi.fn().mockResolvedValue(undefined);

vi.mock("../../services/classRecommendationApi", () => ({
  submitRecommendedClassFeedback: vi.fn(),
}));

vi.mock("../../store/useInfluxStore", () => ({
  useInfluxStore: {
    getState: () => ({
      setClassNameInput,
      setSelectedMeasurements,
      saveClass,
    }),
  },
}));

vi.mock("./RecommendationGraph", () => ({
  default: ({ topics }: { topics: string[] }) => (
    <div aria-label="Recommendation graph mock">{topics.join(",")}</div>
  ),
}));

const candidate: RecommendedClassCandidate = {
  candidate_id: "candidate-1",
  candidate_version: 2,
  rank: 1,
  anchor_topic: "a",
  member_topics: ["a", "b"],
  discovery_channels: ["key"],
  evidence: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(submitRecommendedClassFeedback).mockResolvedValue({
    feedback_id: "feedback",
    candidate_id: candidate.candidate_id,
    candidate_version: candidate.candidate_version,
    action_type: "KEEP_TOPIC",
    topic: null,
  });
});

it("updates graph membership and records explicit add/remove actions", async () => {
  render(
    <IndependentRecommendationReview
      candidate={candidate}
      availableTopics={["a", "b", "c"]}
      shadowRunId={null}
      liveRunId={null}
    />,
  );

  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("a,b");

  fireEvent.click(screen.getByRole("button", { name: "Remove b" }));
  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "REMOVE_TOPIC",
      candidate_version: 2,
      topic: "b",
    }),
  );
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("a");

  fireEvent.change(screen.getByLabelText("Topic to add"), { target: { value: "c" } });
  fireEvent.click(screen.getByRole("button", { name: "Add topic" }));
  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "ADD_TOPIC",
      candidate_version: 2,
      topic: "c",
    }),
  );
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("a,c");
});

it("saves only after the user chooses a final group and records final feedback", async () => {
  render(
    <IndependentRecommendationReview
      candidate={candidate}
      availableTopics={["a", "b", "c"]}
      shadowRunId={null}
      liveRunId={null}
    />,
  );

  fireEvent.change(screen.getByLabelText("Class name"), { target: { value: "My class" } });
  fireEvent.click(screen.getByRole("button", { name: "Save as Class" }));

  await waitFor(() => expect(saveClass).toHaveBeenCalled());
  expect(setClassNameInput).toHaveBeenCalledWith("My class");
  expect(setSelectedMeasurements).toHaveBeenCalledWith(["a", "b"]);
  expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
    action: "KEEP_TOPIC",
    candidate_version: 2,
    topic: "a",
  });
  expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
    action: "KEEP_TOPIC",
    candidate_version: 2,
    topic: "b",
  });
  expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
    action: "ACCEPT_CANDIDATE",
    candidate_version: 2,
  });
});
