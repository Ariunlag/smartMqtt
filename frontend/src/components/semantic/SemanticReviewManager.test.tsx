import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SemanticReviewManager from "./SemanticReviewManager";

const api = vi.hoisted(() => ({
  getSemanticReviewState: vi.fn(),
  submitSemanticReview: vi.fn(),
}));

vi.mock("../../services/semanticReviewApi", () => api);

const state = {
  candidates: [
    {
      representation_name: "key_value",
      member_topics: ["topic/A", "topic/B"],
      candidate_index: 3,
    },
  ],
  available_unknown_topics: ["topic/A", "topic/B", "topic/C"],
};

const result = {
  class_id: "temperature",
  semantic_class_name: "Temperature",
  registry_updated: true,
  positive_topics: ["topic/A", "topic/C"],
  removed_topics: ["topic/B"],
  changed_representations: [
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
  ],
  constraints_added: [
    { topic: "topic/B", semantic_class_name: "Temperature" },
  ],
  constraints_removed: [],
  prototypes: [
    {
      representation_name: "value_only",
      member_topics: ["topic/A", "topic/C"],
      member_count: 2,
    },
  ],
};

beforeEach(() => {
  api.getSemanticReviewState.mockReset();
  api.submitSemanticReview.mockReset();
  api.getSemanticReviewState.mockResolvedValue(state);
});

describe("SemanticReviewManager", () => {
  it("edits the exact partition, reports diagnostics, and removes a successful candidate", async () => {
    api.submitSemanticReview.mockResolvedValue(result);
    render(<SemanticReviewManager />);

    expect(await screen.findByText("key_value")).toBeInTheDocument();
    expect(screen.getByText("topic/A")).toBeInTheDocument();
    expect(screen.getByText("topic/B")).toBeInTheDocument();
    for (const topic of ["topic/A", "topic/B"]) {
      expect(
        within(screen.getByRole("group", { name: `Membership for ${topic}` }))
          .getByRole("button", { name: "Keep" }),
      ).toHaveAttribute("aria-pressed", "true");
    }
    expect(screen.getByRole("button", { name: "Apply review" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Semantic class ID"), {
      target: { value: "temperature" },
    });
    fireEvent.change(screen.getByLabelText("Semantic class name"), {
      target: { value: "Temperature" },
    });
    fireEvent.click(
      within(screen.getByRole("group", { name: "Membership for topic/B" }))
        .getByRole("button", { name: "Remove" }),
    );
    fireEvent.change(screen.getByLabelText("Add UNKNOWN topic"), {
      target: { value: "topic/C" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add topic" }));

    expect(screen.getByText("Kept").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Removed").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Added").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Suggestion precision").nextSibling).toHaveTextContent("0.50");
    expect(screen.getByText("Suggestion coverage proxy").nextSibling).toHaveTextContent("0.50");

    fireEvent.click(screen.getByRole("button", { name: "Apply review" }));

    await waitFor(() => expect(api.submitSemanticReview).toHaveBeenCalledWith({
      identity: {
        representation_name: "key_value",
        member_topics: ["topic/A", "topic/B"],
      },
      class_id: "temperature",
      semantic_class_name: "Temperature",
      kept_topics: ["topic/A"],
      removed_topics: ["topic/B"],
      added_topics: ["topic/C"],
    }));
    expect(await screen.findByText("No pending semantic candidates.")).toBeInTheDocument();
    expect(screen.getByText("Applied review for Temperature")).toBeInTheDocument();
    expect(screen.getByText("Constraints added: 1")).toBeInTheDocument();
  });

  it("keeps the candidate and displays an API failure", async () => {
    api.submitSemanticReview.mockRejectedValue(new Error("Review unavailable"));
    render(<SemanticReviewManager />);

    await screen.findByText("topic/A");
    fireEvent.change(screen.getByLabelText("Semantic class ID"), {
      target: { value: "temperature" },
    });
    fireEvent.change(screen.getByLabelText("Semantic class name"), {
      target: { value: "Temperature" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Review unavailable");
    expect(screen.getByText("topic/A")).toBeInTheDocument();
    expect(screen.getByText("topic/B")).toBeInTheDocument();
  });
});
