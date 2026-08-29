import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import RecommendationsManager from "./RecommendationsManager";
import {
  getRecommendedClassCandidates,
  submitRecommendedClassFeedback,
} from "../../services/classRecommendationApi";
import type { RecommendedClassCandidateSet } from "../../types/api_models";

vi.mock("../../services/classRecommendationApi", () => ({
  getRecommendedClassCandidates: vi.fn(),
  submitRecommendedClassFeedback: vi.fn(),
}));

const hdbscanStrategy = {
  strategy_id: "independent_hdbscan",
  label: "Independent evidence (HDBSCAN)",
  description:
    "Runs HDBSCAN separately for each evidence type and merges identical topic groups as consensus. No cross-evidence weighting is applied.",
};

const centroidStrategy = {
  strategy_id: "tag_value_centroid",
  label: "Tag value centroid",
  description:
    "Uses only tag pair value embeddings and the original nearest-centroid assignment idea. It is a baseline over the same stored evidence.",
};

const candidateSet: RecommendedClassCandidateSet = {
  available_topics: ["building/a", "building/b", "building/c"],
  strategy: hdbscanStrategy,
  strategy_catalog: [hdbscanStrategy, centroidStrategy],
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
  shadow_evaluation: {
    mode: "shadow",
    status: "scored",
    shadow_run_id: "11111111-1111-1111-1111-111111111111",
    ranking_effect: "none",
    baseline_order_preserved: true,
    persistence: { status: "stored", count: 1 },
  },
  live_ranking: {
    mode: "live",
    status: "applied",
    live_run_id: "22222222-2222-2222-2222-222222222222",
    ranking_effect: "same_order",
    membership_effect: "none",
    persistence: { status: "stored", count: 1 },
  },
  candidates: [
    {
      candidate_id: "candidate-1",
      candidate_version: 3,
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
  vi.mocked(submitRecommendedClassFeedback).mockResolvedValue({
    feedback_id: "feedback-1",
    candidate_id: "candidate-1",
    candidate_version: 3,
    action_type: "KEEP_TOPIC",
    topic: "building/a",
  });
});

it("keeps one recommendation surface and exposes registered methods", async () => {
  render(<RecommendationsManager />);

  expect(
    await screen.findByRole("heading", { name: "Recommended class #1" }),
  ).toBeInTheDocument();
  const selector = screen.getByRole("combobox", { name: "Recommendation method" });
  expect(selector).toHaveValue("independent_hdbscan");
  expect(screen.getByRole("option", { name: "Independent evidence (HDBSCAN)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Tag value centroid" })).toBeInTheDocument();
  expect(screen.getByText("Similar keys")).toBeInTheDocument();
  expect(screen.getByText("Similar structure")).toBeInTheDocument();
  expect(screen.getByText("Candidate version 3")).toBeInTheDocument();
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/numeric key/i)).not.toBeInTheDocument();
});

it("requests the selected strategy without changing the evidence UI", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1" });

  fireEvent.change(
    screen.getByRole("combobox", { name: "Recommendation method" }),
    { target: { value: "tag_value_centroid" } },
  );

  await waitFor(() =>
    expect(getRecommendedClassCandidates).toHaveBeenCalledWith("tag_value_centroid"),
  );
});

it("records topic membership feedback against the exact candidate and exposure", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1" });

  fireEvent.click(screen.getAllByRole("button", { name: "Belongs" })[0]);

  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "KEEP_TOPIC",
      candidate_version: 3,
      topic: "building/a",
      shadow_run_id: "11111111-1111-1111-1111-111111111111",
      live_run_id: "22222222-2222-2222-2222-222222222222",
    }),
  );
  expect(await screen.findByText("Recorded feedback for building/a.")).toBeInTheDocument();
});

it("records candidate usefulness without mutating Saved Classes", async () => {
  vi.mocked(submitRecommendedClassFeedback).mockResolvedValueOnce({
    feedback_id: "feedback-2",
    candidate_id: "candidate-1",
    candidate_version: 3,
    action_type: "ACCEPT_CANDIDATE",
    topic: null,
  });
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1" });

  fireEvent.click(screen.getByRole("button", { name: "Useful group" }));

  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "ACCEPT_CANDIDATE",
      candidate_version: 3,
      shadow_run_id: "11111111-1111-1111-1111-111111111111",
      live_run_id: "22222222-2222-2222-2222-222222222222",
    }),
  );
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
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
});