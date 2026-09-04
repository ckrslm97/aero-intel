import { AlertCenter } from "@/components/kokpit/alert-center";
import { CockpitHeader } from "@/components/kokpit/cockpit-header";
import { CompetitivePulse } from "@/components/kokpit/competitive-pulse";
import { DailySummary } from "@/components/kokpit/daily-summary";
import { FxBoardTable } from "@/components/kokpit/fx-board-table";
import { IataOutlook } from "@/components/kokpit/iata-outlook";
import { KpiStrip } from "@/components/kokpit/kpi-strip";
import { MarketPulseRow } from "@/components/kokpit/market-pulse-row";
import { SectionHeader } from "@/components/kokpit/section-header";
import { SectorBalance } from "@/components/kokpit/sector-balance";
import { SignalStream } from "@/components/kokpit/signal-stream";
import { ServerSourceError } from "@/components/server-source-error";
import { apiFetch } from "@/lib/api";
import type {
  AnnualSeriesBoardOut,
  CockpitSignalsOut,
  EnergyBoardOut,
  FxForecastOut,
  IataIndicatorOut,
  KokpitFxBoardOut,
} from "@/lib/types";

/** ISR: KPIs and FX move at most every 15 minutes, so a 60s revalidation
 * serves the page instantly and still stays current. */
const LIVE = { cache: "force-cache", next: { revalidate: 60 } } as const;
/** The IATA series and the curated indicators change when a person edits a
 * seed file, not between requests. */
const CURATED = { cache: "force-cache", next: { revalidate: 3600 } } as const;

/** One server-side source: what it answered, and whether it answered at all.
 *
 * `failed` is not derivable from `data`. `/kokpit/fx-forecasts` returning `[]`
 * and `/kokpit/fx-forecasts` returning 503 produce the same `data` and mean
 * opposite things -- "no institution published a forecast" versus "we did not
 * find out". The flag is the only place that difference survives. */
interface Source<T> {
  data: T | null;
  failed: boolean;
}

/** Fetch, and remember a failure AS a failure.
 *
 * Kokpit is nine sections over eleven endpoints, and one of them being down
 * must thin the page, never blank it -- the same per-source degradation
 * contract `useDataSource` gives the client components further down, applied
 * to the server-rendered half.
 *
 * This used to swallow the error and return an `empty` value the caller
 * supplied: `null` for the boards, `[]` for the lists. Downstream that is
 * indistinguishable from a real answer, so a dead `/kokpit/fx-forecasts`
 * printed a TAHMİN column with no forecasts in it and a dead
 * `/kokpit/annual-series` printed "IATA serisi henüz yüklenmedi" -- a sentence
 * about seeding, over an outage. Nothing here invents a value any more; the
 * render decides what an unread source looks like, per section. */
async function load<T>(
  path: string,
  init: RequestInit & { next?: { revalidate?: number } },
): Promise<Source<T>> {
  try {
    return { data: await apiFetch<T>(path, init), failed: false };
  } catch {
    return { data: null, failed: true };
  }
}

/** The sources a section wanted and did not get, named for the reader.
 *
 * A section whose every source failed renders no content at all -- there is
 * nothing to draw and a skeleton would be a lie about a request that is not
 * coming. A section that lost SOME of its sources still draws, with this line
 * above it saying which cells are missing rather than letting the reader read
 * their absence as a measurement. */
function missing(entries: readonly (readonly [string, Source<unknown>])[]): string[] {
  return entries.filter(([, source]) => source.failed).map(([label]) => label);
}

/**
 * KOKPİT -- the executive landing page.
 *
 * "LESS BUT BETTER. READING THE DASHBOARD SHOULD NOT REQUIRE READING."
 *
 * The page answers one question in thirty seconds: what is the market doing,
 * how are the industry's numbers moving, which way is the lira going, what is
 * IATA expecting, and what should worry me. The section order below IS that
 * answer, and sections 1-4 are sized to clear the fold together on a 13"
 * laptop -- see THE FOLD CONTRACT below for the measurement.
 *
 * THE TWO RULES EVERY LAYOUT DECISION HERE CAME FROM
 * --------------------------------------------------
 * 1. TWO CADENCES, TWO VISUAL FORMS. A continuous line means a live
 *    measurement (FX and energy, re-read every ~15 minutes). A discrete dot
 *    means an annual publication (IATA's industry series, revised twice a
 *    year, current year a forecast). No cell mixes them. See
 *    components/charts/year-dots.tsx for the three separate untruths a
 *    sparkline tells about an eight-point annual series.
 * 2. FORM ENCODES EPISTEMIC STATUS, COLOUR ENCODES JUDGEMENT. Filled vs hollow
 *    dots and solid vs dashed lines say "measured or projected". Green and red
 *    say only "good or bad". A forecast is NOT amber -- amber in this house
 *    means "warning" and nothing else.
 *
 * THE FOLD CONTRACT -- MEASURED, and budgeted against 735px, not 900
 * ------------------------------------------------------------------
 * The earlier contract was written against a 1440x900 window. That is not the
 * machine this page is read on: a 13" MacBook reports 1440 logical pixels wide
 * but roughly 735 of visible page once the browser chrome and this app's own
 * 96px shell are taken out. Budgeting against 900 meant the contract held on
 * the measuring machine and broke on the reader's.
 *
 * Measured in a browser against live data, dark and light, at 1440 and 1280:
 *
 *   1 Header               52  ->  bottom 148
 *   2 Market Pulse        218  ->  bottom 386
 *   3 Genel KPI (6 cells) 176  ->  bottom 582
 *   4 Günün Özeti         113  ->  bottom 715      <-- 13" fold at 735
 *   5 Kur / FX            373  ->  bottom 1108     <-- 1440x900 fold at 900
 *                                                       falls inside the table
 *
 * FOUR complete sections now clear the fold on the smallest machine anyone
 * reads this on, where the previous layout got three and a half. The room came
 * from two places and neither of them was a caveat:
 *
 *   * section 3 was a five-cell strip PLUS a four-column "Sektör Dengesi"
 *     panel, 287px. Three of that panel's four rows were arithmetic on two
 *     numbers already printed within two hundred pixels of it -- the
 *     demand-capacity scissor IS the load factor's direction, the
 *     revenue-traffic scissor IS yield's -- and the fourth was fuel's second
 *     appearance on a page instructed to show fuel once. Only the unit margin
 *     said something the page could not say elsewhere, so it became the sixth
 *     cell of the strip and the panel went away: 287 -> 176.
 *   * the section bylines were cut from 278 words to 191 (300px to 195px, 15%
 *     of the page to 10%). What was cut was explanation; what stayed is
 *     source, period and the caveats that make the numbers readable. The FX
 *     chart's method note lost the paragraph explaining how "Q4 2026" becomes
 *     an x coordinate -- that is written on each point's own tooltip, where
 *     the reader who needs it is already looking.
 *
 * The bylines are still NOT negotiable for fold space. If you find yourself
 * trading one for a row of a table, that is the trade you are making.
 *
 * WHAT THIS PAGE REFUSES TO SHOW
 * ------------------------------
 * Several obvious executive-dashboard components are deliberately absent
 * because the data behind them does not exist here:
 *
 * * a composite 0-100 "aviation health score" -- it would blend a 15-minute FX
 *   reading with a twice-yearly IATA series under weights nobody can cite. See
 *   cockpit_signals_service.py, and kokpit/sector-balance.tsx for what is
 *   shown instead: ONE derived relationship -- the unit margin RASK-CASK,
 *   which is the only one of the four originally drawn here that says
 *   something no other cell on the page already says -- with the years it was
 *   computed from printed under it;
 * * competitor capacity / load factor / market share / price pressure -- every
 *   competitive number on this page is a count of news and campaigns, and the
 *   Rekabet caption says so rather than relying on one line a reader may skip;
 * * a REGIONAL IATA selector -- `iata_indicators.region` is NULL on all eight
 *   rows, so the selector would offer five choices that all return nothing. An
 *   empty selector reads as a broken product, not as absent data;
 * * live pairs the owner did not ask for -- GBP/USD and EUR/GBP are still
 *   recorded, still have their own /kpi detail pages, and are simply not on
 *   the executive board. On the running page GBP/USD was a row of dashes end
 *   to end under a 9px divider that measured 2,39:1 in the light theme;
 * * a threshold band on the three ANNUAL pulse cells -- nobody publishes a
 *   threshold for an IATA yearly series, and one invented here would be the
 *   composite score this page refuses two bullets above. The two live cells
 *   carry the bands `/kokpit/signals` actually computes;
 * * a "1M" column in the FX table -- the curated forecasts carry 3- and
 *   12-month horizons and nothing shorter, and filling a 1M column would mean
 *   interpolating between two institutions' horizons, which is precisely what
 *   curated_seed.py refuses to do. The column is TAHMİN and prints each
 *   institution's own wording;
 * * a YÖN (direction) column on the signal board -- a rival's route
 *   announcement has no direction, `SignalOut` has no such field, and deriving
 *   one from a headline would invent the row's most decision-relevant claim.
 *   The column is TÜR;
 * * macro panels, monthly commercial data, an energy risk matrix, forecast
 *   confidence percentages, a header "data health %" -- none of these are
 *   measured or ingested anywhere in this system.
 *
 * The commercial figures ARE real, but they are IATA's GLOBAL INDUSTRY annual
 * series 2019-2026: not this airline's, not monthly, and not a budget. That
 * caveat is printed under the section headings, next to the numbers, never
 * tucked into a tooltip.
 */
export default async function KokpitPage() {
  // Independent server fetches. `Promise.all` because they are independent:
  // serially, a cold render paid one round trip per section end to end.
  //
  // `/kokpit/energy` is here even though no "Yakıt & Enerji" section survives:
  // Market Pulse's Brent cell needs the day AND week windows plus a sparkline,
  // and `/kpis` carries only a "vs previous measurement" delta. `/kokpit/pulse`
  // is deliberately NOT fetched -- this page prints no generated prose.
  const [board, energy, signalsOut, annual, forecasts, indicators] = await Promise.all([
    load<KokpitFxBoardOut>("/kokpit/fx", LIVE),
    load<EnergyBoardOut>("/kokpit/energy", LIVE),
    load<CockpitSignalsOut>("/kokpit/signals", LIVE),
    load<AnnualSeriesBoardOut>("/kokpit/annual-series", CURATED),
    load<FxForecastOut[]>("/kokpit/fx-forecasts", CURATED),
    load<IataIndicatorOut[]>("/kokpit/iata?kind=forecast", CURATED),
  ]);

  // The names below are what the ServerSourceError lines print. They are the
  // reader's words for the source, not the endpoint path: "/kokpit/energy"
  // tells an RM analyst nothing about which cell went missing.
  const FX = ["Kur panosu", board] as const;
  const ENERGY = ["Enerji panosu", energy] as const;
  const SIGNALS = ["Kokpit sinyalleri", signalsOut] as const;
  const ANNUAL = ["IATA yıllık serisi", annual] as const;
  const FORECASTS = ["Kurum kur tahminleri", forecasts] as const;
  const INDICATORS = ["IATA göstergeleri", indicators] as const;

  const signals = signalsOut.data?.signals ?? [];
  const annualSeries = annual.data?.series ?? [];

  return (
    // 1680 rather than full width: at 2560 a twelve-column row stretches past
    // what an eye scans in one pass. 20px between sections -- 32 spent 256px
    // of a 900px screen on nothing, 16 erased the section boundary.
    <div className="mx-auto flex max-w-[1680px] flex-col gap-5">
      {/* 1 --------------------------------------------------------------- */}
      {/* The header's "Canlı" badge is earned from the board's own oldest
          reading, and with no board it does not merely fall silent: it prints
          an amber "Veri yok" in the top right corner of the product's first
          screen. That sentence is fine over an empty board and false over a
          dead endpoint, so the flag goes with the data -- `unavailable` turns
          it into "Kur panosu okunamadı".

          It still gets no ServerSourceError line of its own: Market Pulse's
          line, twenty pixels below and naming the same "Kur panosu", already
          offers the retry, and two identical warnings that close together
          stop being read as one. */}
      <CockpitHeader board={board.data} unavailable={board.failed} />

      {/* 2 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Market Pulse"
          // The IATA edition comes from the payload, never from a literal in
          // this file: `scope_tr` is built server-side off the seed's own
          // publication date, so seeding a newer report moves this line, the
          // cell badges and the chart's dashed tail together. A hard-coded
          // "Haziran 2026" here would go on claiming the old edition after
          // every one of them had moved.
          caption={`Sol üç hücre: ${
            annual.data?.scope_tr ?? "IATA Küresel Görünüm · sektör geneli · yıllık"
          }. Sağ iki hücre: Yahoo, ~15 dk. Yakıt küresel Brent’tir, şirket yakıt maliyeti değildir.`}
          glowVar="var(--signal)"
        />
        {/* Five cells over four sources. Losing one source costs the cells it
            feeds and no others -- but a cell that is simply absent from the
            row is read as "there is no such measurement", so the line above
            names what went missing. All four gone means no cells at all, and
            an empty five-cell row would be the loudest lie on the page. */}
        <ServerSourceError sources={missing([ANNUAL, FX, ENERGY, SIGNALS])} />
        {(annual.data || board.data || energy.data || signalsOut.data) && (
          <MarketPulseRow
            annual={annual.data}
            board={board.data}
            energy={energy.data}
            signals={signals}
          />
        )}
      </section>

      {/* 3 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Genel KPI"
          caption={`${
            annual.data?.scope_tr ?? "IATA Küresel Görünüm · sektör geneli · yıllık"
          } · TK verisi değil. Tek bileşik sağlık skoru üretilmez.`}
          glowVar="var(--chart-2)"
          action={
            annual.data ? { href: annual.data.source_url, label: "IATA kaynağı" } : undefined
          }
        />
        <ServerSourceError sources={missing([ANNUAL])} />
        {/* Six cells in ONE strip, where this was a five-cell strip plus a
            four-column "Sektör Dengesi" panel. Three of that panel's four rows
            were arithmetic on two numbers already printed within two hundred
            pixels of it (see sector-balance.tsx); the fourth, the unit margin,
            is the one figure the page cannot state anywhere else, so it became
            the sixth cell. The section fell from 287px to ~130px. */}
        {/* `unavailable` is the whole point of the flag reaching this far: an
            empty strip says "IATA serisi henüz yüklenmedi" and an unread one
            must not, because nothing is going to load. Same for the margin
            cell, which otherwise blames RASK and CASK for having no common
            year when the truth is that neither series was read. */}
        <KpiStrip
          series={annualSeries}
          unavailable={annual.failed}
          trailing={<SectorBalance annual={annual.data} unavailable={annual.failed} />}
        />
      </section>

      {/* 4 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Günün Özeti"
          caption="Eşiği aşan sürücüler; bileşik skor değil. Kur ve yakıt bantları kendi Market Pulse hücrelerinde. Sayı, eşik ve yöntem karonun üzerine gelince görünür."
          glowVar="var(--chart-4)"
        />
        {/* DailySummary's own empty state ("eşiği aşan sürücü yok") is a
            measurement: the service ran and nothing crossed a threshold. It
            must never stand in for a request that did not return, so with the
            source unread the tile is replaced by the line saying so. */}
        {signalsOut.failed ? (
          <ServerSourceError sources={missing([SIGNALS])} />
        ) : (
          <DailySummary signals={signals} />
        )}
      </section>

      {/* 5 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        {/* "Canlı spot", the caption used to open -- a static sentence two
            lines above a footnote reading "~15 dk gecikmeli", over rows that
            can be hours behind when a cron run fails. A caption states what the
            column IS; whether a given row is current is a per-row claim, and it
            is now made on the row (see FxRow.delayLabel). */}
        <SectionHeader
          title="Kur / FX"
          caption="Spot kur ve kurumların kendi tahminleri; asla ortalanmaz. Bir satır seçince sağdaki grafik o pariteye geçer."
          glowVar="var(--primary)"
        />
        {/* The TAHMİN column is the forecasts source; the rows are the board.
            An unread forecast set leaves every TAHMİN cell empty, which on a
            table whose whole right half is forecasts reads as "no institution
            has published one" -- so it is named above rather than inferred
            from the blanks. */}
        <ServerSourceError sources={missing([FX, FORECASTS])} />
        {board.data && <FxBoardTable board={board.data} forecasts={forecasts.data ?? []} />}
      </section>

      {/* 6 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="IATA Görünümü"
          caption={`Kaynak: ${
            annual.data?.scope_tr ?? "IATA Küresel Görünüm · sektör geneli · yıllık"
          } · bölgesel kırılım yok.`}
          glowVar="var(--chart-2)"
          action={
            annual.data ? { href: annual.data.source_url, label: "IATA kaynağı" } : undefined
          }
        />
        <ServerSourceError sources={missing([ANNUAL, INDICATORS])} />
        {/* Both flags, for the same reason `KpiStrip` and `SectorBalance` take
            theirs one section up. This section reads two sources and either
            can fail alone: an unread series left the panel printing "IATA
            gelir serisi yüklenmedi" and unread indicators left it printing
            "Kâr göstergeleri henüz seed edilmedi" -- two confident statements
            about the DATABASE, manufactured from an HTTP failure, sitting
            directly under the line above saying the source was not read. */}
        {(annual.data || indicators.data) && (
          <IataOutlook
            series={annualSeries}
            seriesUnavailable={annual.failed}
            indicators={indicators.data ?? []}
            indicatorsUnavailable={indicators.failed}
          />
        )}
      </section>

      {/* 7 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Rekabet / Piyasa Görünümü"
          caption="Her sayı bir haber/kampanya HACMİDİR — rakip kapasitesi, doluluğu, pazar payı ve fiyat baskısı verisi bu sistemde yoktur."
          glowVar="var(--chart-3)"
        />
        <CompetitivePulse />
      </section>

      {/* 8 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Sinyal Panosu"
          caption="Rakip olayları ve stratejik gelişmeler; diğer beş akış kendi bölümlerinde."
          glowVar="var(--chart-4)"
          action={{ href: "/sinyaller", label: "Tümü (7 akış)" }}
        />
        <SignalStream />
      </section>

      {/* 9 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Alert Merkezi"
          caption="Kampanya uyarıları ve yüksek şiddetli riskler, öncelik sırasıyla. Sıfır bir ölçümdür; akış okunamazsa sayaç yerine bunu söyler."
          glowVar="var(--critical)"
        />
        <AlertCenter />
      </section>
    </div>
  );
}
