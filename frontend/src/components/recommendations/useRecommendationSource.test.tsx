import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import RecommendationsManager from "./RecommendationsManager";
import {
  getRecommendedClassCandidates,
  submitRecommendedClassFeedback,
} from "../../services/classRecommendationApi";
import type { RecommendedClassCandidateSet } from "../../types/api_models";

/* Branch-local: independent evidence discovery mapped onto the shared surface. */

const setClassNameInput = vi.fn();
const setSelectedMeasurements = vi.fn().mockResolvedValue(undefined);
const saveClass = vi.fn().mockResolvedValue(undefined);

vi.mock("../../services/classRecommendationApi", () => ({
  getRecommendedClassCandidates: vi.fn(),
  submitRecommendedClassFeedback: vi.fn(),
}));
vi.mock("../../store/useInfluxStore", () => ({
  useInfluxStore: {
    getState: () => ({ setClassNameInput, setSelectedMeasurements, saveClass }),
  },
}));
vi.mock("./RecommendationGraph", () => ({
  default: ({ topics }: { topics: string[] }) => (
    <div aria-label="Recommendation graph mock">{topics.join(",")}</div>
  ),
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
    { evidence_id: "stream_context", label: "Similar whole-stream context", scope: "stream" },
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
      discovery_support: [
        {
          evidence_id: "key",
          items: [
            { topic: "building/a", text: "unit", similarity: 0.99, source: "tag" },
            { topic: "building/b", text: "unit", similarity: 0.98, source: "tag" },
          ],
        },
        {
          evidence_id: "schema",
          items: [
            { topic: "building/a", text: "temperature: numeric", similarity: 0.97, source: "field" },
            { topic: "building/b", text: "temp: numeric", similarity: 0.96, source: "field" },
          ],
        },
        {
          evidence_id: "stream_context",
          items: [
            { topic: "building/a", text: null, similarity: 0.94, source: "stream" },
            { topic: "building/b", text: null, similarity: 0.93, source: "stream" },
          ],
        },
      ],
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


const centroidSet: RecommendedClassCandidateSet = {
  ...candidateSet,
  strategy: centroidStrategy,
  shadow_evaluation: undefined,
  live_ranking: undefined,
  candidates: [
    {
      candidate_id: "centroid-1",
      candidate_version: 1,
      rank: 1,
      anchor_topic: "building/a",
      member_topics: ["building/a", "building/c"],
      discovery_channels: ["value"],
      discovery_support: [
        {
          evidence_id: "value",
          items: [
            { topic: "building/a", text: "Chicago", similarity: 0.96, source: "tag" },
            { topic: "building/c", text: "Chicagoland", similarity: 0.94, source: "tag" },
          ],
        },
      ],
      evidence: [],
    },
  ],
};

const memberRow = (topic: string) =>
  within(screen.getByRole("list", { name: "Suggested members" }))
    .getByText(topic)
    .closest("li") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getRecommendedClassCandidates).mockResolvedValue(structuredClone(candidateSet));
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
    await screen.findByRole("heading", { name: "Recommended class #1", level: 4 }),
  ).toBeInTheDocument();
  const selector = screen.getByRole("combobox", { name: "Recommendation method" });
  expect(selector).toHaveValue("independent_hdbscan");
  expect(screen.getByRole("option", { name: "Independent evidence (HDBSCAN)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Tag value centroid" })).toBeInTheDocument();
  expect(screen.getAllByText("Duplicate review pending").length).toBe(1);
  expect(screen.queryByText(/Overall similarity/i)).not.toBeInTheDocument();
});

it("names the discovery channels that produced the candidate", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  const reasons = screen.getByRole("region", { name: "Recommendation reasons" });
  expect(within(reasons).getByText("Similar key")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar structure")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar stream context")).toBeInTheDocument();
  expect(within(reasons).queryByText("Shared value")).not.toBeInTheDocument();
});

it("switches to the distinct centroid method and shows only value evidence", async () => {
  vi.mocked(getRecommendedClassCandidates).mockReset();
  vi.mocked(getRecommendedClassCandidates)
    .mockResolvedValueOnce(structuredClone(candidateSet))
    .mockResolvedValueOnce(structuredClone(centroidSet));

  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  fireEvent.change(screen.getByRole("combobox", { name: "Recommendation method" }), {
    target: { value: "tag_value_centroid" },
  });

  await waitFor(() =>
    expect(getRecommendedClassCandidates).toHaveBeenCalledWith("tag_value_centroid"),
  );

  const reasons = await screen.findByRole("region", { name: "Recommendation reasons" });
  expect(within(reasons).getByText("Shared value")).toBeInTheDocument();
  expect(within(reasons).getByText("Chicago")).toBeInTheDocument();
  expect(within(reasons).getByText("Chicagoland")).toBeInTheDocument();
  expect(within(reasons).queryByText("Similar key")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("Method details"));
  expect(screen.getByText("Centroid input")).toBeInTheDocument();
  expect(screen.queryByText("Independent evidence")).not.toBeInTheDocument();
});

it("shows compact shared evidence without cluster jargon or per-member Why panels", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  const reasons = screen.getByRole("region", { name: "Recommendation reasons" });
  expect(within(reasons).getByText("Similar key")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar structure")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar stream context")).toBeInTheDocument();
  expect(within(reasons).queryByText("Shared value")).not.toBeInTheDocument();

  // Repeated identical evidence is shown once at group level.
  expect(within(reasons).getAllByText("unit")).toHaveLength(1);
  expect(within(reasons).getByText("Exact shared match")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar tag and field structure across these topics.")).toBeInTheDocument();
  expect(within(reasons).getByText("Similar whole-stream context across these topics.")).toBeInTheDocument();

  expect(screen.queryByText(/discovery cluster/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/cluster member/i)).not.toBeInTheDocument();

  for (const topic of ["building/a", "building/b"]) {
    const row = memberRow(topic);
    expect(within(row).queryByText("Matches the shared evidence above")).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Why?" })).not.toBeInTheDocument();
  }
});

it("records membership edits against the candidate version and undoes them", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent(
    "building/a,building/b",
  );

  fireEvent.click(screen.getByRole("button", { name: "Remove building/b" }));
  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "REMOVE_TOPIC",
      candidate_version: 3,
      topic: "building/b",
      shadow_run_id: "11111111-1111-1111-1111-111111111111",
      live_run_id: "22222222-2222-2222-2222-222222222222",
    }),
  );
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("building/a");

  fireEvent.click(screen.getByRole("button", { name: "Undo last edit" }));
  expect(await screen.findByRole("button", { name: "Remove building/b" })).toBeInTheDocument();
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent(
    "building/a,building/b",
  );
});

it("adds an outside topic as explicit feedback", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  fireEvent.click(screen.getByRole("button", { name: "Add topic" }));
  fireEvent.change(screen.getByLabelText("Topic to add"), { target: { value: "building/c" } });
  fireEvent.click(screen.getByRole("button", { name: "Add selected topic" }));

  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "ADD_TOPIC",
      candidate_version: 3,
      topic: "building/c",
      shadow_run_id: "11111111-1111-1111-1111-111111111111",
      live_run_id: "22222222-2222-2222-2222-222222222222",
    }),
  );
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent(
    "building/a,building/b,building/c",
  );
});

it("saves only the reviewed group and records the final membership", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  fireEvent.click(screen.getByRole("button", { name: "Save as Class" }));
  fireEvent.change(screen.getByLabelText("Class name"), { target: { value: "My class" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Class" }));

  await waitFor(() => expect(saveClass).toHaveBeenCalled());
  expect(setClassNameInput).toHaveBeenCalledWith("My class");
  expect(setSelectedMeasurements).toHaveBeenCalledWith(["building/a", "building/b"]);
  for (const topic of ["building/a", "building/b"]) {
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith(
      "candidate-1",
      expect.objectContaining({ action: "KEEP_TOPIC", candidate_version: 3, topic }),
    );
  }
  expect(submitRecommendedClassFeedback).toHaveBeenCalledWith(
    "candidate-1",
    expect.objectContaining({ action: "ACCEPT_CANDIDATE", candidate_version: 3 }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent('Class "My class" saved.');
});

it("records candidate usefulness without mutating Saved Classes", async () => {
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  fireEvent.click(screen.getByRole("button", { name: "Useful group" }));

  await waitFor(() =>
    expect(submitRecommendedClassFeedback).toHaveBeenCalledWith("candidate-1", {
      action: "ACCEPT_CANDIDATE",
      candidate_version: 3,
      shadow_run_id: "11111111-1111-1111-1111-111111111111",
      live_run_id: "22222222-2222-2222-2222-222222222222",
    }),
  );
  expect(saveClass).not.toHaveBeenCalled();
});

it("keeps the reviewed membership when feedback fails", async () => {
  vi.mocked(submitRecommendedClassFeedback).mockRejectedValue(
    new Error("Candidate version is stale. Refresh before editing."),
  );
  render(<RecommendationsManager />);
  await screen.findByRole("heading", { name: "Recommended class #1", level: 4 });

  fireEvent.click(screen.getByRole("button", { name: "Remove building/b" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Refresh before editing");
  expect(screen.getByRole("button", { name: "Remove building/b" })).toBeInTheDocument();
});
