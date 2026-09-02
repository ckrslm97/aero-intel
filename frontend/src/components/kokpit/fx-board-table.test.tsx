import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FxForecastOut, KokpitFxBoardOut, KokpitFxPairOut } from "@/lib/types";

import { FxBoardTable, buildFxRows, nearestForecast } from "./fx-board-table";

// The forecast chart mounts ECharts and fetches a year of history; neither is
// what this file is about, and jsdom has no layout for the former.
vi.mock("./fx-forecast-chart-lazy", () => ({
  FxForecastChart: ({ pair }: { pair: string }) => <div data-testid="chart">{pair}</div>,
}));

const pair = (currency_pair: string, value: number, overrides: Partial<KokpitFxPairOut> = {}): KokpitFxPairOut => ({
  currency_pair,
  value,
  unit: currency_pair.split("/")[1],
  day_delta_pct: 0.1,
  week_delta_pct: 1.2,
  month_delta_pct: 3.4,
  sparkline: [value * 0.99, value],
  as_of: "2026-08-30T19:50:00Z",
  source: "Yahoo Finance",
  source_url: null,
  frequency_label: "~15 dakikada bir",
  ...overrides,
});

const board = (pairs: KokpitFxPairOut[]): KokpitFxBoardOut => ({
  pairs,
  peg: {
    currency_pair: "USD/SAR",
    value: 3.75,
    label: "Sabit · 3,75 (SAMA)",
    source: "Saudi Central Bank (SAMA)",
    source_url: "https://www.sama.gov.sa",
  },
});

const forecast = (overrides: Partial<FxForecastOut> = {}): FxForecastOut => ({
  institution: "Danske Bank",
  currency_pair: "USD/TRY",
  horizon_label: "+3m",
  horizon_months: 3,
  value: 52,
  publication_date: "2026-08-21",
  source_url: "https://danskebank.test",
  note_tr: null,
  target_date: "2026-11-21",
  target_date_basis_tr: "Yayın tarihi + 3 ay",
  ...overrides,
});

const NOW = new Date("2026-09-01T00:00:00Z").getTime();

const ALL_PAIRS = [
  pair("USD/TRY", 48.2505),
  pair("EUR/TRY", 56.41),
  pair("EUR/USD", 1.0842),
  pair("USD/JPY", 147.2),
  pair("USD/CNY", 7.12),
  pair("GBP/USD", 1.264),
  pair("EUR/GBP", 0.857),
];

describe("buildFxRows", () => {
  it("keeps the owner's pairs in the owner's order, the peg last in that block", () => {
    const rows = buildFxRows(board(ALL_PAIRS), [], NOW);
    expect(rows.filter((row) => row.group === "primary").map((row) => row.pair)).toEqual([
      "USD/TRY",
      "EUR/TRY",
      "EUR/USD",
      "USD/JPY",
      "USD/CNY",
      "USD/SAR",
    ]);
  });

  it("puts live pairs the owner did not list below the divider rather than dropping them", () => {
    // Retiring a live series to make a requested list fit would be destroying
    // information to satisfy a layout.
    const rows = buildFxRows(board(ALL_PAIRS), [], NOW);
    expect(rows.filter((row) => row.group === "extra").map((row) => row.pair)).toEqual([
      "GBP/USD",
      "EUR/GBP",
    ]);
  });

  it("renders no GBP/TRY row until the backend actually records the pair", () => {
    // This is what lets the frontend ship ahead of the ingest change: the row
    // appears the day the first reading lands, and until then the table does
    // not claim to be watching a pair it has no reading for.
    expect(buildFxRows(board(ALL_PAIRS), [], NOW).some((row) => row.pair === "GBP/TRY")).toBe(false);

    const withGbpTry = buildFxRows(board([...ALL_PAIRS, pair("GBP/TRY", 65.2307)]), [], NOW);
    expect(withGbpTry.map((row) => row.pair)).toContain("GBP/TRY");
    // And it lands in the owner's slot, fourth, not appended at the end.
    expect(withGbpTry.findIndex((row) => row.pair === "GBP/TRY")).toBe(3);
  });

  it("uses four decimals for a cross and two for a TRY or JPY rate", () => {
    const rows = new Map(buildFxRows(board(ALL_PAIRS), [], NOW).map((row) => [row.pair, row]));
    expect(rows.get("USD/TRY")?.value).toBe("48,25");
    expect(rows.get("USD/JPY")?.value).toBe("147,20");
    expect(rows.get("EUR/USD")?.value).toBe("1,0842");
  });

  it("gives the peg a badge and no deltas, trend or history page", () => {
    const peg = buildFxRows(board([]), [], NOW).find((row) => row.pair === "USD/SAR");
    // The badge is the backend's own string -- never one this component wrote.
    expect(peg?.pegLabel).toBe("Sabit · 3,75 (SAMA)");
    expect(peg?.dayPct).toBeNull();
    expect(peg?.weekPct).toBeNull();
    expect(peg?.series).toEqual([]);
    expect(peg?.metricKey).toBeNull();
  });

  it("keeps a row with no published forecast, dashed rather than hidden", () => {
    // The row's presence says "we watch this pair"; the dash says "nobody has
    // published a target". Hiding it would conceal both facts at once.
    const rows = buildFxRows(board(ALL_PAIRS), [forecast()], NOW);
    expect(rows.find((row) => row.pair === "USD/TRY")?.forecast).not.toBeNull();
    expect(rows.find((row) => row.pair === "USD/JPY")?.forecast).toBeNull();
  });
});

describe("nearestForecast", () => {
  it("prints the institution's own figure and its own horizon wording", () => {
    const cell = nearestForecast([forecast()], "USD/TRY", NOW);
    expect(cell?.label).toBe("52,00 · Danske Bank +3m");
  });

  it("picks the target date closest to now", () => {
    const cell = nearestForecast(
      [
        forecast({ institution: "Uzak", value: 66, target_date: "2027-12-31" }),
        forecast({ institution: "Yakın", value: 52, target_date: "2026-11-21" }),
      ],
      "USD/TRY",
      NOW,
    );
    expect(cell?.label).toContain("Yakın");
  });

  it("counts additional INSTITUTIONS on the same date, not additional rows", () => {
    // One bank publishing two horizons that land on one date is one opinion.
    const sameBankTwice = nearestForecast(
      [forecast(), forecast({ horizon_label: "3 ay sonu", value: 52.5 })],
      "USD/TRY",
      NOW,
    );
    expect(sameBankTwice?.label).not.toContain("kurum");

    const twoBanks = nearestForecast(
      [forecast(), forecast({ institution: "Garanti", value: 53 })],
      "USD/TRY",
      NOW,
    );
    expect(twoBanks?.label).toContain("+1 kurum");
  });

  it("never averages the institutions into one number", () => {
    const cell = nearestForecast(
      [forecast({ value: 50 }), forecast({ institution: "Garanti", value: 54 })],
      "USD/TRY",
      NOW,
    );
    // 52 would be the mean of 50 and 54 -- the arithmetic curated_seed.py
    // forbids. The cell prints one attributable figure and names the rest.
    expect(cell?.label.startsWith("50,00")).toBe(true);
    expect(cell?.title).toContain("Garanti");
  });

  it("ignores a forecast whose horizon could not be turned into a date", () => {
    // The server-side mapping declines to invent a date where the wording does
    // not support one; this column must not undo that.
    expect(nearestForecast([forecast({ target_date: null })], "USD/TRY", NOW)).toBeNull();
  });

  it("returns nothing for a pair nobody has published on", () => {
    expect(nearestForecast([forecast()], "USD/CNY", NOW)).toBeNull();
  });

  it("prefers a target date in the FUTURE over a nearer one already spent", () => {
    // "Closest in absolute time" quietly admits the past. From 2026-11-22 the
    // seeded Danske row (target 2026-11-21) sits a day behind while JPMorgan's
    // live 2026-12-31 target sits weeks ahead -- and the column, headed
    // "Tahmin", would have printed the spent one.
    const after = new Date("2026-11-22T00:00:00Z").getTime();
    const cell = nearestForecast(
      [
        forecast({ institution: "Danske Bank", value: 52, target_date: "2026-11-21" }),
        forecast({ institution: "JPMorgan", value: 55, target_date: "2026-12-31" }),
      ],
      "USD/TRY",
      after,
    );
    expect(cell?.label).toContain("JPMorgan");
    expect(cell?.expired).toBe(false);
  });

  it("labels the last published figure as spent when nothing ahead remains", () => {
    // Still shown -- "the last thing anyone published" is information -- but it
    // can never be read as a current expectation.
    const after = new Date("2027-06-01T00:00:00Z").getTime();
    const cell = nearestForecast([forecast()], "USD/TRY", after);
    expect(cell?.expired).toBe(true);
    expect(cell?.label).toContain("vadesi geçti");
    expect(cell?.title).toContain("ileri tarihli yayımlanmış tahmin kalmadı");
  });

  it("never prints the DERIVED target date, only the institution's own wording", () => {
    // `target_date` exists so the chart has an x coordinate; the institution
    // never published it (see FxForecastOut in lib/types.ts).
    const cell = nearestForecast([forecast()], "USD/TRY", NOW);
    expect(cell?.label).not.toContain("2026-11-21");
    expect(cell?.label).not.toContain("Kas");
  });
});

describe("FxBoardTable", () => {
  it("carries each row's own reading time in its tooltip", () => {
    // `asOfLabel` was computed for every row and then rendered nowhere, so the
    // nine rows shared one collective freshness stamp in the page header and a
    // pair whose cron run had failed looked exactly as current as one whose
    // had not.
    const rows = buildFxRows(board(ALL_PAIRS), [], NOW);
    expect(rows[0].title).toContain("19:50 UTC");
  });

  it("lets the keyboard change the charted pair", async () => {
    // The section byline promises every reader that clicking a row switches
    // the chart. The row used to be a bare <tr onClick>: not focusable, so for
    // a keyboard or screen-reader user no pair but the default was reachable.
    render(
      <FxBoardTable
        board={board(ALL_PAIRS)}
        forecasts={[
          forecast(),
          forecast({ currency_pair: "EUR/USD", value: 1.12, institution: "JPMorgan" }),
        ]}
      />,
    );
    expect(screen.getByTestId("chart")).toHaveTextContent("USD/TRY");

    const row = screen.getByText("EUR/USD").closest("tr")!;
    expect(row).toHaveAttribute("tabindex", "0");
    row.focus();
    await userEvent.keyboard("{Enter}");

    expect(screen.getByTestId("chart")).toHaveTextContent("EUR/USD");
    expect(row).toHaveAttribute("aria-pressed", "true");
  });
});
