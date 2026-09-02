import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Delta } from "./delta";

/** The class list of the element that actually carries the delta's styling. */
function classesOf(text: string | RegExp): string {
  return screen.getByText(text).closest("span")?.className ?? "";
}

describe("Delta", () => {
  it("never colours a neutral-tone move, in either direction", () => {
    // THE REGRESSION LOCK. The surface this replaces wrote `tone: "neutral"`
    // on the FX number and then drew a green trend under it, so the text and
    // the graphic disagreed about whether a currency move is good news.
    const { rerender } = render(<Delta pct={1.2} tone="neutral" />);
    expect(classesOf("+%1,2")).not.toMatch(/text-good|text-critical|bg-good|bg-critical/);

    rerender(<Delta pct={-1.2} tone="neutral" />);
    expect(classesOf("-%1,2")).not.toMatch(/text-good|text-critical|bg-good|bg-critical/);
  });

  it("reads a rise as good for a signed metric and as bad for a cost base", () => {
    const { rerender } = render(<Delta pct={2.4} tone="signed" />);
    expect(classesOf("+%2,4")).toContain("text-good");

    rerender(<Delta pct={2.4} tone="costly" />);
    expect(classesOf("+%2,4")).toContain("text-critical");
  });

  it("reads a fall in a cost base as good -- CASK coming down is not bad news", () => {
    render(<Delta pct={-3.1} tone="costly" />);
    expect(classesOf("-%3,1")).toContain("text-good");
  });

  it("treats a flat reading as a judgement about nothing", () => {
    render(<Delta pct={0} tone="signed" />);
    expect(classesOf("%0,0")).not.toMatch(/text-good|text-critical/);
  });

  it("prints an em dash with a stated reason rather than a fabricated 0%", () => {
    render(<Delta pct={null} scope="1g" />);
    const empty = screen.getByText("1g —");
    expect(empty).toHaveAttribute("title", "Yeterli geçmiş henüz yok");
    expect(screen.queryByText(/%0,0/)).not.toBeInTheDocument();
  });

  it("boxes the value only in pill form", () => {
    const { rerender } = render(<Delta pct={5} tone="signed" form="bare" />);
    expect(classesOf("+%5,0")).not.toContain("rounded-full");

    rerender(<Delta pct={5} tone="signed" form="pill" />);
    expect(classesOf("+%5,0")).toContain("rounded-full");
  });

  it("lets the caller state a percentage-POINT change in its own unit", () => {
    // A load factor moving 84,0 -> 84,5 has risen 0,5 POINTS, not 0,5 percent.
    render(<Delta pct={0.5} tone="signed" valueLabel="+0,5pp" scope="25→26T" />);
    expect(screen.getByText("+0,5pp")).toBeInTheDocument();
    expect(screen.queryByText(/%0,5/)).not.toBeInTheDocument();
  });

  it("prints no number at all in arrow form", () => {
    // The arrow form exists for rows whose number is NOT a percentage -- a
    // percentage-point gap, a cents-per-ASK margin. Emitting "%" there would
    // relabel the caller's quantity as something it is not, which is exactly
    // the bug this form was introduced to fix.
    const { container } = render(<Delta pct={-0.23} tone="signed" form="arrow" />);
    expect(container.textContent).not.toMatch(/%/);
    expect(container.textContent).not.toMatch(/0,2/);
    // The direction still reaches a screen reader.
    expect(screen.getByText("geriledi")).toHaveClass("sr-only");
  });

  it("still colours by tone in arrow form", () => {
    const { container } = render(<Delta pct={-1} tone="signed" form="arrow" />);
    expect(container.firstElementChild?.className).toContain("text-critical");
  });
});
