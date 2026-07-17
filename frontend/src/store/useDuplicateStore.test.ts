import { describe, it, expect, beforeEach } from "vitest";
import { useDuplicateStore } from "./useDuplicateStore";
import { DupeStatus } from "../types/api_models";

const dupe = (topics: string[]) => ({
  topics,
  score: 0.95,
  status: DupeStatus.PENDING,
});

beforeEach(() => {
  useDuplicateStore.setState({ duplicates: [], selectedPair: null, series: [] });
});

describe("useDuplicateStore duplicate handling", () => {
  it("adds a duplicate and is idempotent regardless of topic order", () => {
    const { addDuplicate } = useDuplicateStore.getState();
    addDuplicate(dupe(["a", "b"]));
    addDuplicate(dupe(["b", "a"])); // same pair, reversed
    expect(useDuplicateStore.getState().duplicates).toHaveLength(1);
  });

  it("never mutates the source topic arrays", () => {
    const first = ["b", "a"];
    useDuplicateStore.getState().addDuplicate(dupe(first));
    const compare = ["d", "c"];
    useDuplicateStore.getState().addDuplicate(dupe(compare));

    // Comparison must not have sorted the stored or incoming arrays in place.
    expect(first).toEqual(["b", "a"]);
    expect(compare).toEqual(["d", "c"]);
    expect(useDuplicateStore.getState().duplicates[0].topics).toEqual(["b", "a"]);
  });

  it("removes by pair key without mutating state arrays", () => {
    const store = useDuplicateStore.getState();
    store.addDuplicate(dupe(["x", "y"]));
    store.addDuplicate(dupe(["m", "n"]));
    store.removeDuplicate(["y", "x"]); // reversed order still matches
    const remaining = useDuplicateStore.getState().duplicates;
    expect(remaining).toHaveLength(1);
    expect(remaining[0].topics).toEqual(["m", "n"]);
  });
});
