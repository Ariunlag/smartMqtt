import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./hooks/useBootstrap", () => ({
  useBootstrap: () => ({ ready: true, error: null }),
}));
vi.mock("./hooks/useWebSocket", () => ({ useWebSocket: vi.fn() }));
vi.mock("./store/useConnectionStore", () => ({
  useConnectionStore: (selector: (state: { status: string }) => unknown) =>
    selector({ status: "connected" }),
}));

vi.mock("./components/mqtt/MqttManager", () => ({
  default: () => <section data-testid="mqtt-manager" />,
}));
vi.mock("./components/duplicates/DuplicateManager", () => ({
  default: () => <section data-testid="duplicate-manager" />,
}));
vi.mock("./components/classes/ClassBuilder", () => ({
  default: () => <section data-testid="class-builder" />,
}));
vi.mock("./components/savedClasses/SavedClasses", () => ({
  default: () => <section data-testid="saved-classes" />,
}));
vi.mock("./components/groups/GroupManager", () => ({
  default: () => <section data-testid="group-manager" />,
}));
vi.mock("./components/recommendations/RecommendationsManager", () => ({
  default: () => <section data-testid="recommendations-manager" />,
}));

const managerTestIds = [
  "mqtt-manager",
  "duplicate-manager",
  "class-builder",
  "saved-classes",
  "group-manager",
  "recommendations-manager",
];

it("preserves every dashboard manager and adds recommendations", () => {
  render(<App />);

  for (const testId of managerTestIds) {
    expect(screen.getByTestId(testId)).toBeInTheDocument();
  }
  expect(screen.getByRole("tab", { name: /Recommendations/i })).toBeInTheDocument();
});
