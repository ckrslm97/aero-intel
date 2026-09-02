import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MicroTrend } from "./micro-trend";

function svgOf(container: HTMLElement) {
  return container.querySelector("svg");
}

describe("MicroTrend", () => {
  it("draws nothing at all from fewer than two points", () => {
    // The caller prints "yeterli geçmiş yok" into the same 20px slot. A trend
    // through one observation is decoration, not data.
    expect(svgOf(render(<MicroTrend data={[]} />).container)).toBeNull();
    expect(svgOf(render(<MicroTrend data={[41.7]} />).container)).toBeNull();
  });

  it("keeps the line neutral whichever way the series went", () => {
    for (const data of [[1, 2, 3], [3, 2, 1]]) {
      const { container } = render(<MicroTrend data={data} tone="neutral" />);
      const line = container.querySelector("polyline")!;
      expect(line.getAttribute("class")).toContain("text-muted-foreground");
      expect(line.getAttribute("class")).not.toMatch(/text-good|text-critical/);
    }
  });

  it("leaves the line neutral even for a cost base -- only the endpoint may redden", () => {
    const { container } = render(<MicroTrend data={[70, 71, 74]} tone="costly" />);
    expect(container.querySelector("polyline")!.getAttribute("class")).not.toMatch(
      /text-good|text-critical/,
    );
    expect(container.querySelector("path")!.getAttribute("class")).toContain("text-critical");
  });

  it("reads a falling cost base as good news", () => {
    const { container } = render(<MicroTrend data={[74, 71, 70]} tone="costly" />);
    expect(container.querySelector("path")!.getAttribute("class")).toContain("text-good");
  });

  it("gives a neutral endpoint no status colour", () => {
    const { container } = render(<MicroTrend data={[1, 2, 3]} tone="neutral" />);
    expect(container.querySelector("path")!.getAttribute("class")).not.toMatch(
      /text-good|text-critical/,
    );
  });

  it("still renders a series that has not moved", () => {
    // Equal min and max collapse the range to zero; without the pad every y is
    // NaN and the polyline silently disappears.
    const { container } = render(<MicroTrend data={[3.75, 3.75, 3.75]} />);
    expect(container.querySelector("polyline")!.getAttribute("points")).not.toMatch(/NaN/);
  });

  it("carries no area fill", () => {
    const { container } = render(<MicroTrend data={[1, 2, 3]} />);
    expect(container.querySelector("polyline")!.getAttribute("fill")).toBe("none");
  });
});
