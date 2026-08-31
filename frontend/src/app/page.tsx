import { AlertCenter } from "@/components/kokpit/alert-center";
// Lazily loaded, so echarts stays out of the landing page's initial bundle --
// see the note in that file for why the boundary is a module of its own.
import { AnnualTrendChart } from "@/components/kokpit/annual-trend-chart-lazy";
import { AviationFeed } from "@/components/kokpit/aviation-feed";
import { CockpitHeader } from "@/components/kokpit/cockpit-header";
import { CompetitivePulse } from "@/components/kokpit/competitive-pulse";
import { FuelEnergy } from "@/components/kokpit/fuel-energy";
import { FxForecastTable } from "@/components/kokpit/fx-forecast-table";
import { KpiStrip } from "@/components/kokpit/kpi-strip";
import { MarketStrip } from "@/components/kokpit/market-strip";
import { SectionHeader } from "@/components/kokpit/section-header";
import { SignalBoard } from "@/components/kokpit/signal-board";
import { TodaysIntelligence } from "@/components/kokpit/todays-intelligence";
import { apiFetch } from "@/lib/api";
import type {
  AnnualSeriesBoardOut,
  CockpitSignalsOut,
  EnergyBoardOut,
  KokpitFxBoardOut,
} from "@/lib/types";

/** ISR: KPIs and FX move at most every 15 minutes, so a 60s revalidation
 * serves the page instantly and still stays current. */
const LIVE = { cache: "force-cache", next: { revalidate: 60 } } as const;
/** The IATA series and the curated indicators change when a person edits a
 * seed file, not between requests. */
const CURATED = { cache: "force-cache", next: { revalidate: 3600 } } as const;

/** Fetch or fall back to `empty`. Kokpit is eleven sections over eight
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
 * The page has to answer four questions in about five seconds: durum ne, risk
 * var mı, ne değişiyor, neye dikkat. The order below is that answer, and the
 * top three sections (header, market strip, signal board + alerts) are sized
 * to sit inside a 1440x900 fold together.
 *
 * WHAT THIS PAGE REFUSES TO SHOW
 * ------------------------------
 * Several obvious executive-dashboard components are deliberately absent
 * because the data behind them does not exist here:
 *
 * * a composite 0-100 "health score" -- see cockpit_signals_service.py;
 * * a macro impact matrix, GDP/inflation/rate panels, regional IATA splits,
 *   monthly commercial data -- none of these are ingested at all;
 * * an energy "risk matrix" (Oil Supply: High, Refining: Medium, ...) -- this
 *   system ingests price series, not supply balances or a geopolitical index;
 *   the Yakıt & Enerji panel fills that space with arithmetic over real closes
 *   instead (see energy_service.py);
 * * an event-linkage graph under the aviation feed -- there is no
 *   article-to-article event relationship data here, and edges drawn from
 *   headline similarity would be invented ones;
 * * forecast confidence percentages -- the curated forecast rows carry no
 *   confidence field, and inventing one would defeat the point of curating;
 *   the forecast chart's shaded band is a MIN-MAX SPREAD, and its median line
 *   only appears where three institutions share one target date;
 * * competitor capacity / load factor / market share -- every competitive
 *   number on this page is a count of news and campaigns, and each panel says
 *   so in its own caption rather than relying on one line a reader may skip;
 * * a "data health %" figure in the header -- there is no such measurement.
 *
 * The commercial figures ARE real, but they are IATA's GLOBAL INDUSTRY annual
 * series 2019-2026, not this airline's and not monthly. That caveat is printed
 * under the section heading, next to the numbers, not tucked into a tooltip.
 */
export default async function KokpitPage() {
  // Independent server fetches. `Promise.all` because they are independent:
  // serially, a cold render paid one round trip per section end to end.
  //
  // `/kpis` is no longer among them. The market strip used to read Brent and
  // jet fuel out of that list, which carries only a "vs previous measurement"
  // delta -- so the strip could show a day delta for FX and nothing comparable
  // for energy. `/kokpit/energy` computes both from the contracts' own daily
  // closes, which is what lets every cell in the strip print the same two
  // windows.
  const [board, energy, signalsOut, annual] = await Promise.all([
    load<KokpitFxBoardOut | null>("/kokpit/fx", LIVE, null),
    load<EnergyBoardOut | null>("/kokpit/energy", LIVE, null),
    load<CockpitSignalsOut | null>("/kokpit/signals", LIVE, null),
    load<AnnualSeriesBoardOut | null>("/kokpit/annual-series", CURATED, null),
  ]);

  const signals = signalsOut?.signals ?? [];
  const fuelSignal = signals.find((signal) => signal.key === "fuel") ?? null;
  const annualSeries = annual?.series ?? [];

  return (
    <div className="flex flex-col gap-8">
      <CockpitHeader board={board} />

      {/* One row, every live market number. Replaces both the old six-cell
          strip and the full-width "Döviz Kuru Kokpiti" board that used to sit
          three sections below it printing the same USD/TRY a second time. */}
      <MarketStrip board={board} energy={energy} />

      {/* Durum + risk, side by side: the two things a reader looks at first,
          and the reason the old hero block had to shrink to a single band. */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[3fr_2fr]">
        <section className="flex flex-col gap-3">
          <SectionHeader
            title="Sinyal Panosu"
            caption="Dört ayrı sürücü, dört açık eşik — tek bir bileşik skor değil. Her karonun ⓘ notu, seviyeyi hangi kuralın verdiğini söyler."
            glowVar="var(--signal)"
          />
          <SignalBoard signals={signals} />
        </section>

        <section className="flex flex-col gap-3">
          <SectionHeader
            title="Alert Merkezi"
            caption="Kampanya uyarıları ve yüksek şiddetli risk sinyalleri, öncelik sırasıyla."
            glowVar="var(--critical)"
          />
          <AlertCenter />
        </section>
      </div>

      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Bugünün İstihbaratı"
          caption="Önce bakılan: sinyal seviyeleri, duygu dağılımı ve en önemli üç gelişme. Yapay zekâ/kural tabanlı metinler (Market Pulse ve Günün Özeti) “Detayı gör” altında, üreteni etiketli olarak duruyor."
          glowVar="var(--chart-4)"
        />
        <TodaysIntelligence signals={signals} />
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader
          title="IATA Sektör Görünümü"
          caption={
            annual
              ? `${annual.scope_tr} · şirket verisi değil, aylık veri değil`
              : "IATA Küresel Görünüm · sektör geneli · yıllık"
          }
          glowVar="var(--chart-2)"
          action={annual ? { href: annual.source_url, label: "IATA kaynağı" } : undefined}
        />
        <KpiStrip series={annualSeries} />
        {annualSeries.length > 0 && (
          <div
            style={{ "--glow-color": "var(--chart-2)" } as React.CSSProperties}
            className="rounded-xl border-gradient p-4 shadow-elev-1"
          >
            <AnnualTrendChart series={annualSeries} />
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[3fr_2fr]">
        <section className="flex flex-col gap-3">
          <SectionHeader
            title="Kur Tahminleri"
            caption="Küratörlü banka tahminleri. Tahminler asla ortalanmaz: her satır bir kurumun kendi rakamıdır. Canlı pariteler sayfanın en üstündeki piyasa şeridinde."
            glowVar="var(--primary)"
          />
          <FxForecastTable />
        </section>

        <section className="flex flex-col gap-3">
          <SectionHeader
            title="Yakıt & Enerji"
            caption="Brent, WTI ve doğal gazın gerçek kapanışları; jet yakıtı bunun üzerinden türetilen bir tahmindir. Yüzdeler her kontratın kendi serisinden hesaplanır."
            glowVar="var(--chart-5)"
          />
          <FuelEnergy signal={fuelSignal} />
        </section>
      </div>

      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Rekabet Nabzı"
          caption="Buradaki her sayı bir haber/kampanya hacmidir. Rakip kapasitesi, doluluğu veya pazar payı verisi bu sistemde yoktur."
          glowVar="var(--chart-3)"
        />
        <CompetitivePulse />
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Havacılık Akışı"
          caption="Son günlerin eşiği geçen, Türkçeye çevrilmiş haberleri."
          glowVar="var(--category-general)"
          action={{ href: "/newspaper", label: "Gazete'ye git" }}
        />
        <AviationFeed />
      </section>
    </div>
  );
}
