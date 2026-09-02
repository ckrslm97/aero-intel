import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AnnualPoint, AnnualSeries, AnnualSeriesBoardOut, EnergyBoardOut } from "@/lib/types";

import { SectorBalance, buildBalanceRows } from "./sector-balance";

const point = (year: number, value: number): AnnualPoint => ({ year, value, kind: "actual" });

const series = (metric_key: string, points: AnnualPoint[], unit = "x"): AnnualSeries => ({
  metric_key,
  label_tr: metric_key,
  unit,
  up_is_good: true,
  points,
});

const board = (rows: AnnualSeries[]): AnnualSeriesBoardOut => ({
  series: rows,
  source: "IATA",
  source_url: "https://iata.org",
  scope_tr: "sektör geneli · yıllık",
});

const energy = (percentile: number | null): EnergyBoardOut => ({
  metrics: [
    {
      metric_key: "oil_price",
      label_tr: "Brent",
      unit: "$/bbl",
      value: 71.2,
      as_of: "2026-08-30T20:00:00Z",
      day_change_pct: 1,
      week_change_pct: 1,
      month_change_pct: 1,
      ytd_change_pct: 1,
      percentile_1y: percentile,
      volatility_30d_pct: 20,
      sparkline: [70, 71],
      source: "Yahoo",
      source_url: "https://finance.yahoo.com",
      href: "/kpi/oil_price",
      is_estimate: false,
      note_tr: null,
    },
  ],
  volatility_method_tr: "…",
  percentile_method_tr: "…",
});

const rowsOf = (annual: AnnualSeriesBoardOut | null, en: EnergyBoardOut | null) =>
  new Map(buildBalanceRows(annual, en).map((row) => [row.key, row]));

describe("buildBalanceRows", () => {
  it("always produces the same four drivers and no composite score", () => {
    const rows = buildBalanceRows(null, null);
    expect(rows.map((row) => row.key)).toEqual([
      "demand_capacity",
      "revenue_traffic",
      "unit_margin",
      "fuel_position",
    ]);
    // Nothing here is a 0-100 blend of the four.
    expect(rows.every((row) => !/skor|score/i.test(row.label))).toBe(true);
  });

  it("states the demand-capacity scissor in percentage POINTS", () => {
    // RPK +5%, ASK +2% -> a THREE POINT gap, not "+%3" of anything.
    const rows = rowsOf(
      board([
        series("rpk", [point(2025, 100), point(2026, 105)]),
        series("ask", [point(2025, 100), point(2026, 102)]),
      ]),
      null,
    );
    expect(rows.get("demand_capacity")?.value).toBe("+3,0pp");
    expect(rows.get("demand_capacity")?.chip).toBe("IATA · yıllık · 25→26");
  });

  it("states the revenue-traffic scissor the same way", () => {
    const rows = rowsOf(
      board([
        series("total_aviation_revenue_ytd", [point(2025, 100), point(2026, 110)]),
        series("rpk", [point(2025, 100), point(2026, 102)]),
      ]),
      null,
    );
    expect(rows.get("revenue_traffic")?.value).toBe("+8,0pp");
  });

  it("refuses a scissor when either side has fewer than two years", () => {
    const rows = rowsOf(
      board([series("rpk", [point(2026, 105)]), series("ask", [point(2025, 100), point(2026, 102)])]),
      null,
    );
    expect(rows.get("demand_capacity")?.value).toBe("—");
    expect(rows.get("demand_capacity")?.title).toBe("yeterli yıllık nokta yok");
  });

  it("compares unit margin only on years BOTH series have, and names them", () => {
    // CASK is missing 2025 upstream. The comparison is therefore 2024 vs 2026,
    // and the chip says 2024 rather than implying consecutive years.
    const rows = rowsOf(
      board([
        series("rask", [point(2024, 10.2), point(2025, 10.5), point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 9.55), point(2026, 9.66)], "¢/ASK"),
      ]),
      null,
    );
    const margin = rows.get("unit_margin");
    expect(margin?.value).toBe("0,42");
    expect(margin?.chip).toBe("IATA · yıllık · 2024: 0,65");
    // Narrowing from 0,65 to 0,42 is a fall.
    expect(margin?.pct).toBeLessThan(0);
  });

  it("declines a margin comparison when the two series share no year", () => {
    const rows = rowsOf(
      board([
        series("rask", [point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 9.55)], "¢/ASK"),
      ]),
      null,
    );
    expect(rows.get("unit_margin")?.value).toBe("—");
  });

  it("reads the fuel position off the live percentile and labels its own clock", () => {
    const rows = rowsOf(null, energy(78.5));
    expect(rows.get("fuel_position")?.value).toBe("%79 dilim");
    // The one row in the block that is NOT annual says so.
    expect(rows.get("fuel_position")?.chip).toBe("Yahoo · canlı · 1 yıl");
  });

  it("prints a dash rather than a zero percentile when there is no year of closes", () => {
    expect(rowsOf(null, energy(null)).get("fuel_position")?.value).toBe("—");
  });

  it("never renders a percent sign: no row in this block is measured in percent", () => {
    // REGRESSION LOCK. Every row here is a percentage-POINT gap, a
    // cents-per-ASK margin or a percentile band. Rendering the direction
    // through Delta's default form printed "+%0,6" beside "+0,6pp" (one
    // quantity twice, once in the wrong unit) and "-%0,2" beside "0,42" (a
    // 0,23¢ move relabelled as a percentage). Only the percentile's own
    // "%79 dilim" is allowed to carry a %.
    const { container } = render(
      <SectorBalance
        annual={board([
          series("rpk", [point(2025, 100), point(2026, 102.1)]),
          series("ask", [point(2025, 100), point(2026, 101.5)]),
          series("rask", [point(2024, 9.3), point(2026, 10.08)], "¢/ASK"),
          series("cask", [point(2024, 8.65), point(2026, 9.66)], "¢/ASK"),
        ])}
        energy={energy(78.5)}
      />,
    );
    const percents = container.textContent?.match(/%/g) ?? [];
    expect(percents).toHaveLength(1);
    expect(container.textContent).toContain("%79 dilim");
  });

  it("computes a scissor over the years BOTH series carry, and says which", () => {
    // The trap: each side used to take its OWN last two points. With `ask`
    // missing 2025 that subtracts a two-year growth rate from a one-year one
    // and labels the result "25→26" off the left series alone -- a number
    // belonging to no window, wearing a window's name.
    const rows = rowsOf(
      board([
        series("rpk", [point(2024, 100), point(2025, 110), point(2026, 121)]),
        series("ask", [point(2024, 100), point(2026, 121)]),
      ]),
      null,
    );
    const gap = rows.get("demand_capacity")!;
    // Shared years are 2024 and 2026: rpk +21%, ask +21% -> no gap at all.
    expect(gap.value).toBe("0,0pp");
    expect(gap.chip).toBe("IATA · yıllık · 24→26");
  });

  it("refuses the scissor outright when the two series share no two years", () => {
    const rows = rowsOf(
      board([
        series("rpk", [point(2025, 100), point(2026, 110)]),
        series("ask", [point(2019, 90), point(2020, 95)]),
      ]),
      null,
    );
    const gap = rows.get("demand_capacity")!;
    expect(gap.value).toBe("—");
    expect(gap.title).toBe("İki serinin ortak iki yılı yok");
  });

  it("gives the unit margin its unit", () => {
    // "0,42" next to "+0,6pp" and "%78 dilim" is unreadable: percent, ratio or
    // price? It is cents per ASK, which is what both inputs are measured in.
    const rows = rowsOf(
      board([
        series("rask", [point(2024, 9.3), point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 8.67), point(2026, 9.66)], "¢/ASK"),
      ]),
      null,
    );
    const margin = rows.get("unit_margin")!;
    expect(margin.value).toBe("0,42");
    expect(margin.unit).toBe("¢/ASK");
  });
});
