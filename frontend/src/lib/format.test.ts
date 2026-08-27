import { describe, expect, it } from "vitest";

import { formatCompactNumber, formatDelta } from "./format";

describe("formatDelta", () => {
  it("signs a positive change with a leading +", () => {
    expect(formatDelta(4.2)).toBe("+4.2%");
  });

  it("does not double-sign a negative change", () => {
    expect(formatDelta(-3.5)).toBe("-3.5%");
  });

  it("does not sign a zero change", () => {
    expect(formatDelta(0)).toBe("0.0%");
  });

  it("rounds to one decimal place", () => {
    expect(formatDelta(1.249)).toBe("+1.2%");
    expect(formatDelta(1.25)).toBe("+1.3%");
  });
});

describe("formatCompactNumber", () => {
  it("formats large numbers in Turkish compact notation", () => {
    // Intl's tr-TR compact formatter separates the number and the unit with
    // a non-breaking space (U+00A0) -- built via an escape sequence rather
    // than typed literally, since it is visually indistinguishable from a
    // normal space in an editor.
    expect(formatCompactNumber(1_500_000)).toBe("1,5 Mn");
  });

  it("leaves small numbers unabbreviated", () => {
    expect(formatCompactNumber(42)).toBe("42");
  });
});
