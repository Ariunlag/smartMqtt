import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import RecommendationsPanel from "./RecommendationsPanel";
import type { RecommendationGroup, RecommendationSource } from "./recommendationModel";

/* The recommendation surface is shared by every experiment branch, so this
 * suite drives it through a fake source instead of a real algorithm. */

vi.mock("./RecommendationGraph", () => ({
  default: ({ topics }: { topics: string[] }) => (
    <div aria-label="Recommendation graph mock">{topics.join(",")}</div>
  ),
}));

const group: RecommendationGroup = {
  id: "g1",
  title: "Suggested group",
  status: "System suggestion",
  members: [
    {
      topic: "lab/a",
      detail: "Similarity: 0.900",
      confirmed: false,
      evidence: [
        {
          channelId: "topic_text",
          channelLabel: "Topic meaning",
          value: "0.900",
          detail: "Coverage 100% · 2 reference topics",
          matches: [
            {
              left: "lab a",
              right: "lab b",
              detail: null,
              leftValues: [1, 2, null, 4],
              rightValues: [2, 4, null, 8],
            },
          ],
        },
        {
          channelId: "series_shape",
          channelLabel: "Series shape",
          value: "missing",
          detail: null,
          matches: [],
        },
      ],
    },
    { topic: "lab/b", detail: "Similarity: 0.880", confirmed: false, evidence: [] },
  ],
  proposals: [{ topic: "lab/d", detail: "0.820" }],
  discoveryChannels: ["Topic meaning"],
  savedClass: null,
  dismissed: false,
  canUndo: true,
  reviewPending: true,
};

const makeSource = (overrides: Partial<RecommendationSource> = {}): RecommendationSource => ({
  loading: false,
  error: null,
  methods: [
    { id: "m1", label: "Method one", description: "First method." },
    { id: "m2", label: "Method two", description: "Second method." },
  ],
  activeMethodId: "m1",
  stats: [{ label: "Topics", value: "3" }],
  channels: [{ id: "topic_text", label: "Topic meaning", detail: "100.0%" }],
  details: ["Model version 2"],
  groups: [structuredClone(group)],
  availableTopics: ["lab/a", "lab/b", "lab/c"],
  refresh: vi.fn().mockResolvedValue(undefined),
  apply: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});

const memberRow = (topic: string) =>
  within(screen.getByRole("list", { name: "Suggested members" }))
    .getByText(topic)
    .closest("li") as HTMLElement;

it("lists groups in the sidebar and reviews the first one in the detail pane", () => {
  render(<RecommendationsPanel source={makeSource()} />);

  const list = screen.getByRole("list", { name: "Recommended groups" });
  expect(within(list).getByText("Suggested group")).toBeInTheDocument();
  expect(within(list).getByText("2 topics · System suggestion")).toBeInTheDocument();

  expect(screen.getByRole("heading", { name: "Suggested group", level: 4 })).toBeInTheDocument();
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("lab/a,lab/b");
  expect(screen.getAllByText("Duplicate review pending").length).toBe(1);
});

it("shows catalog-defined evidence and a truthful missing status", () => {
  render(<RecommendationsPanel source={makeSource()} />);

  const row = memberRow("lab/a");
  fireEvent.click(within(row).getByRole("button", { name: "Why?" }));

  expect(within(row).getByText("lab a ↔ lab b")).toBeInTheDocument();
  expect(within(row).getByText("Series shape")).toBeInTheDocument();
  expect(within(row).getByText("missing")).toBeInTheDocument();
  expect(
    within(row).getByRole("img", { name: /Time-series shape comparison/ }),
  ).toBeInTheDocument();
});

it("reports every membership edit through one action channel", async () => {
  const source = makeSource();
  render(<RecommendationsPanel source={source} />);

  fireEvent.click(screen.getByRole("button", { name: "Remove lab/b" }));
  await waitFor(() =>
    expect(source.apply).toHaveBeenCalledWith("g1", "remove", { topic: "lab/b" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent("lab/b removed.");

  fireEvent.click(within(memberRow("lab/a")).getByRole("button", { name: "Belongs" }));
  await waitFor(() =>
    expect(source.apply).toHaveBeenCalledWith("g1", "confirm", { topic: "lab/a" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Add topic" }));
  fireEvent.change(screen.getByLabelText("Topic to add"), { target: { value: "lab/c" } });
  fireEvent.click(screen.getByRole("button", { name: "Add selected topic" }));
  await waitFor(() =>
    expect(source.apply).toHaveBeenCalledWith("g1", "add", { topic: "lab/c" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent("lab/c added.");
});

it("saves the reviewed group as a Class", async () => {
  const source = makeSource();
  render(<RecommendationsPanel source={source} />);

  fireEvent.click(screen.getByRole("button", { name: "Save as Class" }));
  fireEvent.change(screen.getByLabelText("Class name"), { target: { value: "Sensors" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Class" }));

  await waitFor(() =>
    expect(source.apply).toHaveBeenCalledWith("g1", "save", { name: "Sensors" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent('Class "Sensors" saved.');
});

it("offers scored additions, usefulness feedback, and undo", async () => {
  const source = makeSource();
  render(<RecommendationsPanel source={source} />);

  fireEvent.click(screen.getByText("Suggested additions (1)"));
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(source.apply).toHaveBeenCalledWith("g1", "add", { topic: "lab/d" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Useful group" }));
  await waitFor(() => expect(source.apply).toHaveBeenCalledWith("g1", "useful", {}));

  fireEvent.click(screen.getByRole("button", { name: "Not useful" }));
  await waitFor(() => expect(source.apply).toHaveBeenCalledWith("g1", "dismiss", {}));

  fireEvent.click(screen.getByRole("button", { name: "Undo last edit" }));
  await waitFor(() => expect(source.apply).toHaveBeenCalledWith("g1", "undo", {}));
  expect(screen.getByRole("status")).toHaveTextContent("Edit undone.");
});

it("keeps the reviewed membership when an edit fails", async () => {
  const source = makeSource({
    apply: vi.fn().mockRejectedValue(new Error("This group changed. Refresh before editing.")),
  });
  render(<RecommendationsPanel source={source} />);

  fireEvent.click(screen.getByRole("button", { name: "Remove lab/b" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Refresh before editing");
  expect(screen.getByRole("button", { name: "Remove lab/b" })).toBeInTheDocument();
  expect(screen.getByLabelText("Recommendation graph mock")).toHaveTextContent("lab/a,lab/b");
});

it("re-requests the selected method without changing the surface", async () => {
  const source = makeSource();
  render(<RecommendationsPanel source={source} />);

  const selector = screen.getByRole("combobox", { name: "Recommendation method" });
  expect(selector).toHaveValue("m1");
  fireEvent.change(selector, { target: { value: "m2" } });

  await waitFor(() => expect(source.refresh).toHaveBeenCalledWith("m2"));
});

it("explains the method and states that viewing a graph is not feedback", () => {
  render(<RecommendationsPanel source={makeSource()} />);

  fireEvent.click(screen.getByText("Method details"));

  expect(screen.getByText("First method.")).toBeInTheDocument();
  expect(screen.getByText("Model version 2")).toBeInTheDocument();
  expect(screen.getByText(/Viewing a graph does not train the model/)).toBeInTheDocument();
});

it("invites a selection when the method returns no groups", () => {
  render(<RecommendationsPanel source={makeSource({ groups: [] })} />);

  expect(
    screen.getByText("No candidate groups in the current evidence snapshot."),
  ).toBeInTheDocument();
  expect(screen.getByText("Select a recommended group to review it.")).toBeInTheDocument();
});
