import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import RecommendationsManager from "./RecommendationsManager";
import { getRecommendedClassCandidates } from "../../services/classRecommendationApi";

vi.mock("../../services/classRecommendationApi", () => ({
  getRecommendedClassCandidates: vi.fn(),
}));

const candidateSet = {
  available_topics: ["building/a", "building/b", "building/c"],
  candidates: [
    {
      candidate_id: "candidate-1",
      rank: 1,
      anchor_topic: "building/a",
      member_topics: ["building/a", "building/b"],
      discovery_channels: ["key", "schema", "stream_context"],
      evidence: [
        {
          topic: "building/b",
          channel_scores: {
            key: 0.96,
            value: 0.71,
            key_value: 0.91,
            schema: 0.98,
            numeric_key: 0.95,
            stream_context: 0.89,
          },
          coverage: {
            candidate_pair_count: 3,
            class_prototype_count: 3,
            matched_pair_count: 2,
            candidate_coverage: 2 / 3,
            prototype_coverage: 2 / 3,
          },
          matched_pairs: [
            {
              candidate: { source: "tag", normalized_key: "unit", datatype: "string" },
              prototype: { source: "tag", normalized_key: "unit", datatype: "string" },
              prototype_id: "building/a:tag:unit:string",
              scores: {
                key: 0.98,
                value: 0.97,
                key_value: 0.98,
                schema: 1,
                numeric_key: null,
              },
              compatibility_score: 0.9825,
            },
            {
              candidate: { source: "field", normalized_key: "temp", datatype: "numeric" },
              prototype: { source: "field", normalized_key: "temperature", datatype: "numeric" },
              prototype_id: "building/a:field:temperature:numeric",
              scores: {
                key: 0.94,
                value: 0.45,
                key_value: 0.89,
                schema: 0.96,
                numeric_key: 0.95,
              },
              compatibility_score: 0.838,
            },
          ],
          duplicate_pending: true,
        },
      ],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getRecommendedClassCandidates).mockResolvedValue(candidateSet);
});

it("keeps Saved Classes out of system recommendations and explains independent evidence", async () => {
  render(<RecommendationsManager />);

  expect(
    await screen.findByRole("heading", { name: "Recommended class #1" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Similar keys")).toBeInTheDocument();
  expect(screen.getByText("Similar structure")).toBeInTheDocument();
  expect(screen.getByText("Similar whole-stream context")).toBeInTheDocument();
  expect(screen.queryByText("Saved class")).not.toBeInTheDocument();
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
});

it("shows tag, field, coverage, and whole-stream evidence without a fused score", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1" });

  expect(screen.getByText("Duplicate review pending")).toBeInTheDocument();
  expect(screen.getByText("Tag evidence").nextSibling?.textContent ?? "").not.toContain("Overall");
  fireEvent.click(screen.getByRole("button", { name: "Show evidence" }));

  expect(screen.getByText(/Matched 2 \/ 3 candidate pairs/)).toBeInTheDocument();
  expect(screen.getAllByText("Tag evidence").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Field evidence").length).toBeGreaterThan(0);
  expect(screen.getByText(/unit:string ↔ unit:string/)).toBeInTheDocument();
  expect(screen.getByText(/temp:numeric ↔ temperature:numeric/)).toBeInTheDocument();
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
});
