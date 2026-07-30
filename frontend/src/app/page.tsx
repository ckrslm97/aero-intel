import { KpiCard } from "@/components/kpi-card";
import { MarketTicker } from "@/components/market-ticker";
import { MotionItem, MotionList, MotionRail } from "@/components/motion/motion-list";
// Lazily loaded, so echarts stays out of the landing page's initial bundle --
// see the note in that file for why the boundary is a module of its own.
import { RevenueOverviewChart } from "@/components/revenue-overview-chart-lazy";
import { apiFetch } from "@/lib/api";
import {
  MARKET_KEYS,
  REVENUE_BAR_KEYS,
  REVENUE_MANAGEMENT_KEYS,
} from "@/lib/kpi-groups";
import type { KpiOut } from "@/lib/types";

function KpiGrid({ kpis }: { kpis: KpiOut[] }) {
  return (
    <MotionList className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
      {kpis.map((kpi) => (
        <MotionItem key={kpi.metric_key} variant="scalePop">
          <KpiCard
            metricKey={kpi.metric_key}
            label={kpi.label}
            value={kpi.value}
            unit={kpi.unit || undefined}
            deltaPct={kpi.delta_pct ?? undefined}
            upIsGood={kpi.up_is_good}
            trend={kpi.trend}
            isEstimate={kpi.is_estimate}
            lyDeltaPct={kpi.ly_delta_pct ?? undefined}
            lyComparisonLabel={kpi.comparison_label}
          />
        </MotionItem>
      ))}
    </MotionList>
  );
}

export default async function DashboardPage() {
  let kpis: KpiOut[] = [];
  let error: string | null = null;

  try {
    // ISR: the dashboard was rendered on every request against a live,
    // uncached backend call. KPIs move at most every 15 minutes, so a 60s
    // revalidation serves the page instantly and still stays current.
    kpis = await apiFetch<KpiOut[]>("/kpis", {
      cache: "force-cache",
      next: { revalidate: 60 },
    });
  } catch {
    error = "KPI API'sine ulaşılamadı. Sunucu çalışıyor mu?";
  }

  const asOf = new Date().toLocaleString("tr-TR", {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
  });

  const marketKpis = kpis.filter((k) => MARKET_KEYS.has(k.metric_key));
  const revenueManagementKpis = kpis.filter((k) => REVENUE_MANAGEMENT_KEYS.has(k.metric_key));
  const operationalKpis = kpis.filter(
    (k) => !REVENUE_MANAGEMENT_KEYS.has(k.metric_key) && !MARKET_KEYS.has(k.metric_key),
  );

  // The two cards beside the chart deliberately are NOT the metrics the chart
  // already plots -- printing the same three revenue lines twice, side by
  // side, was the density problem this pass is trying to fix.
  const chartKeys = new Set<string>(REVENUE_BAR_KEYS);
  const chartCompanions = revenueManagementKpis.filter((k) => !chartKeys.has(k.metric_key));
  const remainingRevenueKpis = revenueManagementKpis.filter(
    (k) => !chartCompanions.slice(0, 2).some((c) => c.metric_key === k.metric_key),
  );

  return (
    <div className="flex flex-col gap-10">
      {/* The one structural hook this visual pass adds: a hero shell so the
          night-horizon mesh has something to sit behind. Layout inside is
          unchanged from the structural pass. */}
      <div className="relative overflow-hidden rounded-2xl bg-hero-mesh p-5 sm:p-6">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              Havacılık{" "}
              <span className="gradient-text">Kontrol Paneli</span>
            </h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Dünya genelinde operasyonel ve piyasa KPI&apos;ları · {asOf} UTC itibarıyla
            </p>
          </div>
          <MarketTicker items={marketKpis} />
        </div>
      </div>

      {error && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      )}

      {!error && kpis.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Henüz KPI kaydı yok. İlk ölçümü almak için{" "}
          <code className="rounded bg-muted px-1 py-0.5">make refresh-kpis</code>{" "}
          komutunu çalıştırın.
        </p>
      )}

      {/* Gelir Yönetimi leads: it is the portal's focus, and the chart carries
          the section rather than sitting under a wall of tiles. */}
      {revenueManagementKpis.length > 0 && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Gelir Yönetimi
            </h2>
            <MotionRail style={{ "--glow-color": "var(--signal)" } as React.CSSProperties} />
          </div>

          <MotionList className="grid grid-cols-1 gap-5 lg:grid-cols-4">
            <MotionItem className="lg:col-span-2">
              {/* No bg-card here on purpose: border-gradient paints the card
                  fill itself (padding-box) so the gradient border stays
                  visible -- a background-color would cover it. */}
              <div
                style={{ "--glow-color": "var(--signal)" } as React.CSSProperties}
                className="flex h-full flex-col gap-2 rounded-xl border-gradient p-5 shadow-elev-1"
              >
                <h3 className="text-sm font-semibold">
                  Gelir tabanı{" "}
                  <span className="font-normal text-muted-foreground">
                    (2026 vs 2025, yıllık değişim)
                  </span>
                </h3>
                <RevenueOverviewChart kpis={revenueManagementKpis} />
              </div>
            </MotionItem>
            {chartCompanions.slice(0, 2).map((kpi) => (
              <MotionItem key={kpi.metric_key} variant="scalePop">
                <KpiCard
                  metricKey={kpi.metric_key}
                  label={kpi.label}
                  value={kpi.value}
                  unit={kpi.unit || undefined}
                  deltaPct={kpi.delta_pct ?? undefined}
                  upIsGood={kpi.up_is_good}
                  trend={kpi.trend}
                  isEstimate={kpi.is_estimate}
                  lyDeltaPct={kpi.ly_delta_pct ?? undefined}
                  lyComparisonLabel={kpi.comparison_label}
                />
              </MotionItem>
            ))}
          </MotionList>

          {remainingRevenueKpis.length > 0 && <KpiGrid kpis={remainingRevenueKpis} />}
        </div>
      )}

      {operationalKpis.length > 0 && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Operasyonel
            </h2>
            <MotionRail style={{ "--glow-color": "var(--primary)" } as React.CSSProperties} />
          </div>
          <KpiGrid kpis={operationalKpis} />
        </div>
      )}
    </div>
  );
}
