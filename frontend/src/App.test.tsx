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
vi.mock("./components/semantic/SemanticOperationsPanel", () => ({
  default: () => <section data-testid="semantic-operations" />,
}));
vi.mock("./components/semantic/SemanticReviewManager", () => ({
  default: () => <section data-testid="semantic-review" />,
}));

const managerTestIds = [
  "mqtt-manager",
  "duplicate-manager",
  "class-builder",
  "saved-classes",
  "group-manager",
  "semantic-operations",
  "semantic-review",
];

it("preserves every dashboard manager and mounts operations before review", () => {
  render(<App />);

  for (const testId of managerTestIds) {
    expect(screen.getByTestId(testId)).toBeInTheDocument();
  }
  const operations = screen.getByTestId("semantic-operations");
  const review = screen.getByTestId("semantic-review");
  expect(
    operations.compareDocumentPosition(review) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
