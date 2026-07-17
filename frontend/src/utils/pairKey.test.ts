import { describe, it, expect } from "vitest";
import { pairKey, samePair } from "./pairKey";

describe("pairKey", () => {
  it("is order-independent", () => {
    expect(pairKey(["a", "b"])).toBe(pairKey(["b", "a"]));
  });

  it("distinguishes different pairs", () => {
    expect(pairKey(["a", "b"])).not.toBe(pairKey(["a", "c"]));
  });

  it("does not mutate the input array", () => {
    const input = ["b", "a"];
    const snapshot = [...input];
    pairKey(input);
    expect(input).toEqual(snapshot); // still ["b","a"], unsorted
  });

  it("samePair matches regardless of order and does not mutate", () => {
    const a = ["z", "y"];
    const b = ["y", "z"];
    expect(samePair(a, b)).toBe(true);
    expect(a).toEqual(["z", "y"]);
    expect(b).toEqual(["y", "z"]);
  });
});
