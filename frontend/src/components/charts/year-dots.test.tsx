import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AnnualPoint } from "@/lib/types";

import { buildSlots, YearDots } from "./year-dots";

const point = (year: number, value: number, kind: AnnualPoint["kind"] = "actual"): AnnualPoint => ({
  year,
  value,
  kind,
});

describe("buildSlots", () => {
  it("returns the last four YEARS, not the last four points", () => {
    const slots = buildSlots([point(2019, 1), point(2023, 2), point(2024, 3), point(2026, 4)]);
    expect(slots.map((slot) => slot.year)).toEqual([2023, 2024, 2025, 2026]);
  });

  it("leaves a missing year empty instead of closing the gap", () => {
    // `cask` genuinely has no 2025 row. Sliding 2022 into the gap would draw
    // four evenly spaced years that are not four consecutive years.
    const slots = buildSlots([point(2022, 1), point(2023, 2), point(2024, 3), point(2026, 4)]);
    expect(slots.map((slot) => slot.year)).toEqual([2023, 2024, 2025, 2026]);
    expect(slots[2].point).toBeNull();
    expect(slots[3].point?.value).toBe(4);
  });

  it("has nothing to draw for an empty series", () => {
    expect(buildSlots([])).toEqual([]);
  });
});

describe("YearDots", () => {
  it("fills a measured year and hollows an estimate or a forecast", () => {
    const { container } = render(
      <YearDots
        points={[
          point(2023, 10),
          point(2024, 11),
          point(2025, 12, "estimate"),
          point(2026, 13, "forecast"),
        ]}
      />,
    );
    const dots = [...container.querySelectorAll("[title]")].map((n) => n.getAttribute("class") ?? "");
    expect(dots[0]).toContain("bg-foreground/70");
    expect(dots[2]).toContain("bg-transparent");
    expect(dots[3]).toContain("bg-transparent");
  });

  it("dashes the connector into a year that was not measured", () => {
    const { container } = render(
      <YearDots
        points={[point(2023, 10), point(2024, 11), point(2025, 12), point(2026, 13, "forecast")]}
      />,
    );
    const lines = [...container.querySelectorAll("line")];
    expect(lines).toHaveLength(3);
    expect(lines[0].getAttribute("stroke-dasharray")).toBeNull();
    expect(lines[2].getAttribute("stroke-dasharray")).toBe("2 2");
  });

  it("refuses to interpolate across a missing year", () => {
    // Two segments, not three: nothing is drawn into or out of the empty slot.
    const { container } = render(
      <YearDots points={[point(2022, 9), point(2023, 10), point(2024, 11), point(2026, 13)]} />,
    );
    expect(container.querySelectorAll("line")).toHaveLength(1);
  });

  it("says out loud which year is missing", () => {
    const { container } = render(
      <YearDots points={[point(2023, 10), point(2024, 11), point(2026, 13)]} />,
    );
    expect(container.querySelector('[title="2025 verisi yok"]')).not.toBeNull();
  });

  it("always prints the year labels, flagging estimates and forecasts", () => {
    const { container } = render(
      <YearDots
        points={[point(2023, 10), point(2024, 11), point(2025, 12, "estimate"), point(2026, 13, "forecast")]}
      />,
    );
    expect(container.textContent).toContain("25G");
    expect(container.textContent).toContain("26T");
  });

  it("carries no glow -- glow means live measurement on this page", () => {
    const { container } = render(<YearDots points={[point(2025, 1), point(2026, 2, "forecast")]} />);
    expect(container.innerHTML).not.toMatch(/glow/);
  });
});
