import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import MqttMessageLog from "./MqttMessageLog";
import { useMqttStore } from "../../store/useMqttStore";
import type { MqttMessage } from "../../types/mqtt";

const msg = (over: Partial<MqttMessage>): MqttMessage => ({
  topic: "t/a",
  tags: {},
  fields: { value: 1 },
  timestamp: "2024-01-01T00:00:00.000Z",
  ...over,
});

beforeEach(() => {
  useMqttStore.setState({ topics: [], messages: [] });
});

describe("MqttMessageLog", () => {
  it("renders one row per message even with identical topic+timestamp", () => {
    // distinct event ids, same topic and timestamp
    useMqttStore.getState().addMessages([
      msg({ event_id: "e1", fields: { value: 1 } }),
      msg({ event_id: "e2", fields: { value: 2 } }),
    ]);
    render(<MqttMessageLog />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("is stable across repeated renders (no duplicated rows)", () => {
    useMqttStore.getState().addMessage(msg({ event_id: "e1" }));
    const { rerender } = render(<MqttMessageLog />);
    rerender(<MqttMessageLog />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});
