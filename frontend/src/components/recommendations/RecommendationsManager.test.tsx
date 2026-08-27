import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import RecommendationsManager from "./RecommendationsManager";
import { getRecommendedClassCandidates } from "../../services/classRecommendationApi";
import type { RecommendedClassCandidateSet } from "../../types/api_models";

vi.mock("../../services/classRecommendationApi", () => ({
  getRecommendedClassCandidates: vi.fn(),
}));

const candidateSet: RecommendedClassCandidateSet = {
  available_topics: ["building/a", "building/b", "building/c"],
  evidence_catalog: [
    { evidence_id: "key", label: "Similar keys", scope: "pair" },
    { evidence_id: "value", label: "Similar values", scope: "pair" },
    { evidence_id: "key_value", label: "Similar key + value meaning", scope: "pair" },
    { evidence_id: "schema", label: "Similar structure", scope: "pair" },
    {
      evidence_id: "stream_context",
      label: "Similar whole-stream context",
      scope: "stream",
    },
  ],
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
            items: [
              { evidence_id: "key", score: 0.96 },
              { evidence_id: "value", score: 0.71 },
              { evidence_id: "key_value", score: 0.91 },
              { evidence_id: "schema", score: 0.98 },
              { evidence_id: "stream_context", score: 0.89 },
            ],
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
                items: [
                  { evidence_id: "key", score: 0.98 },
                  { evidence_id: "value", score: 0.97 },
                  { evidence_id: "key_value", score: 0.98 },
                  { evidence_id: "schema", score: 1 },
                ],
              },
              compatibility_score: 0.9825,
            },
            {
              candidate: { source: "field", normalized_key: "temp", datatype: "numeric" },
              prototype: { source: "field", normalized_key: "temperature", datatype: "numeric" },
              prototype_id: "building/a:field:temperature:numeric",
              scores: {
                items: [
                  { evidence_id: "key", score: 0.94 },
                  { evidence_id: "value", score: 0.45 },
                  { evidence_id: "key_value", score: 0.89 },
                  { evidence_id: "schema", score: 0.96 },
                ],
              },
              compatibility_score: 0.81,
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
  expect(screen.getAllByText("Similar whole-stream context").length).toBeGreaterThan(0);
  expect(screen.queryByText("Saved class")).not.toBeInTheDocument();
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/numeric key/i)).not.toBeInTheDocument();
});

it("shows tag, field, coverage, and catalog-driven pair evidence without a fused score", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1" });

  expect(screen.getByText("Duplicate review pending")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show evidence" }));

  expect(screen.getByText(/Matched 2 \/ 3 candidate pairs/)).toBeInTheDocument();
  expect(screen.getAllByText("Tag evidence").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Field evidence").length).toBeGreaterThan(0);
  expect(screen.getByText(/unit:string ↔ unit:string/)).toBeInTheDocument();
  expect(screen.getByText(/temp:numeric ↔ temperature:numeric/)).toBeInTheDocument();
  expect(screen.getAllByText(/Similar keys 98.0%|Similar keys 94.0%/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
});
