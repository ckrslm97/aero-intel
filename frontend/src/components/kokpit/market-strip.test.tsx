import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EnergyBoardOut, EnergyMetricOut, KokpitFxBoardOut, KokpitFxPairOut } from "@/lib/types";

import { buildCells, MarketStrip, utcTimeLabel } from "./market-strip";

const pair = (overrides: Partial<KokpitFxPairOut> = {}): KokpitFxPairOut => ({
  currency_pair: "USD/TRY",
  value: 41.7231,
  unit: "TRY",
  day_delta_pct: 0.42,
  week_delta_pct: -1.1,
  month_delta_pct: 3.4,
  sparkline: [41.1, 41.4, 41.7],
  as_of: "2026-08-30T11:45:00Z",
  source: "Yahoo Finance (TRY=X)",
  source_url: "https://finance.yahoo.com/quote/TRY=X",
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

const metric = (overrides: Partial<EnergyMetricOut> = {}): EnergyMetricOut => ({
  metric_key: "oil_price",
  label_tr: "Brent",
  unit: "$/bbl",
  value: 88.16,
  as_of: "2026-08-30T20:00:00Z",
  day_change_pct: 1.2,
  week_change_pct: -0.8,
  month_change_pct: 4.1,
  ytd_change_pct: 12.4,
  percentile_1y: 78.5,
  volatility_30d_pct: 24.3,
  sparkline: [80, 84, 88],
  source: "Yahoo Finance (BZ=F)",
  source_url: "https://finance.yahoo.com/quote/BZ=F",
  href: "/kpi/oil_price",
  is_estimate: false,
  note_tr: null,
  ...overrides,
});

const energy = (metrics: EnergyMetricOut[]): EnergyBoardOut => ({
  metrics,
  volatility_method_tr: "…",
  percentile_method_tr: "…",
});

describe("utcTimeLabel", () => {
  it("prints the reading's own UTC time", () => {
    expect(utcTimeLabel("2026-08-30T11:45:00Z")).toBe("11:45");
  });

  it("returns null rather than inventing a timestamp", () => {
    expect(utcTimeLabel(null)).toBeNull();
    expect(utcTimeLabel(undefined)).toBeNull();
    expect(utcTimeLabel("not a date")).toBeNull();
  });
});

describe("buildCells", () => {
  it("puts every live pair, both energy contracts and the peg in one row", () => {
    const cells = buildCells(
      board([
        pair(),
        pair({ currency_pair: "EUR/TRY", value: 56.0939 }),
        pair({ currency_pair: "GBP/USD", value: 1.3553 }),
      ]),
      energy([metric(), metric({ metric_key: "fuel_price", label_tr: "Jet Yakıtı ˜", value: 145.16 })]),
    );

    expect(cells.map((cell) => cell.key)).toEqual([
      "oil_price",
      "fuel_price",
      "fx_usd_try",
      "fx_eur_try",
      "fx_gbp_usd",
      "usd_sar_peg",
    ]);
  });

  it("links each card to its own KPI detail page", () => {
    const cells = buildCells(board([pair({ currency_pair: "EUR/TRY" })]), null);
    expect(cells.find((cell) => cell.key === "fx_eur_try")?.href).toBe("/kpi/fx_eur_try");
  });

  it("gives the peg no deltas, no series and no link -- it has not moved since 1986", () => {
    const peg = buildCells(board([]), null).find((cell) => cell.key === "usd_sar_peg");

    expect(peg?.staticLabel).toBe("Sabit · 3,75 (SAMA)");
    expect(peg?.dayDeltaPct).toBeNull();
    expect(peg?.series).toEqual([]);
    expect(peg?.href).toBeUndefined();
  });

  it("formats a TRY rate at two decimals and a cross at four", () => {
    const cells = buildCells(
      board([pair({ currency_pair: "USD/TRY", value: 41.7231 }), pair({ currency_pair: "EUR/USD", value: 1.16423 })]),
      null,
    );

    expect(cells.find((cell) => cell.key === "fx_usd_try")?.value).toBe("41,72");
    expect(cells.find((cell) => cell.key === "fx_eur_usd")?.value).toBe("1,1642");
  });

  it("carries the energy contract's own day and week change, not a KPI-list delta", () => {
    const cells = buildCells(null, energy([metric({ day_change_pct: 1.2, week_change_pct: -0.8 })]));
    const brent = cells.find((cell) => cell.key === "oil_price");

    expect(brent?.dayDeltaPct).toBe(1.2);
    expect(brent?.weekDeltaPct).toBe(-0.8);
    expect(brent?.tone).toBe("costly"); // a rise in a cost base IS bad
  });

  it("marks an FX move as neither good nor bad", () => {
    const cells = buildCells(board([pair()]), null);
    expect(cells.find((cell) => cell.key === "fx_usd_try")?.tone).toBe("neutral");
  });

  it("skips an energy contract with no reading rather than printing a blank card", () => {
    const cells = buildCells(null, energy([metric({ value: null })]));
    expect(cells).toEqual([]);
  });

  it("keeps the display order fixed even when a pair is temporarily missing", () => {
    // The API returns the pairs it has; the strip must not reshuffle when one
    // of them has no reading yet.
    const cells = buildCells(
      board([pair({ currency_pair: "USD/CNY", value: 7.2 }), pair({ currency_pair: "USD/TRY" })]),
      null,
    );
    expect(cells.map((cell) => cell.key)).toEqual(["fx_usd_try", "fx_usd_cny", "usd_sar_peg"]);
  });
});

describe("MarketStrip", () => {
  it("prints the value, both deltas and the as-of time on one card", () => {
    render(<MarketStrip board={board([pair()])} energy={null} />);

    expect(screen.getByText("USD/TRY")).toBeInTheDocument();
    expect(screen.getByText("41,72")).toBeInTheDocument();
    expect(screen.getByText("+%0,4")).toBeInTheDocument(); // day
    expect(screen.getByText("-%1,1")).toBeInTheDocument(); // week
    expect(screen.getByText("11:45")).toBeInTheDocument();
  });

  it("says a new pair has no history yet rather than printing 0%", () => {
    // EUR/TRY and GBP/USD are new to the 15-minute cron: for a while they
    // genuinely have neither a day nor a week of history, and a 0% there would
    // be a fabrication.
    render(
      <MarketStrip
        board={board([
          pair({
            currency_pair: "EUR/TRY",
            value: 56.0939,
            day_delta_pct: null,
            week_delta_pct: null,
            month_delta_pct: null,
            sparkline: [56.0939],
          }),
        ])}
        energy={null}
      />,
    );

    expect(screen.getByText("EUR/TRY")).toBeInTheDocument();
    expect(screen.getByText("yeterli geçmiş yok")).toBeInTheDocument();
    expect(screen.queryByText(/%0,0/)).not.toBeInTheDocument();
  });

  it("degrades to a stated failure rather than an empty band", () => {
    render(<MarketStrip board={null} energy={null} />);
    expect(screen.getByText(/Piyasa verisi şu anda okunamıyor/)).toBeInTheDocument();
  });
});
