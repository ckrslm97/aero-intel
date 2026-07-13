import { KpiCard } from "@/components/kpi-card";
import { apiFetch } from "@/lib/api";
import type { KpiOut } from "@/lib/types";

export default async function DashboardPage() {
  let kpis: KpiOut[] = [];
  let error: string | null = null;

  try {
    kpis = await apiFetch<KpiOut[]>("/kpis");
  } catch {
    error = "Could not reach the KPI API. Is the backend running?";
  }

  const asOf = new Date().toLocaleString("en-GB", {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
  });

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Aviation Dashboard
        </h1>
        <p className="text-sm text-muted-foreground">
          Worldwide operational and market KPIs · as of {asOf} UTC
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      )}

      {!error && kpis.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          No KPIs recorded yet. Run{" "}
          <code className="rounded bg-muted px-1 py-0.5">make refresh-kpis</code> to
          pull the first observation.
        </p>
      )}

      {kpis.length > 0 && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((kpi) => (
            <KpiCard
              key={kpi.metric_key}
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
      )}
    </div>
  );
}
