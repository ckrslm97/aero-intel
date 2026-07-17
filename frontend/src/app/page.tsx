import { KpiCard } from "@/components/kpi-card";
import { apiFetch } from "@/lib/api";
import type { KpiOut } from "@/lib/types";

const REVENUE_MANAGEMENT_KEYS = new Set([
  "total_aviation_revenue_ytd",
  "passenger_revenue_ytd",
  "ancillary_revenue_ytd",
  "rask",
  "cask",
  "yield_per_rpk",
  "ask",
  "rpk",
]);

function KpiGrid({ kpis }: { kpis: KpiOut[] }) {
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {kpis.map((kpi) => (
        <KpiCard
          key={kpi.metric_key}
          metricKey={kpi.metric_key}
          label={kpi.label}
          value={kpi.value}
          unit={kpi.unit || undefined}
          deltaPct={kpi.delta_pct ?? undefined}
          upIsGood={kpi.up_is_good}
          trend={kpi.trend}
          isEstimate={kpi.is_estimate}
        />
      ))}
    </section>
  );
}

export default async function DashboardPage() {
  let kpis: KpiOut[] = [];
  let error: string | null = null;

  try {
    kpis = await apiFetch<KpiOut[]>("/kpis");
  } catch {
    error = "KPI API'sine ulaşılamadı. Sunucu çalışıyor mu?";
  }

  const asOf = new Date().toLocaleString("tr-TR", {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
  });

  const operationalKpis = kpis.filter((k) => !REVENUE_MANAGEMENT_KEYS.has(k.metric_key));
  const revenueManagementKpis = kpis.filter((k) => REVENUE_MANAGEMENT_KEYS.has(k.metric_key));

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Havacılık Kontrol Paneli
        </h1>
        <p className="text-sm text-muted-foreground">
          Dünya genelinde operasyonel ve piyasa KPI&apos;ları · {asOf} UTC itibarıyla
        </p>
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

      {operationalKpis.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Operasyonel
          </h2>
          <KpiGrid kpis={operationalKpis} />
        </div>
      )}

      {revenueManagementKpis.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Gelir Yönetimi
          </h2>
          <KpiGrid kpis={revenueManagementKpis} />
        </div>
      )}
    </div>
  );
}
