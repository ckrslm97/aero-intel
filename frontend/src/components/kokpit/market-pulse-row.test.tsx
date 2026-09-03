import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("gives each cell the clock its own series actually runs on", () => {
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], NOW);
    expect(cells.map((cell) => cell.cadence)).toEqual([
      "annual",
      "annual",
      "annual",
      "live",
      // Brent is a settled DAILY close, not a quote. It used to sit here as
      // "live" and be judged by the FX cron's 30-minute window, so the fuel
      // cell read "GECİKMELİ" from half an hour after the settlement until the
      // next one -- nearly the whole day, over a current number.
      "daily",
    ]);
    // The annual cells must never wear the live vocabulary.
    expect(cells[0].badge).toBe("IATA 2026T");
    expect(cells[0].asOfLabel).toBeNull();
    expect(cells[3].badge).toBe("CANLI · 15 DK'DA BİR");
    expect(cells[3].asOfLabel).toBe("19:50");
    // ...and neither may the daily one.
    expect(cells[4].badge).toBe("GÜNLÜK KAPANIŞ · bugün");
  });

  it("stops saying CANLI once the reading falls outside the live window", () => {
    // The badge used to be a constant, so a cell said "CANLI · 15dk" over a
    // two-day-old reading while the page header, off the SAME timestamps,
    // correctly said "Gecikmeli". One screen cannot hold two answers to "is
    // this current?".
    const stale = new Date("2026-09-01T12:00:00Z");
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], stale);
    // And it says HOW late, the way the header does: one word over a
    // forty-hour gap and over a forty-minute one is the same word for two very
    // different numbers.
    expect(cells[3].badge).toBe("GECİKMELİ · 40 sa");
    expect(cells[4].badge).toBe("GÜNLÜK KAPANIŞ · 2 gün önce");
    // The reading itself is still printed with its own time -- it is real, it
    // is merely old.
    expect(cells[3].value).toBe("48,25");
    expect(cells[3].asOfLabel).toBe("19:50");
  });

  it("makes no freshness claim at all before the reader's clock has ticked", () => {
    // Kokpit is pre-rendered with `revalidate: 60`. A badge decided against the
    // RENDER's clock is a verdict frozen into cached HTML: production served an
    // 18:03 UTC reading under "CANLI" at 18:41. With no client tick yet both
    // live cells name their CADENCE -- a fact about the series -- and say
    // nothing about this reading's age.
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], null);
    expect(cells[3].badge).toBe("15 DK'DA BİR");
    expect(cells[4].badge).toBe("GÜNLÜK KAPANIŞ");
    for (const cell of [cells[3], cells[4]]) {
      expect(cell.badge).not.toContain("CANLI");
      expect(cell.badge).not.toContain("GECİKMELİ");
      // The stamp is a fact and is still printed: the cell goes quiet about
      // freshness, not about the reading.
      expect(cell.asOfLabel).not.toBeNull();
    }
  });

  it("defaults to having no clock rather than to the render's own", () => {
    // The default that caused the bug was `new Date()`. This one cannot lie:
    // the worst it can do is withhold a badge for one frame.
    const cells = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]));
    expect(cells[3].badge).toBe("15 DK'DA BİR");
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
    // One rule for every surface -- and it does not invent a digit. This cell
    // used to print a percentage to ONE decimal while the KPI strip's copy
    // printed it to two and /kpi/load_factor printed it to none; they all read
    // `formatMetricValue` (lib/format.ts) now. IATA states this figure as
    // 84,0, so a padded "84,00" would claim a hundredth of a point the source
    // never measured.
    expect(cells[2].value).toBe("%84");
  });

  it("lights the lamp for a LIVE READING, not for a live series", () => {
    // The lamp and the value glow were keyed to `cadence`, which is a constant
    // per cell -- so a KUR cell whose badge said "GECİKMELİ · 40 sa" still drew
    // the lit dot and the glowing number. Colour is the only channel this row
    // reserves for liveness, so that was the "canlı" claim the words had just
    // stopped making, still standing in the one place nobody had looked.
    const live = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], NOW);
    expect(live[3].lit).toBe(true);

    // Late: the badge says so, and now so does the colour.
    const stale = new Date("2026-09-01T12:00:00Z");
    const late = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], stale);
    expect(late[3].badge).toBe("GECİKMELİ · 40 sa");
    expect(late[3].lit).toBe(false);

    // No clock yet -- the server render, and the first client frame. The badge
    // withholds its verdict here, and the lamp has to withhold the same one or
    // the pre-rendered HTML carries a lit liveness claim without the word.
    const pending = buildPulseCells(fullAnnual, fxBoard([pair()]), energyBoard([brent()]), [], null);
    expect(pending[3].lit).toBe(false);

    // And the cadences that are never live, whatever the clock says.
    expect(live[4].lit).toBe(false); // a settled daily close is not a live price
    expect(live[0].lit).toBe(false); // an IATA annual series least of all
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
  // Two of these tests freeze the clock, and `useNow` keeps ONE module-level
  // interval per period shared by every consumer -- so a frozen clock left
  // behind would be the next test file's clock too.
  afterEach(() => {
    vi.useRealTimers();
  });

  it("prints the live values, both windows and the reading's own time", () => {
    render(
      <MarketPulseRow annual={fullAnnual} board={fxBoard([pair()])} energy={energyBoard([brent()])} />,
    );
    expect(screen.getByText("48,25")).toBeInTheDocument();
    // The stamp NAMES its zone. It is UTC while the topbar clock two rows up is
    // İstanbul, so a bare "19:50" beside a reader's 22:50 is three hours of
    // error with nothing on screen able to catch it.
    expect(screen.getAllByText("19:50 UTC").length).toBeGreaterThan(0);
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

  it("draws no lit dot and no glow over a late reading", () => {
    // The MARKUP half of the lamp fix. The bug lived in the class names --
    // `bg-signal` and `dark:text-glow` were keyed to the cell's cadence, which
    // never changes -- so this is the assertion that would have caught it, and
    // the one the cell-level test above cannot make.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-01T12:00:00Z"));
    const { container } = render(
      <MarketPulseRow annual={fullAnnual} board={fxBoard([pair()])} energy={energyBoard([brent()])} />,
    );
    // The words already said it...
    expect(screen.getByText("GECİKMELİ · 40 sa")).toBeInTheDocument();
    // ...and now the colour does too, on the whole row.
    expect(container.querySelectorAll(".bg-signal")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='text-glow']")).toHaveLength(0);
  });

  it("draws the lit dot when the reading really is live", () => {
    // The positive half: the lamp still means something. Without this, keying
    // `lit` to a constant `false` would pass the test above.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-30T20:05:00Z"));
    const { container } = render(
      <MarketPulseRow annual={fullAnnual} board={fxBoard([pair()])} energy={energyBoard([brent()])} />,
    );
    expect(screen.getByText("CANLI · 15 DK'DA BİR")).toBeInTheDocument();
    expect(container.querySelectorAll(".bg-signal")).toHaveLength(1);
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
