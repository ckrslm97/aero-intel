"use client";

import { MicroTrend, type MicroTrendTone } from "@/components/charts/micro-trend";
import { YearDots } from "@/components/charts/year-dots";
import { Delta } from "@/components/ui/delta";
import { StatusPill, statusToneOf, type StatusTone } from "@/components/ui/status-pill";
import { useNow } from "@/hooks/use-now";
import {
  ANNUAL_KIND_SUFFIX,
  annualScopeLabel,
  dailyCloseBadge,
  type Freshness,
  freshnessOf,
} from "@/lib/cockpit";
import { formatMetricValue, formatUtcTime } from "@/lib/format";
import type {
  AnnualPoint,
  AnnualSeries,
  AnnualSeriesBoardOut,
  CockpitSignal,
  EnergyBoardOut,
  KokpitFxBoardOut,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** Which clock a cell runs on. This is the page's central distinction, so it
 * is a field on the data rather than a styling decision at the leaf:
 *
 * * `annual` -- IATA's global industry series. Published twice a year, eight
 *   yearly points, industry-wide, with the current year a forecast. Drawn as
 *   discrete dots.
 * * `daily`  -- a settled DAILY CLOSE. One reading per trading day, final once
 *   published. A continuous line, like `live`, because the series is
 *   continuous -- but never lit and never called "canlı".
 * * `live`   -- a Yahoo series the cron re-reads every ~15 minutes. Drawn as a
 *   continuous line, and the only cadence allowed to glow.
 *
 * `daily` exists because Brent was being judged as `live`: the fuel cell ran
 * the 30-minute FX window (one cron period plus a missed run) over a number
 * that changes once a day, so it read "GECİKMELİ" from half an hour after the
 * settlement until the next one -- almost the entire day, over a perfectly
 * current close. Calling it "CANLI · 15dk" instead would have been the
 * opposite lie. A settled close is neither; it has its own vocabulary, in
 * `dailyCloseBadge` (lib/cockpit.ts).
 *
 * A cell never mixes them, and the annual block is separated from the rest by
 * a hairline seam so a reader sees the boundary before reading a single
 * label. */
export type Cadence = "annual" | "daily" | "live";

export interface PulseDelta {
  /** "25→26T", "1g", "1h" -- the window, printed next to the number. */
  scope: string;
  pct: number | null;
  /** Overrides the "%" formatting, for a percentage-POINT move. */
  valueLabel?: string;
}

export interface PulseCell {
  key: string;
  label: string;
  cadence: Cadence;
  /** Whether THIS READING is currently live -- not whether the series is.
   *
   * These are different questions and the cell used to answer the second one
   * in the first one's voice: the lamp and the value glow were keyed to
   * `cadence`, which is a constant per cell, so a KUR cell whose badge read
   * "GECİKMELİ · 40 sa" still rendered a lit `bg-signal` dot over a glowing
   * number. Colour is the one channel this row reserves for liveness, so a lit
   * lamp on a forty-hour-old reading is exactly the badge this change exists
   * to delete, left standing where the words no longer say it.
   *
   * Derived from `freshnessOf(...).state === "live"`, so it is false with no
   * clock yet (`pending`) as well as when the reading is late -- the same
   * three-state caution the header band takes (cockpit-header.tsx). `false`
   * for every `daily` and `annual` cell by construction: a settled close is
   * not a live price. */
  lit: boolean;
  /** "IATA 2026T", "CANLI · 15 DK'DA BİR", "GÜNLÜK KAPANIŞ · dün". */
  badge: string;
  /** HH:MM of the reading in UTC -- the cell prints "UTC" beside it, because
   * the topbar clock two rows up is on İstanbul time and an unlabelled "19:50"
   * next to it is three hours of silent error. */
  asOfLabel: string | null;
  /** null when the series behind the cell did not load at all. */
  value: string | null;
  unit: string | null;
  deltas: PulseDelta[];
  tone: MicroTrendTone;
  /** Populated for `annual` cells. */
  points: AnnualPoint[];
  /** Populated for `live` cells. */
  series: number[];
  /** What to print in the 20px trend slot when there is nothing to draw. The
   * slot keeps its height either way -- the fold arithmetic in app/page.tsx
   * depends on this cell being exactly 104px whatever the data does. */
  emptyNote: string | null;
  title: string;
  /** The threshold band for this cell's driver, from `/kokpit/signals`.
   *
   * The owner's Market Pulse spec asked for "sparkline + yön + değer + değişim
   * + STATUS" in every cell, and this is that status -- the one part of the
   * spec the first draft did not implement, which is why the same two drivers
   * ended up with a card of their own in Günün Özeti just to carry a word.
   * Now the judgement sits on the surface that already carries the number, and
   * Günün Özeti carries only the drivers that have no cell here (see
   * daily-summary.tsx).
   *
   * Null on the three annual cells, and that is not an omission: nobody in
   * this system publishes a threshold for an IATA yearly series, and a band
   * invented for one would be the composite score sector-balance.tsx refuses. */
  status: { tone: StatusTone; label: string; title: string } | null;
}

/** An annual cell's value, with the Turkish percent sign where the unit is one.
 *
 * The DIGITS are `formatMetricValue`'s (lib/format.ts) and no longer this
 * file's: percent and cent metrics carry meaningful decimals -- compact
 * notation renders 84,00 as "84" -- and this cell used to say so in its own
 * copy of the rule, at a different precision from the KPI strip's copy and
 * from the /kpi detail page, which had no such rule at all. What stays here is
 * PLACEMENT, which is a layout fact: "%84,00" reads as Turkish, and the cell
 * then suppresses its unit row so the five cells keep one height.
 */
function annualValue(value: number, unit: string, metricKey?: string): string {
  const digits = formatMetricValue(value, unit, metricKey);
  return unit === "%" ? `%${digits}` : digits;
}

function signedPoints(diff: number): string {
  const sign = diff > 0 ? "+" : diff < 0 ? "-" : "";
  return `${sign}${Math.abs(diff).toFixed(1).replace(".", ",")}pp`;
}

/** The year-on-year move between an annual series' last two points.
 *
 * A percentage series moves in percentage POINTS, not percent: load factor
 * going 83,5 -> 84,0 has risen half a point, and printing "+%0,6" for it would
 * be a different (and wrong) claim. */
function annualDelta(series: AnnualSeries): PulseDelta {
  const points = series.points;
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];
  if (!latest || !previous) {
    return { scope: "yıllık", pct: null };
  }
  const scope = annualScopeLabel(previous, latest);
  if (series.unit === "%") {
    const diff = latest.value - previous.value;
    return { scope, pct: diff, valueLabel: signedPoints(diff) };
  }
  if (!previous.value) return { scope, pct: null };
  return { scope, pct: ((latest.value - previous.value) / previous.value) * 100 };
}

/** The three annual cells, in the owner's own order and under the owner's own
 * names. The cells were NOT renamed to fit the data -- only the way they are
 * DRAWN changed (see YearDots). */
const ANNUAL_CELLS: { key: string; label: string }[] = [
  { key: "rpk", label: "TALEP" },
  { key: "ask", label: "KAPASİTE" },
  { key: "load_factor", label: "DOLULUK" },
];

/** How often the FX cron re-reads the pair. Stated on the cell whether or not
 * the reading is current, because it is a fact about the SERIES rather than a
 * claim about this reading. */
const FX_CADENCE_TR = "15 DK'DA BİR";

/** A live cell's badge is EARNED, not printed.
 *
 * "CANLI" used to be a constant: the cell said it whether the reading was
 * fifteen minutes or two days old, while the page header three centimetres
 * above correctly said "Gecikmeli · son 16:50" off the same timestamps. One
 * screen, two answers to "is this current?". `freshnessOf` is the header's own
 * rule (30 minutes, i.e. one missed cron run) and now decides both.
 *
 * The two states this grew are both refusals to guess:
 *
 *   * with no client clock yet (`pending`) the badge names the CADENCE and
 *     stops -- "15 DK'DA BİR" is true of the series no matter what time it is,
 *     while "CANLI" would be exactly the pre-rendered, cached liveness claim
 *     this whole change exists to delete;
 *   * a late reading now says HOW late, the same way the header does. A bare
 *     "GECİKMELİ" over a two-day-old rate and over a forty-minute-old one is
 *     the same word for two very different numbers.
 */
function liveBadge(fresh: Freshness): string {
  switch (fresh.state) {
    case "missing":
      return "VERİ YOK";
    case "pending":
      return FX_CADENCE_TR;
    case "live":
      return `CANLI · ${FX_CADENCE_TR}`;
    case "stale":
      return `GECİKMELİ · ${fresh.delayLabel}`;
  }
}

function annualCell(
  { key, label }: { key: string; label: string },
  series: AnnualSeries | undefined,
  scopeTr: string | null,
): PulseCell {
  const base = {
    key,
    label,
    cadence: "annual" as const,
    // An annual series is never live, whatever the clock says.
    lit: false,
    // No YEAR in the fallback badge. It used to read "IATA 2026T" even when
    // the series had not loaded at all -- a cell printing "—" for its value
    // while asserting which edition the missing number came from.
    badge: "IATA",
    asOfLabel: null,
    tone: "neutral" as const,
    series: [],
    // The scope sentence comes from the payload (`AnnualSeriesBoardOut.scope_tr`,
    // itself derived from the seed's publication date) rather than from a
    // hard-coded "Haziran 2026" here. Seed a newer IATA edition and the badge
    // year moves with the data; a literal in this file would not.
    title: scopeTr
      ? `${scopeTr} · TK verisi değil`
      : "IATA Küresel Görünüm · sektör geneli · yıllık · TK verisi değil",
    status: null,
  };
  const latest = series?.points[series.points.length - 1];
  if (!series || !latest) {
    return {
      ...base,
      value: null,
      unit: null,
      deltas: [{ scope: "yıllık", pct: null }],
      points: [],
      emptyNote: "IATA serisi yüklenmedi",
    };
  }
  return {
    ...base,
    badge: `IATA ${latest.year}${ANNUAL_KIND_SUFFIX[latest.kind]}`,
    value: annualValue(latest.value, series.unit, series.metric_key),
    // A percentage is printed as "%84,00" with nothing after it; the unit row
    // still occupies its 12px so the five cells stay the same height.
    unit: series.unit === "%" ? null : series.unit,
    deltas: [annualDelta(series)],
    points: series.points,
    emptyNote: series.points.length < 2 ? "tek yıllık nokta" : null,
  };
}

/**
 * Map the three server boards onto the owner's five Market Pulse cells.
 *
 * Pure and exported so the mapping -- which cell, which cadence, which unit,
 * and what happens when a source is missing -- is asserted by a test rather
 * than by mounting the page.
 *
 * The row is ALWAYS five cells. A missing source thins a cell to "—" with a
 * stated reason; it never removes it. A heartbeat that skips a beat is not a
 * heartbeat, and the reader would have no way to tell a dead source from a
 * metric we quietly stopped carrying.
 */
export function buildPulseCells(
  annual: AnnualSeriesBoardOut | null,
  board: KokpitFxBoardOut | null,
  energy: EnergyBoardOut | null,
  signals: CockpitSignal[] = [],
  /** The reader's clock, or `null` when there is not one yet. Defaulting to
   * `new Date()` is what let a cached server render claim liveness minutes
   * after the fact; defaulting to "no clock" costs a badge one frame and
   * cannot lie. */
  now: Date | null = null,
): PulseCell[] {
  const byKey = new Map((annual?.series ?? []).map((entry) => [entry.metric_key, entry]));
  const cells = ANNUAL_CELLS.map((spec) =>
    annualCell(spec, byKey.get(spec.key), annual?.scope_tr ?? null),
  );

  // The band is the SERVER'S, never re-derived here: `cockpit_signals_service`
  // owns every threshold on this page, so the pill on a pulse cell and the
  // tile on /sinyaller cannot disagree about what "Dikkat" means.
  const bandOf = (key: CockpitSignal["key"]): PulseCell["status"] => {
    const signal = signals.find((entry) => entry.key === key);
    if (!signal) return null;
    return {
      tone: statusToneOf(signal.level),
      label: signal.level_label_tr,
      // The threshold that produced the band and the method behind it. The
      // cell prints the band; a reader who wants to know why it is amber gets
      // the sentence, not a colour to interpret.
      title: [signal.reason_tr, signal.method_tr, `Kaynak: ${signal.source}`]
        .filter(Boolean)
        .join("\n\n"),
    };
  };

  // --- cell 4: the anchor rate -------------------------------------------
  const usdTry = (board?.pairs ?? []).find((pair) => pair.currency_pair === "USD/TRY");
  // ONE freshness reading feeds both the badge and the lamp. Computed twice --
  // or, as it was, computed for the badge and guessed from `cadence` for the
  // lamp -- the two channels can and did disagree: "GECİKMELİ · 40 sa" under a
  // lit dot.
  const usdTryFreshness = freshnessOf(usdTry?.as_of, now);
  cells.push({
    key: "fx_usd_try",
    label: "KUR",
    cadence: "live",
    lit: usdTryFreshness.state === "live",
    badge: liveBadge(usdTryFreshness),
    asOfLabel: formatUtcTime(usdTry?.as_of),
    // Four decimals for a cross where the fourth digit is the one that moves,
    // two for a TRY or JPY rate where it is not. The cut used to be typed here
    // AND in the FX table AND nowhere at all on /kpi/fx_eur_usd, which printed
    // the same reading as "1,1". All three now call `formatMetricValue`, which
    // is the only copy of the rule.
    value: usdTry ? formatMetricValue(usdTry.value, usdTry.unit, "fx_usd_try") : null,
    unit: usdTry?.unit ?? null,
    deltas: [
      { scope: "1g", pct: usdTry?.day_delta_pct ?? null },
      { scope: "1h", pct: usdTry?.week_delta_pct ?? null },
    ],
    // NEUTRAL, and structurally so: a lira move is neither good nor bad for an
    // airline, and `KokpitFxPairOut` carries no `up_is_good` for exactly that
    // reason.
    tone: "neutral",
    points: [],
    series: usdTry?.sparkline ?? [],
    emptyNote: usdTry
      ? (usdTry.sparkline?.length ?? 0) > 1
        ? null
        : "yeterli geçmiş yok"
      : "kur okunamadı",
    title: usdTry ? `${usdTry.source} · ${usdTry.frequency_label}` : "Kur verisi okunamadı",
    status: bandOf("fx"),
  });

  // --- cell 5: the owner's "MARKET" slot ---------------------------------
  // Rival capacity, market share and price pressure do not exist in this
  // system in any model, column or endpoint. Rather than leave the fifth cell
  // empty or invent a number for it, the slot goes to Brent on the owner's own
  // instruction that fuel appear in Market Pulse as a single signal when it is
  // critical -- and it is the only live-priced cost base aviation has.
  const brent = (energy?.metrics ?? []).find((metric) => metric.metric_key === "oil_price");
  cells.push({
    key: "oil_price",
    label: "YAKIT · BRENT",
    cadence: "daily",
    // Never. A settled close draws a continuous line but is not a live price,
    // so it gets the line and not the colour.
    lit: false,
    // A settled daily close, in its own vocabulary -- see `Cadence` above.
    badge: dailyCloseBadge(brent?.as_of, now),
    asOfLabel: formatUtcTime(brent?.as_of),
    value: brent?.value != null ? formatMetricValue(brent.value, brent.unit) : null,
    unit: brent?.unit ?? null,
    deltas: [
      { scope: "1g", pct: brent?.day_change_pct ?? null },
      { scope: "1h", pct: brent?.week_change_pct ?? null },
    ],
    // A rise in a cost base IS bad. This is the one cell in the row that has a
    // polarity at all.
    tone: "costly",
    points: [],
    series: brent?.sparkline ?? [],
    emptyNote:
      brent?.value != null
        ? (brent.sparkline?.length ?? 0) > 1
          ? null
          : "yeterli geçmiş yok"
        : "yakıt okunamadı",
    title: brent ? (brent.note_tr ?? brent.source) : "Enerji verisi okunamadı",
    // Fuel's ONE appearance on this page, and this pill is why it can be one:
    // the number, the two windows, the trend and the threshold band now all
    // live in this cell. The Sektör Dengesi percentile row and the Günün
    // Özeti fuel tile were the second and third, and both are gone.
    status: bandOf("fuel"),
  });

  return cells;
}

function Cell({ cell, seam }: { cell: PulseCell; seam: boolean }) {
  // `min-h` and `shrink-0` throughout, where this was a hard `h-[104px]` with
  // shrinkable children. The five slots below add up to more than 104px once
  // the annual cells' YearDots (20px of dots + its own year labels) is counted,
  // so flex was silently compressing whichever child had an `overflow: hidden`
  // on it -- the unit row rendered 8px tall inside its 12px box and clipped
  // "RPK" and "$/varil" from below. The row still stands at one height: the
  // grid stretches all five to the tallest.
  return (
    <div
      title={cell.title}
      className={cn(
        "relative flex min-h-[104px] flex-col justify-between gap-1 rounded-lg border border-border bg-card/60 px-3 py-2.5",
        // The seam between the two cadences. Only at the breakpoint where the
        // five cells actually sit in one row -- below that they wrap and a
        // vertical rule would divide the wrong pair.
        seam &&
          "xl:before:absolute xl:before:-left-1.5 xl:before:top-1 xl:before:bottom-1 xl:before:w-px xl:before:bg-border xl:before:content-['']",
      )}
    >
      {/* Wraps for the same reason the delta row does: in a 170px phone cell
          "YAKIT · BRENT" beside a cadence badge and a timestamp truncated to
          "YAKI…", which names nothing. The badge drops to its own line
          instead. */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-1.5 sm:flex-nowrap">
        <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {cell.label}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
          {/* Shape says CADENCE, colour says THIS READING. A round lamp is a
              series that keeps flowing (15-minute FX, daily closes); a filled
              square is a series published a couple of times a year. The two
              are independent on purpose: the shape is a fact about the series
              and never changes, the colour is a claim about the number printed
              below it and goes out the moment that number is late -- or before
              the first client tick, when there is no clock to judge it with. */}
          <span
            aria-hidden
            className={cn(
              "size-1",
              cell.cadence !== "annual" && "rounded-full",
              cell.lit ? "bg-signal" : "bg-muted-foreground",
            )}
          />
          {cell.badge}
          {/* The zone is NAMED. This stamp is UTC while the topbar clock three
              rows up is İstanbul, so a bare "19:50" beside a reader's 22:50 is
              three hours of error with nothing on screen to catch it. The
              header band and the FX rows say "UTC" for the same reason. */}
          {cell.asOfLabel && <span className="tabular-nums">{cell.asOfLabel} UTC</span>}
        </span>
      </div>

      <div className="flex shrink-0 items-center">
        <span
          className={cn(
            "text-[26px] font-semibold leading-none tracking-tight tabular-nums",
            // Only a LIVE READING glows -- not merely a reading from a live
            // series. This was keyed to the cadence, so a forty-hour-old rate
            // glowed under its own "GECİKMELİ" badge.
            cell.lit && cell.value !== null && "dark:text-glow",
            cell.value === null && "text-muted-foreground",
          )}
        >
          {cell.value ?? "—"}
        </span>
      </div>

      {/* A fixed 10px even when empty. A percentage prints as "%84,00" with no
          unit after it, and letting that cell's unit row collapse to zero
          would slide its delta and its dots out of line with the four cells
          beside it -- the row is a comparison, so the slots have to agree. */}
      <div className="h-[10px] shrink-0 truncate text-[10px] leading-none text-muted-foreground">
        {cell.unit ?? ""}
      </div>

      {/* WRAPS. At 375px the row is two cells wide, and "1g ↗ +%0,1  1h ↗
          +%0,4  ⊙ DİKKAT" does not fit a 170px cell -- with every child
          `shrink-0` the pill pushed 19px past the viewport and gave the whole
          page a horizontal scrollbar. Wrapping costs one line of cell height
          on a phone and nothing at all above `sm`. */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-1">
        {cell.deltas.map((delta) => (
          <Delta
            key={delta.scope}
            pct={delta.pct}
            valueLabel={delta.valueLabel}
            scope={delta.scope}
            tone={cell.tone === "costly" ? "costly" : "neutral"}
          />
        ))}
        {/* The band sits with the CHANGE, not with the value: it is a
            judgement about how far something moved, and putting it beside the
            deltas says so without a word of prose. */}
        {cell.status && (
          <StatusPill tone={cell.status.tone} title={cell.status.title} className="ml-auto">
            {cell.status.label}
          </StatusPill>
        )}
      </div>

      {/* The trend slot. Tall enough for YearDots (dots plus its own year
          labels) so the annual cells no longer overflow their card; the live
          cells' 20px line and the empty note sit inside the same box, so the
          five cells still line up row for row. */}
      <div className="flex h-8 shrink-0 items-center">
        {cell.emptyNote ? (
          <span className="block text-[10px] leading-none text-muted-foreground">
            {cell.emptyNote}
          </span>
        ) : cell.cadence === "annual" ? (
          <YearDots points={cell.points} unitLabel={cell.unit ?? undefined} className="w-full" />
        ) : (
          <MicroTrend data={cell.series} tone={cell.tone} title={`${cell.label} trendi`} />
        )}
      </div>
    </div>
  );
}

/**
 * MARKET PULSE -- the page's heartbeat, five cells, no prose.
 *
 * Replaces the nine-cell horizontally-scrolling `MarketStrip`. The owner asked
 * for exactly these five readings and got exactly these five readings; what
 * changed is that the three annual ones no longer pretend to be live. See
 * `Cadence` above, `YearDots` for why, and section E of the design spec for
 * the two places the owner's wording had to bend to the data (the "MARKET"
 * cell, and the sparklines on the IATA series).
 */
export function MarketPulseRow({
  annual,
  board,
  energy,
  signals = [],
}: {
  annual: AnnualSeriesBoardOut | null;
  board: KokpitFxBoardOut | null;
  energy: EnergyBoardOut | null;
  /** `/kokpit/signals`, for the two live cells' threshold bands. Optional so a
   * signals outage thins the cells to a number without a band rather than
   * emptying the row. */
  signals?: CockpitSignal[];
}) {
  // The reader's clock, not the pre-render's: this row is inside a page cached
  // for `revalidate: 60`, so "CANLI" decided at build time is a claim about a
  // moment that has already passed by the time anyone reads it.
  const now = useNow();
  const cells = buildPulseCells(annual, board, energy, signals, now);
  return (
    <div
      aria-label="Piyasa nabzı"
      className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5"
    >
      {cells.map((cell, index) => (
        <Cell key={cell.key} cell={cell} seam={index === 3} />
      ))}
    </div>
  );
}
