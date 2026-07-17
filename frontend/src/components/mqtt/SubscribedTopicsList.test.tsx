import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../../services/topicApi", () => ({
  subscribeTopic: vi.fn(),
  unsubscribeTopic: vi.fn(),
  getSubscribedTopics: vi.fn(),
}));

import SubscribedTopicsList from "./SubscribedTopicsList";
import { useMqttStore } from "../../store/useMqttStore";
import * as topicApi from "../../services/topicApi";

const unsub = topicApi.unsubscribeTopic as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useMqttStore.setState({ topics: ["t/a"], messages: [] });
  vi.clearAllMocks();
});

describe("SubscribedTopicsList unsubscribe failure", () => {
  it("keeps the topic and shows an error when unsubscribe fails", async () => {
    unsub.mockRejectedValue(new Error("boom"));
    render(<SubscribedTopicsList />);

    fireEvent.click(screen.getByTitle("Unsubscribe"));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // topic still present
    expect(screen.getByText("t/a")).toBeInTheDocument();
    expect(useMqttStore.getState().topics).toContain("t/a");
  });

  it("removes the topic and clears error on a successful retry", async () => {
    unsub.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({});
    render(<SubscribedTopicsList />);

    fireEvent.click(screen.getByTitle("Unsubscribe"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() =>
      expect(screen.queryByText("t/a")).not.toBeInTheDocument()
    );
    expect(useMqttStore.getState().topics).not.toContain("t/a");
  });
});
