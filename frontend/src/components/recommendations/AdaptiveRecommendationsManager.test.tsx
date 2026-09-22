import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import AdaptiveRecommendationsManager from "./AdaptiveRecommendationsManager";
import { editAdaptiveGroup, getAdaptiveRecommendations } from "../../services/adaptiveRecommendationApi";
import type { AdaptiveGroup, AdaptiveResponse } from "../../services/adaptiveRecommendationApi";

vi.mock("../../services/adaptiveRecommendationApi", () => ({getAdaptiveRecommendations: vi.fn(), editAdaptiveGroup: vi.fn()}));
vi.mock("../../store/useInfluxStore", () => ({useInfluxStore: {getState: () => ({getClasses: vi.fn()})}}));
vi.mock("./RecommendationGraph", () => ({default: ({topics}: {topics: string[]}) => <div aria-label="Recommendation graph mock">{topics.join(",")}</div>}));

const group: AdaptiveGroup = {group_id: "g1", revision: 1, name: null, members: ["lab/a", "lab/b"],
  saved_class: null, dismissed: false, edited: false, can_undo: false, confirmed: [],
  evidence: {"lab/a": {topic_text: {score: .9, status: "available", coverage: 1,
    matches: [{left: {text: "lab a"}, right: {text: "lab b"}, similarity: .9}]}}},
  proposals: [], member_scores: {"lab/a": .9, "lab/b": .9}};
const response: AdaptiveResponse = {environment_id: "Lab", catalog: [
  {evidence_id: "topic_text", label: "Topic meaning", scope: "stream", active: true, kind: "embedding"},
  {evidence_id: "series_shape", label: "Series shape", scope: "series_window", active: false, kind: "direct_similarity"}],
  model: {version: 0, weights: {topic_text: 1}, status: "baseline", updated_at: null},
  feedback_count: 0, background_error: null, available_topics: ["lab/a", "lab/b", "lab/c"], groups: [group], threshold: .8};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAdaptiveRecommendations).mockResolvedValue(structuredClone(response));
});

it("renders catalog-defined future evidence and truthful missing status", async () => {
  render(<AdaptiveRecommendationsManager />);
  await screen.findByText("Environment:", {exact: false});
  const row = screen.getAllByRole("listitem")[0];
  fireEvent.click(within(row).getByRole("button", {name: "Why?"}));
  expect(within(row).getByText("lab a ↔ lab b")).toBeInTheDocument();
  expect(within(row).getByText("Series shape")).toBeInTheDocument();
  expect(within(row).getByText("missing")).toBeInTheDocument();
});

it("removes members immediately and undo restores server membership", async () => {
  vi.mocked(editAdaptiveGroup).mockResolvedValueOnce({...group, revision: 2, members: ["lab/a"], can_undo: true, edited: true})
    .mockResolvedValueOnce({...group, revision: 3});
  render(<AdaptiveRecommendationsManager />);
  fireEvent.click(await screen.findByRole("button", {name: "Review graph"}));
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("lab/a,lab/b");
  fireEvent.click(screen.getByRole("button", {name: "Remove lab/b"}));
  await screen.findByText("lab/b removed.");
  expect(screen.queryByRole("button", {name: "Remove lab/b"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("lab/a");
  fireEvent.click(screen.getByRole("button", {name: "Undo last edit"}));
  expect(await screen.findByRole("button", {name: "Remove lab/b"})).toBeInTheDocument();
  expect(vi.mocked(editAdaptiveGroup).mock.calls[1][0].revision).toBe(2);
});

it("adds an outside topic and saves the edited group as a Class", async () => {
  const added = {...group, revision: 2, members: [...group.members, "lab/c"], can_undo: true};
  vi.mocked(editAdaptiveGroup).mockResolvedValueOnce(added).mockResolvedValueOnce({...added, revision: 3, name: "Sensors", saved_class: "Sensors"});
  render(<AdaptiveRecommendationsManager />);
  fireEvent.click(await screen.findByRole("button", {name: "Add topic", exact: true}));
  fireEvent.change(screen.getByLabelText("Topic to add"), {target: {value: "lab/c"}});
  fireEvent.click(screen.getByRole("button", {name: "Add selected topic"}));
  await screen.findByRole("button", {name: "Remove lab/c"});
  fireEvent.click(screen.getByRole("button", {name: "Save as Class"}));
  fireEvent.change(screen.getByLabelText("Class name"), {target: {value: "Sensors"}});
  fireEvent.click(screen.getByRole("button", {name: "Save Class", exact: true}));
  expect(await screen.findByRole("heading", {name: "Sensors"})).toBeInTheDocument();
  expect(vi.mocked(editAdaptiveGroup).mock.calls[1].slice(1)).toEqual(["save", {name: "Sensors"}]);
});

it("retains membership when an edit fails", async () => {
  vi.mocked(editAdaptiveGroup).mockRejectedValue(new Error("This group changed. Refresh before editing."));
  render(<AdaptiveRecommendationsManager />);
  fireEvent.click(await screen.findByRole("button", {name: "Remove lab/b"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Refresh before editing");
  expect(screen.getByRole("button", {name: "Remove lab/b"})).toBeInTheDocument();
});

it("shows missing-sample shape charts and the approximate-search limitation", async () => {
  const result = structuredClone(response);
  result.discovery = {mode: "approximate", algorithm: "projection", scored_pairs: 20, possible_pairs: 100, elapsed_seconds: .1};
  result.groups[0].evidence["lab/a"].series_shape = {status: "available", score: .9, coverage: .75,
    matches: [{left: {text: "power", values: [1, 2, null, 4]}, right: {text: "load", values: [2, 4, null, 8]}, similarity: .9}]};
  vi.mocked(getAdaptiveRecommendations).mockResolvedValue(result);
  render(<AdaptiveRecommendationsManager />);
  await screen.findByText("Environment:", {exact: false});
  fireEvent.click(within(screen.getAllByRole("listitem")[0]).getByRole("button", {name: "Why?"}));
  expect(screen.getByRole("img", {name: /Time-series shape comparison/})).toBeInTheDocument();
  expect(screen.getByText(/Approximate search can miss matching topics/)).toBeInTheDocument();
});
