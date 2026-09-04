import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { riskCountry, riskItem } from "@/lib/__fixtures__/risk";
import { chartTheme, severityChartColor } from "@/lib/chart-theme";
import { SEVERITY_LADDER, type Severity } from "@/lib/severity";

import { RiskMap } from "./risk-map";

/** The ECharts option the map hands the renderer, captured. The canvas itself
 * is checked in a browser; what has to be pinned here is the COLOUR the map
 * decides on, because that is the thing that silently drifted away from the
 * rest of the page. */
const options = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }));
vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: Record<string, unknown> }) => {
    options.last = option;
    return <div data-testid="echarts" />;
  },
}));
vi.mock("@/lib/echarts-world", () => ({ ensureWorldMap: () => Promise.resolve() }));

interface Series {
  data?: { itemStyle?: { color?: string }; meta?: { severity?: string } }[];
}

function markerColors() {
  const series = (options.last?.series ?? []) as Series[];
  const found = new Map<string, string>();
  for (const s of series) {
    for (const point of s.data ?? []) {
      if (point.meta?.severity && point.itemStyle?.color) {
        found.set(point.meta.severity, point.itemStyle.color);
      }
    }
  }
  return found;
}

/** Athens, Rome and Madrid: three placed cities so each rung gets a marker of
 * its own rather than three markers sharing a coordinate. */
const COUNTRIES = [
  riskCountry("Greece", [
    riskItem({ id: "r-high", severity: "high", country: "Greece", city: "Athens" }),
  ]),
  riskCountry("Italy", [
    riskItem({ id: "r-medium", severity: "medium", country: "Italy", city: "Rome" }),
  ]),
  riskCountry("Spain", [
    riskItem({ id: "r-low", severity: "low", country: "Spain", city: "Madrid" }),
  ]),
];

async function renderMap() {
  options.last = null;
  render(
    <RiskMap
      countries={COUNTRIES}
      selectedCountry={null}
      onSelectCountry={() => {}}
      onOpenItem={() => {}}
    />,
  );
  await waitFor(() => expect(screen.getByTestId("echarts")).toBeInTheDocument());
}

/** THE BUG. This map kept its own severity->colour table, and the ladder moved
 * `high` from --critical to --warning without it. Both surfaces are on ONE
 * screen -- the map, and the SeverityPill in the country list beside it -- so
 * amber meant "Yüksek" in one place and "Orta" in the other, which is the
 * confusion lib/severity.ts exists to end. The legend had drifted further
 * still: it printed "Orta" in --warning while the marker for that same rung
 * was drawn in --signal, so it disagreed with its own map. */
describe("risk map severity language", () => {
  it("paints its markers in the ladder's hues", async () => {
    await renderMap();
    const colors = markerColors();
    const theme = chartTheme(false);

    for (const rung of ["high", "medium", "low"] as const) {
      expect(colors.get(rung)).toBe(severityChartColor(theme, rung));
    }
    // The negative half, stated as the regression itself: "Yüksek" is not
    // drawn in the top rung's red, and no two rungs share a hex.
    expect(colors.get("high")).not.toBe(theme.critical);
    expect(new Set(colors.values()).size).toBe(3);
  });

  it("draws a legend that agrees with its own markers", async () => {
    await renderMap();

    for (const rung of ["high", "medium", "low"] as Severity[]) {
      const meta = SEVERITY_LADDER[rung];
      // The word comes off the ladder, so the legend cannot invent a fourth
      // vocabulary for the three rungs this page carries.
      const entry = screen.getByText(meta.label);
      const dot = entry.querySelector("span[aria-hidden]");
      expect(dot).not.toBeNull();
      expect(dot).toHaveClass(...meta.dot.split(" "));
    }

    // And the specific thing that was wrong: "Yüksek" was drawn as a critical
    // dot, and "Orta" as the warning dot that "Yüksek" now owns -- so the
    // legend disagreed both with the ladder and with its own markers.
    expect(screen.getByText("Yüksek").innerHTML).not.toContain("bg-critical");
    expect(screen.getByText("Orta").innerHTML).not.toContain("bg-warning");
  });
});
