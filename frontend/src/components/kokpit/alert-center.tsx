"use client";

import { CircleAlert, Clock, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import type { CampaignAlert, RiskRadarOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALERT_LIMIT = 12;
const RISK_LIMIT = 4;
const ROW_LIMIT = 10;

type Priority = "CRITICAL" | "HIGH" | "MEDIUM" | "INFO";

/** CRITICAL and HIGH are the only two that take a hue. A list where every row
 * is coloured tells a reader nothing about which one to read first -- the same
 * rule campaign-alert-strip.tsx set, kept here rather than re-decided. */
const PRIORITY_META: Record<Priority, { label: string; icon: LucideIcon; text: string; dot: string }> = {
  CRITICAL: { label: "Kritik", icon: TriangleAlert, text: "text-critical", dot: "bg-critical" },
  HIGH: { label: "Yüksek", icon: CircleAlert, text: "text-warning", dot: "bg-warning" },
  MEDIUM: { label: "Orta", icon: Info, text: "text-muted-foreground", dot: "bg-muted-foreground" },
  INFO: { label: "Bilgi", icon: Info, text: "text-muted-foreground", dot: "bg-muted-foreground" },
};

const PRIORITY_ORDER: Priority[] = ["CRITICAL", "HIGH", "MEDIUM", "INFO"];

const CAMPAIGN_TYPE_LABELS: Record<CampaignAlert["alert_type"], string> = {
  NEW: "Yeni kampanya",
  CHANGE: "Değişiklik",
  EXPIRING: "Bitmek üzere",
  EXPIRED: "Sona erdi",
  LOW_CONFIDENCE: "Düşük güven",
};

interface AlertRow {
  id: string;
  priority: Priority;
  title: string;
  kindLabel: string;
  createdAt: string | null;
  /** Which stream the row came from. Shown as a chip, because "TK Avrupa
   * kampanyası bitiyor" and "Etna'da kül bulutu" need different reflexes and
   * a merged list that hid the difference would be worse than two lists. */
  source: "campaign" | "risk";
  href: string;
  /** True only for the newest CRITICAL, and only on first paint. */
  flash: boolean;
}

/** "Alert Merkezi": the two real alert streams this system has, in one
 * priority-ordered list.
 *
 * Campaign alerts arrive pre-prioritised from the backend. Risk items do not
 * have a priority at all -- they have a severity -- so only `high` ones are
 * lifted in, mapped to HIGH rather than CRITICAL: a high-severity disaster
 * signal genuinely is one rung below "a rival's campaign expires today" in
 * terms of what a revenue desk must act on this morning, and inventing a
 * CRITICAL for it would push the campaign alerts the desk actually owns off
 * the top of the list.
 *
 * Both streams degrade independently: whichever one answers gets rendered.
 */
export function AlertCenter() {
  const alertsFetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<CampaignAlert[]>(`/campaign-alerts?limit=${ALERT_LIMIT}`, {
        cache: "default",
        signal,
      }),
    [],
  );
  const risksFetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<RiskRadarOut>("/risks?days=14", { cache: "default", signal }),
    [],
  );

  const alerts = useDataSource(alertsFetcher, []);
  const risks = useDataSource(risksFetcher, []);

  const rows = useMemo<AlertRow[]>(() => {
    const campaignRows: AlertRow[] = (alerts.data ?? []).map((alert) => ({
      id: `campaign-${alert.id}`,
      priority: alert.priority,
      title: alert.title_tr,
      kindLabel: CAMPAIGN_TYPE_LABELS[alert.alert_type] ?? alert.alert_type,
      createdAt: alert.created_at,
      source: "campaign",
      href: "/kampanyalar",
      flash: false,
    }));

    const riskRows: AlertRow[] = (risks.data?.countries ?? [])
      .flatMap((country) => country.items)
      .filter((item) => item.severity === "high")
      .slice(0, RISK_LIMIT)
      .map((item) => ({
        id: `risk-${item.id}`,
        priority: "HIGH" as const,
        title: item.headline,
        kindLabel: item.risk_type_label_tr,
        createdAt: item.published_at,
        source: "risk" as const,
        href: "/risk-radari",
        flash: false,
      }));

    const merged = [...campaignRows, ...riskRows].sort((a, b) => {
      const byPriority =
        PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority);
      if (byPriority !== 0) return byPriority;
      return (b.createdAt ?? "").localeCompare(a.createdAt ?? "");
    });

    // Exactly one row may flash, exactly once: the top CRITICAL on first
    // paint. `animate-pulse-once` does not loop and is off under reduced
    // motion; a list where several rows pulsed would be a notification tray,
    // which this is not.
    const firstCritical = merged.findIndex((row) => row.priority === "CRITICAL");
    if (firstCritical !== -1) merged[firstCritical].flash = true;

    return merged.slice(0, ROW_LIMIT);
  }, [alerts.data, risks.data]);

  const counts = useMemo(() => {
    const tally: Partial<Record<Priority, number>> = {};
    for (const row of rows) tally[row.priority] = (tally[row.priority] ?? 0) + 1;
    return tally;
  }, [rows]);

  const loading = !alerts.loaded || !risks.loaded;

  return (
    <div className="flex h-full flex-col gap-2 rounded-xl border border-border bg-card bg-card-sheen p-3 shadow-elev-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {rows.length} bekleyen
        </span>
        <span className="flex items-center gap-2">
          {PRIORITY_ORDER.filter((priority) => counts[priority]).map((priority) => (
            <span
              key={priority}
              className={cn("flex items-center gap-1 text-[11px] tabular-nums", PRIORITY_META[priority].text)}
            >
              <span aria-hidden className={cn("size-1.5 rounded-full", PRIORITY_META[priority].dot)} />
              {PRIORITY_META[priority].label} {counts[priority]}
            </span>
          ))}
        </span>
        <span className="ml-auto flex gap-3 text-[11px]">
          <Link
            href="/kampanyalar"
            className="rounded text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Kampanyalar →
          </Link>
          <Link
            href="/risk-radari"
            className="rounded text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Risk →
          </Link>
        </span>
      </div>

      {loading ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full rounded-lg" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Aktif uyarı yok.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((row) => {
            const meta = PRIORITY_META[row.priority];
            const Icon = meta.icon;
            return (
              <li key={row.id}>
                <Link
                  href={row.href}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    row.flash && "animate-pulse-once",
                  )}
                >
                  <Icon className={cn("size-3.5 shrink-0", meta.text)} aria-hidden />
                  <span className="sr-only">{meta.label} öncelikli:</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {row.title}
                  </span>
                  <span className="hidden shrink-0 rounded-full bg-muted px-1.5 py-px text-[10px] text-muted-foreground sm:inline">
                    {row.source === "campaign" ? "Kampanya" : "Risk"}
                  </span>
                  <span className="hidden shrink-0 text-[10px] text-muted-foreground lg:inline">
                    {row.kindLabel}
                  </span>
                  <span className="flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground">
                    <Clock className="size-2.5" aria-hidden />
                    {row.createdAt ? relativeTimeTr(row.createdAt) : "—"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
