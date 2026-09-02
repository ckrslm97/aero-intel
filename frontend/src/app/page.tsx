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

/** Fetch or fall back to `empty`. Kokpit is nine sections over eleven
 * endpoints, and one of them being down must thin the page, never blank it --
 * the same per-source degradation contract `useDataSource` gives the client
 * components further down, applied to the server-rendered half. */
async function load<T>(path: string, init: RequestInit & { next?: { revalidate?: number } }, empty: T): Promise<T> {
  try {
    return await apiFetch<T>(path, init);
  } catch {
    return empty;
  }
}

/**
 * KOKPİT -- the executive landing page.
 *
 * "LESS BUT BETTER. READING THE DASHBOARD SHOULD NOT REQUIRE READING."
 *
 * The page answers one question in thirty seconds: what is the market doing,
 * how are the industry's numbers moving, which way is the lira going, what is
 * IATA expecting, and what should worry me. The section order below IS that
 * answer, and sections 1-5 are sized to fit a 1440x900 fold together.
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
 * THE FOLD CONTRACT (1440x900) -- MEASURED, not budgeted
 * ------------------------------------------------------
 * The app shell starts this page at y=96, leaving 804px of visible page.
 * These are the heights the sections ACTUALLY render at with live data, read
 * out of the browser rather than added up from the cell specs:
 *
 *   1 Header              52  (+20 gap) ->  72
 *   2 Market Pulse       178  (+20 gap) -> 270
 *   3 KPI + Denge        287  (+20 gap) -> 577
 *   4 Günün Özeti        129  (+20 gap) -> 726
 *   5 Kur / FX  (heading + byline visible)  -> 804 = fold
 *
 * So the fold carries: market state, the five KPIs, the sector balance, the
 * four signal tiles, and the FX section's heading. IATA's expectation is in
 * the fold too -- as the 2026T badge on the three annual pulse cells and the
 * year labels under the KPI dots.
 *
 * That satisfies the owner's contract ("market state + KPIs + which way the
 * lira is going + IATA's expectation + what should worry me, in thirty
 * seconds"): the lira's direction is the KUR pulse cell, at 26px, with its day
 * and week deltas. The FX TABLE is the drill-down, and it starts one short
 * scroll below.
 *
 * The earlier draft of this comment budgeted 120/124/88 for sections 2-4 and
 * concluded the first nine FX rows would clear the fold. They do not, and the
 * difference is almost entirely the section bylines -- the source-and-period
 * captions under each heading. Those captions are the page's honesty
 * contract and are NOT negotiable for fold space; the FX rows are. If you
 * find yourself tempted to trade one for the other, that is the trade you
 * would be making.
 *
 * THIS SUPERSEDES the 92px cell arithmetic that used to be commented in
 * market-strip.tsx. If you are about to make a cell taller, this is the
 * calculation you are spending.
 *
 * WHAT THIS PAGE REFUSES TO SHOW
 * ------------------------------
 * Several obvious executive-dashboard components are deliberately absent
 * because the data behind them does not exist here:
 *
 * * a composite 0-100 "aviation health score" -- it would blend a 15-minute FX
 *   reading with a twice-yearly IATA series under weights nobody can cite. See
 *   cockpit_signals_service.py, and kokpit/sector-balance.tsx for what is
 *   shown instead: four DERIVED relationships, each with its own source and
 *   period printed under it;
 * * competitor capacity / load factor / market share / price pressure -- every
 *   competitive number on this page is a count of news and campaigns, and the
 *   Rekabet caption says so rather than relying on one line a reader may skip;
 * * a REGIONAL IATA selector -- `iata_indicators.region` is NULL on all eight
 *   rows, so the selector would offer five choices that all return nothing. An
 *   empty selector reads as a broken product, not as absent data;
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
    load<KokpitFxBoardOut | null>("/kokpit/fx", LIVE, null),
    load<EnergyBoardOut | null>("/kokpit/energy", LIVE, null),
    load<CockpitSignalsOut | null>("/kokpit/signals", LIVE, null),
    load<AnnualSeriesBoardOut | null>("/kokpit/annual-series", CURATED, null),
    load<FxForecastOut[]>("/kokpit/fx-forecasts", CURATED, []),
    load<IataIndicatorOut[]>("/kokpit/iata?kind=forecast", CURATED, []),
  ]);

  const signals = signalsOut?.signals ?? [];
  const annualSeries = annual?.series ?? [];

  return (
    // 1680 rather than full width: at 2560 a twelve-column row stretches past
    // what an eye scans in one pass. 20px between sections -- 32 spent 256px
    // of a 900px screen on nothing, 16 erased the section boundary.
    <div className="mx-auto flex max-w-[1680px] flex-col gap-5">
      {/* 1 --------------------------------------------------------------- */}
      <CockpitHeader board={board} />

      {/* 2 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Market Pulse"
          caption="IATA Küresel Görünüm (Haziran 2026) · yıllık · sektör geneli — canlı seriler Yahoo Finance, ~15 dk gecikmeli. Soldaki üç hücre yılda iki kez, sağdaki iki hücre 15 dakikada bir güncellenir. “MARKET” hücresi için rakip kapasite/pazar payı verisi bu sistemde yoktur; slot, havacılığın canlı fiyatlanan tek maliyet kalemine verilmiştir."
          glowVar="var(--signal)"
        />
        <MarketPulseRow annual={annual} board={board} energy={energy} />
      </section>

      {/* 3 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Genel KPI"
          caption={
            annual
              ? `${annual.scope_tr} · TK verisi değil, aylık veri değil.`
              : "IATA Küresel Görünüm · sektör geneli · yıllık · TK verisi değil, aylık veri değil."
          }
          glowVar="var(--chart-2)"
          action={annual ? { href: annual.source_url, label: "IATA kaynağı" } : undefined}
        />
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
          <div className="xl:col-span-8">
            <KpiStrip series={annualSeries} />
          </div>
          <div className="xl:col-span-4">
            <SectorBalance annual={annual} energy={energy} />
          </div>
        </div>
      </section>

      {/* 4 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Günün Özeti"
          caption="Dört ayrı sürücü, dört açık eşik — tek bir bileşik skor değil. Sayı ve yöntem her karonun ⓘ notunda."
          glowVar="var(--chart-4)"
        />
        <DailySummary signals={signals} />
      </section>

      {/* 5 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Kur / FX"
          caption="Canlı spot kurlar ve kurumların kendi yayımladığı tahminler. Tahminler asla ortalanmaz: her satır bir kurumun kendi rakamıdır, kendi vadesiyle. Bir satıra tıklayınca sağdaki grafik o pariteye geçer."
          glowVar="var(--primary)"
        />
        <FxBoardTable board={board} forecasts={forecasts} />
      </section>

      {/* 6 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="IATA Görünümü"
          caption="Kaynak: IATA Küresel Görünüm · Haziran 2026 · sektör geneli · yıllık · bölgesel kırılım yok."
          glowVar="var(--chart-2)"
          action={annual ? { href: annual.source_url, label: "IATA kaynağı" } : undefined}
        />
        <IataOutlook series={annualSeries} indicators={indicators} />
      </section>

      {/* 7 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Rekabet / Piyasa Görünümü"
          caption="Buradaki her sayı bir haber/kampanya HACMİDİR. Rakip kapasitesi, doluluğu, pazar payı veya fiyat baskısı verisi bu sistemde yoktur."
          glowVar="var(--chart-3)"
        />
        <CompetitivePulse />
      </section>

      {/* 8 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Sinyal Panosu"
          caption="Rakip olayları ve stratejik gelişmeler. Diğer beş akış bu sayfanın kendi bölümlerinde zaten görünüyor, burada tekrar edilmez."
          glowVar="var(--chart-4)"
          action={{ href: "/sinyaller", label: "Tümü (7 akış)" }}
        />
        <SignalStream />
      </section>

      {/* 9 --------------------------------------------------------------- */}
      <section className="flex flex-col gap-2">
        <SectionHeader
          title="Alert Merkezi"
          caption="Kampanya uyarıları ve yüksek şiddetli risk sinyalleri, öncelik sırasıyla. Sıfır sayısı da bir bilgidir: bölüm boşken de sayaçlarını basar."
          glowVar="var(--critical)"
        />
        <AlertCenter />
      </section>
    </div>
  );
}
