import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  AnnualPoint,
  AnnualSeries,
  AnnualSeriesBoardOut,
  CockpitSignal,
  EnergyBoardOut,
  EnergyMetricOut,
  KokpitFxBoardOut,
  KokpitFxPairOut,
} from "@/lib/types";

import { buildPulseCells, MarketPulseRow } from "./market-pulse-row";

const point = (year: number, value: number, kind: AnnualPoint["kind"] = "actual"): AnnualPoint => ({
  year,
  value,
  kind,
});

const series = (overrides: Partial<AnnualSeries> = {}): AnnualSeries => ({
  metric_key: "rpk",
  label_tr: "RPK",
  unit: "RPK",
  up_is_good: true,
  points: [point(2023, 9_000), point(2024, 9_400), point(2025, 9_520, "estimate"), point(2026, 9_719, "forecast")],
  ...overrides,
});

/** Five minutes after the newest fixture reading, so "CANLI" is earned rather
 * than assumed. Passed explicitly everywhere the badge is asserted: with the
 * real clock these fixtures are days old and the badge is -- correctly --
 * "GECİKMELİ". */
const NOW = new Date("2026-08-30T20:05:00Z");

const annualBoard = (rows: AnnualSeries[]): AnnualSeriesBoardOut => ({
  series: rows,
  source: "IATA",
  source_url: "https://iata.org",
  scope_tr: "sektör geneli · yıllık",
});

const pair = (overrides: Partial<KokpitFxPairOut> = {}): KokpitFxPairOut => ({
  currency_pair: "USD/TRY",
  value: 48.2505,
  unit: "TRY",
  day_delta_pct: 0.1,
  week_delta_pct: 1.2,
  month_delta_pct: 3.4,
  sparkline: [47.9, 48.1, 48.25],
  as_of: "2026-08-30T19:50:00Z",
  source: "Yahoo Finance (TRY=X)",
  source_url: "https://finance.yahoo.com/quote/TRY=X",
  frequency_label: "~15 dakikada bir",
  ...overrides,
});

const fxBoard = (pairs: KokpitFxPairOut[]): KokpitFxBoardOut => ({
  pairs,
  peg: {
    currency_pair: "USD/SAR",
    value: 3.75,
    label: "Sabit · 3,75 (SAMA)",
    source: "SAMA",
    source_url: "https://www.sama.gov.sa",
  },
});

const brent = (overrides: Partial<EnergyMetricOut> = {}): EnergyMetricOut => ({
  metric_key: "oil_price",
  label_tr: "Brent",
  unit: "$/bbl",
  value: 71.2,
  as_of: "2026-08-30T20:00:00Z",
  day_change_pct: 3.1,
  week_change_pct: 4.0,
  month_change_pct: 4.1,
  ytd_change_pct: 12.4,
  percentile_1y: 78.5,
  volatility_30d_pct: 24.3,
  sparkline: [68, 70, 71.2],
  source: "Yahoo Finance (BZ=F)",
  source_url: "https://finance.yahoo.com/quote/BZ=F",
  href: "/kpi/oil_price",
  is_estimate: false,
  note_tr: null,
  ...overrides,
});

const energyBoard = (metrics: EnergyMetricOut[]): EnergyBoardOut => ({
  metrics,
  volatility_method_tr: "…",
  percentile_method_tr: "…",
});

const fullAnnual = annualBoard([
  series(),
  series({ metric_key: "ask", label_tr: "ASK", unit: "ASK" }),
  series({
    metric_key: "load_factor",
    label_tr: "Doluluk",
    unit: "%",
    points: [point(2023, 82.1), point(2024, 83.2), point(2025, 83.5, "estimate"), point(2026, 84.0, "forecast")],
  }),
]);

describe("buildPulseCells", () => {
  it("keeps the owner's five cells in the owner's order", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]));
    expect(cells.map((cell) => cell.key)).toEqual([
      "rpk",
      "ask",
      "load_factor",
      "fx_usd_try",
      "oil_price",
    ]);
    expect(cells.map((cell) => cell.label)).toEqual([
      "TALEP",
      "KAPASİTE",
      "DOLULUK",
      "KUR",
      "YAKIT · BRENT",
    ]);
  });

  it("still renders five cells when every source is down", () => {
    // A heartbeat that skips a beat is not a heartbeat, and a reader could not
    // tell a dead source from a metric we quietly stopped carrying.
    const cells = buildPulseCells(null, null, null);
    expect(cells).toHaveLength(5);
    expect(cells.every((cell) => cell.value === null)).toBe(true);
    expect(cells[0].emptyNote).toBe("IATA serisi yüklenmedi");
  });

  it("puts the three IATA cells on the annual clock and the two market cells on the live one", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], NOW);
    expect(cells.map((cell) => cell.cadence)).toEqual([
      "annual",
      "annual",
      "annual",
      "live",
      "live",
    ]);
    // The annual cells must never wear the live vocabulary.
    expect(cells[0].badge).toBe("IATA 2026T");
    expect(cells[0].asOfLabel).toBeNull();
    expect(cells[3].badge).toBe("CANLI · 15dk");
    expect(cells[3].asOfLabel).toBe("19:50");
  });

  it("stops saying CANLI once the reading falls outside the live window", () => {
    // The badge used to be a constant, so a cell said "CANLI · 15dk" over a
    // two-day-old reading while the page header, off the SAME timestamps,
    // correctly said "Gecikmeli". One screen cannot hold two answers to "is
    // this current?".
    const stale = new Date("2026-09-01T12:00:00Z");
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], stale);
    expect(cells[3].badge).toBe("GECİKMELİ");
    expect(cells[4].badge).toBe("GECİKMELİ");
    // The reading itself is still printed with its own time -- it is real, it
    // is merely old.
    expect(cells[3].value).toBe("48,25");
    expect(cells[3].asOfLabel).toBe("19:50");
  });

  it("claims no IATA edition year when the annual board did not load", () => {
    // "IATA 2026T" beside an em dash asserted which edition the missing number
    // came from.
    const cells = buildPulseCells(null, null, null);
    expect(cells[0].badge).toBe("IATA");
    expect(cells[0].value).toBeNull();
  });

  it("takes its scope sentence from the payload rather than a hard-coded date", () => {
    const cells = buildPulseCells(
      annualBoard([series()]),
      null,
      null,
    );
    expect(cells[0].title).toContain("sektör geneli · yıllık");
    expect(cells[0].title).not.toContain("Haziran 2026");
  });

  it("gives an annual cell one year-on-year delta, never a 1g/1h pair", () => {
    const cells = buildPulseCells(fullAnnual, null, null);
    expect(cells[0].deltas).toHaveLength(1);
    expect(cells[0].deltas[0].scope).toBe("25→26T");
    expect(cells[3].deltas.map((d) => d.scope)).toEqual(["1g", "1h"]);
  });

  it("moves a percentage series in POINTS, not percent", () => {
    // Load factor 83,5 -> 84,0 has risen half a POINT. "+%0,6" would be a
    // different and wrong claim.
    const cells = buildPulseCells(fullAnnual, null, null);
    expect(cells[2].deltas[0].valueLabel).toBe("+0,5pp");
    // Two decimals, and the second one is not decoration: this cell used to
    // print a percentage to ONE decimal while the KPI strip's copy of the same
    // rule printed it to two and /kpi/load_factor printed it to none. The
    // digits now come from `formatMetricValue` (lib/format.ts), which is the
    // only place any surface asks how precise a percent is.
    expect(cells[2].value).toBe("%84,00");
  });

  it("colours only the cost base", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]));
    expect(cells[3].tone).toBe("neutral"); // a lira move is neither good nor bad
    expect(cells[4].tone).toBe("costly"); // a Brent rise IS bad
  });

  it("prints a fresh reading with no history at full size, saying only the history is missing", () => {
    const cells = buildPulseCells(
      null,
      fxBoard([pair({ sparkline: [48.2505], day_delta_pct: null, week_delta_pct: null })]),
      null,
    );
    const fx = cells[3];
    expect(fx.value).toBe("48,25"); // the value is real and fresh -- not dimmed
    expect(fx.emptyNote).toBe("yeterli geçmiş yok");
    expect(fx.deltas.every((delta) => delta.pct === null)).toBe(true);
  });

  it("says so when a source could not be read at all", () => {
    const cells = buildPulseCells(null, null, energyBoard([brent({ value: null })]));
    expect(cells[3].emptyNote).toBe("kur okunamadı");
    expect(cells[4].emptyNote).toBe("yakıt okunamadı");
  });
});

const signal = (overrides: Partial<CockpitSignal> = {}): CockpitSignal => ({
  key: "fx",
  label_tr: "Kur riski",
  level: "warning",
  level_label_tr: "Dikkat",
  value_label: "48,2505 TRY",
  reason_tr: "USD/TRY haftalık %1,2 yükseldi.",
  method_tr: "Eşik: haftalık %1'i aşan hareket.",
  source: "Yahoo Finance",
  source_url: null,
  href: null,
  as_of: "2026-08-30T19:50:00Z",
  ...overrides,
});

describe("threshold bands", () => {
  it("bands the two live cells from /kokpit/signals and leaves the annual cells alone", () => {
    // The owner's Market Pulse spec asked for a STATUS in every cell. The
    // first draft did not implement it, which is exactly why the same two
    // drivers ended up with a tile of their own in Günün Özeti just to carry
    // one word -- and fuel ended up on the page three times.
    //
    // The annual cells get no band, and that is not an omission: nobody
    // publishes a threshold for an IATA yearly series, and one invented here
    // would be the composite score this page refuses to build.
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [
      signal(),
      signal({ key: "fuel", level: "critical", level_label_tr: "Yüksek" }),
    ]);
    expect(cells.slice(0, 3).every((cell) => cell.status === null)).toBe(true);
    expect(cells[3].status?.label).toBe("Dikkat");
    expect(cells[3].status?.tone).toBe("warning");
    expect(cells[4].status?.label).toBe("Yüksek");
    expect(cells[4].status?.tone).toBe("critical");
  });

  it("carries the threshold and the method behind the band, not just a colour", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [signal()]);
    expect(cells[3].status?.title).toContain("Eşik: haftalık %1'i aşan hareket.");
    expect(cells[3].status?.title).toContain("Kaynak: Yahoo Finance");
  });

  it("thins the cell to a number when the signals endpoint says nothing", () => {
    // A signals outage must not empty the row: the reading is still real.
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), []);
    expect(cells[3].status).toBeNull();
    expect(cells[3].value).toBe("48,25");
  });

  it("never renders an unreadable driver as an all-clear", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [
      signal({ level: "unknown", level_label_tr: "Bilinmiyor" }),
    ]);
    expect(cells[3].status?.tone).toBe("neutral");
  });
});

describe("MarketPulseRow", () => {
  it("prints the live values, both windows and the reading's own time", () => {
    render(
      <MarketPulseRow annual={fullAnnual} board={fxBoard([pair()])} energy={energyBoard([brent()])} />,
    );
    expect(screen.getByText("48,25")).toBeInTheDocument();
    expect(screen.getByText("19:50")).toBeInTheDocument();
    // Both live cells carry the same two windows -- the point of the row is
    // that they are comparable.
    expect(screen.getAllByText("1g")).toHaveLength(2);
    expect(screen.getAllByText("1h")).toHaveLength(2);
  });

  it("prints the band beside the deltas, on the cell that carries the number", () => {
    render(
      <MarketPulseRow
        annual={fullAnnual}
        board={fxBoard([pair()])}
        energy={energyBoard([brent()])}
        signals={[signal()]}
      />,
    );
    expect(screen.getByText("Dikkat")).toBeInTheDocument();
  });

  it("never prints a fabricated 0% for a pair with no history", () => {
    render(
      <MarketPulseRow
        annual={null}
        board={fxBoard([pair({ sparkline: [48.2505], day_delta_pct: null, week_delta_pct: null })])}
        energy={null}
      />,
    );
    expect(screen.getAllByText("yeterli geçmiş yok").length).toBeGreaterThan(0);
    expect(screen.queryByText(/%0,0/)).not.toBeInTheDocument();
  });
});
