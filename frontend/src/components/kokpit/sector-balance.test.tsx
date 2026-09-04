import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AnnualPoint, AnnualSeries, AnnualSeriesBoardOut } from "@/lib/types";

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

const marginOf = (annual: AnnualSeriesBoardOut | null) => buildBalanceRows(annual)[0];

describe("buildBalanceRows", () => {
  it("produces exactly one derived row, and it is not a composite score", () => {
    // THE POINT OF THIS ROUND. The block used to carry four rows, three of
    // which were arithmetic on two numbers already printed within two hundred
    // pixels of it: demand minus capacity IS the load factor's direction
    // (Market Pulse cell 3), revenue minus traffic IS yield's direction (the
    // GETİRİ card immediately to the left), and the fuel percentile was fuel's
    // second appearance on a page instructed to show it once.
    const rows = buildBalanceRows(null);
    expect(rows.map((row) => row.key)).toEqual(["unit_margin"]);
    expect(rows.every((row) => !/skor|score/i.test(row.label))).toBe(true);
  });

  it("compares the margin only on years BOTH series have, and names them", () => {
    // CASK is missing 2025 upstream. The comparison is therefore 2024 vs 2026,
    // and the chip says 2024 rather than implying consecutive years.
    const margin = marginOf(
      board([
        series("rask", [point(2024, 10.2), point(2025, 10.5), point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 9.55), point(2026, 9.66)], "¢/ASK"),
      ]),
    );
    expect(margin.value).toBe("0,42");
    expect(margin.chip).toBe("IATA · yıllık · 2024: 0,65");
    // Narrowing from 0,65 to 0,42 is a fall.
    expect(margin.pct).toBeLessThan(0);
  });

  it("declines the comparison when the two series share no year", () => {
    const margin = marginOf(
      board([
        series("rask", [point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 9.55)], "¢/ASK"),
      ]),
    );
    expect(margin.value).toBe("—");
    expect(margin.title).toBe("RASK ve CASK'ın ortak bir yılı yok");
  });

  it("prints the level but no arrow when only one shared year exists", () => {
    const margin = marginOf(
      board([
        series("rask", [point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2026, 9.66)], "¢/ASK"),
      ]),
    );
    expect(margin.value).toBe("0,42");
    expect(margin.pct).toBeNull();
    expect(margin.title).toBe("Karşılaştırılacak ikinci ortak yıl yok");
  });

  it("gives the margin its unit", () => {
    // "0,42" beside five other cells is unreadable: percent, ratio or price?
    // It is cents per ASK, which is what both inputs are measured in.
    expect(
      marginOf(
        board([
          series("rask", [point(2024, 9.3), point(2026, 10.08)], "¢/ASK"),
          series("cask", [point(2024, 8.67), point(2026, 9.66)], "¢/ASK"),
        ]),
      ).unit,
    ).toBe("¢/ASK");
  });
});

describe("SectorBalance", () => {
  it("renders no percent sign: the margin is measured in cents per ASK", () => {
    // REGRESSION LOCK. Running the direction through Delta's default form
    // printed "-%0,2" beside "0,42" -- a 0,23¢ move relabelled as a percentage.
    const { container } = render(
      <SectorBalance
        annual={board([
          series("rask", [point(2024, 9.3), point(2026, 10.08)], "¢/ASK"),
          series("cask", [point(2024, 8.65), point(2026, 9.66)], "¢/ASK"),
        ])}
      />,
    );
    expect(container.textContent).not.toContain("%");
    expect(screen.getByText("0,42")).toBeInTheDocument();
    expect(screen.getByText("IATA · yıllık · 2024: 0,65")).toBeInTheDocument();
  });

  it("still renders the cell, with its reason, when the series are missing", () => {
    render(<SectorBalance annual={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Birim marj (RASK−CASK)")).toBeInTheDocument();
  });
});

describe("buildBalanceRows: neden boş olduğunu doğru söyler", () => {
  it("does not blame the two series for having no common year when neither was read", () => {
    // THE WRONG REASON. One sentence -- "RASK ve CASK'ın ortak bir yılı yok" --
    // used to be printed over every dash, including the case where the annual
    // board never answered. It is specific enough that a reader believes it,
    // and it is a finding about the data invented out of an outage.
    const margin = buildBalanceRows(null, true)[0];
    expect(margin.value).toBe("—");
    expect(margin.title).toBe("IATA yıllık serisi okunamadı; birim marj hesaplanamadı");
  });

  it("names the series that is actually absent", () => {
    const onlyRask = buildBalanceRows(
      board([series("rask", [point(2026, 10.08)], "¢/ASK")]),
    )[0];
    expect(onlyRask.title).toBe("CASK serisi bu yanıtta yok");

    const neither = buildBalanceRows(board([]))[0];
    expect(neither.title).toBe("RASK ve CASK serileri bu yanıtta yok");
  });

  it("still gives the real reason when both series are present and share no year", () => {
    // The negative half: the original sentence survives for the case it was
    // written about, and only for that case.
    const margin = buildBalanceRows(
      board([
        series("rask", [point(2026, 10.08)], "¢/ASK"),
        series("cask", [point(2024, 9.55)], "¢/ASK"),
      ]),
    )[0];
    expect(margin.title).toBe("RASK ve CASK'ın ortak bir yılı yok");
  });
});
