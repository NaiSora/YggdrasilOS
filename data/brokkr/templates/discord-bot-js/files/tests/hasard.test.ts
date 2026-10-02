import { describe, expect, it } from "vitest";
import { lancer } from "../src/outils/hasard.js";

describe("lancer", () => {
  it("reste entre 1 et le nombre de faces", () => {
    expect(lancer(6, () => 0)).toBe(1);
    expect(lancer(6, () => 0.9999)).toBe(6);
    expect(lancer(20, () => 0.5)).toBe(11);
  });
  it("refuse un dé impossible", () => {
    expect(() => lancer(1)).toThrow(RangeError);
  });
});
