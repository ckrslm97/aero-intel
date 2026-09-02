"use client";

import { ChevronDown, Clock, RotateCw, TriangleAlert, type LucideIcon } from "lucide-react";
import { CircleAlert, Info } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { Collapse } from "@/components/ui/collapse";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { formatRelativeTr } from "@/lib/format";
import type { CampaignAlert, RiskRadarOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALERT_LIMIT = 12;
const RISK_LIMIT = 4;
/** Three, down from ten. The section sits at the very bottom of the page and
 * opens closed; a reader who expands it wants the top of the list, and the
 * full list is one click away on /kampanyalar and /risk-radari. */
const ROW_LIMIT = 3;

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
  source: "campaign" | "risk";
  href: string;
  /** True only for the newest CRITICAL, and only on first paint. */
  flash: boolean;
}

/**
 * ALERT MERKEZİ -- the page's last section, a 44px band that opens on demand.
 *
 * It was a full-height panel in the upper half of the page. The owner's order
 * puts alerts at the BOTTOM, which is right: an alert centre near the top
 * competes for attention with the market state a reader came for, and on a
 * local database with no recent campaign alerts it competed while empty.
 *
 * The closed band still prints its counts, including zeroes. "0 KRİTİK · 0
 * YÜKSEK · 0 ORTA" is information -- it says the streams answered and had
 * nothing -- and it is a different statement from the section being absent,
 * which would say nothing at all. So the section never hides itself.
 *
 * THAT SENTENCE IS ONLY TRUE IF THE STREAMS ANSWERED, which is why this
 * component now reads `error` as well as `data`. It used to build its counts
 * out of `alerts.data ?? []` and `risks.data?.countries ?? []` and branch on
 * `loaded` alone -- and `useDataSource` sets `loaded` on a FAILED request too.
 * So a 500 from /campaign-alerts printed "0 KRİTİK · 0 YÜKSEK · 0 ORTA" under
 * a byline promising the reader that a zero here is a measurement. Three
 * zeroes is the most reassuring thing this page can say; it must never be what
 * a dead endpoint looks like.
 *
 * Both streams still degrade independently: whichever one answers is rendered,
 * and the band names the one that did not.
 */
export function AlertCenter() {
  const [open, setOpen] = useState(false);

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

  const merged = useMemo<AlertRow[]>(() => {
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

    // Risk items have a SEVERITY, not a priority. Only `high` ones are lifted
    // in, and they map to HIGH rather than CRITICAL: inventing a CRITICAL for
    // them would push the campaign alerts a revenue desk actually owns off the
    // top of the list.
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

    const rows = [...campaignRows, ...riskRows].sort((a, b) => {
      const byPriority = PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority);
      if (byPriority !== 0) return byPriority;
      return (b.createdAt ?? "").localeCompare(a.createdAt ?? "");
    });

    // Exactly one row may flash, exactly once: the top CRITICAL on first
    // paint. `animate-pulse-once` does not loop and is off under reduced
    // motion; a list where several rows pulsed would be a notification tray,
    // which this is not.
    const firstCritical = rows.findIndex((row) => row.priority === "CRITICAL");
    if (firstCritical !== -1) rows[firstCritical].flash = true;
    return rows;
  }, [alerts.data, risks.data]);

  /** Counted over EVERYTHING the two streams returned, not over the three rows
   * the open panel shows. A band that said "2 kritik" because it had truncated
   * to three rows would be a band nobody could reconcile with /kampanyalar. */
  const counts = useMemo(() => {
    const tally: Record<Priority, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, INFO: 0 };
    for (const row of merged) tally[row.priority] += 1;
    return tally;
  }, [merged]);

  const rows = merged.slice(0, ROW_LIMIT);
  const loading = !alerts.loaded || !risks.loaded;
  // "Down" is error AND no data: a failed refresh that still has an earlier
  // result keeps showing it (that is `stale`), and those counts are real.
  const alertsDown = alerts.error !== null && alerts.data === null;
  const risksDown = risks.error !== null && risks.data === null;
  const allDown = alertsDown && risksDown;
  const downLabel = alertsDown ? "kampanya uyarıları" : "risk sinyalleri";

  const retryDown = () => {
    if (alertsDown) alerts.retry();
    if (risksDown) risks.retry();
  };

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex h-7 flex-wrap items-center gap-x-3 gap-y-1">
        <TriangleAlert
          className={cn("size-3.5 shrink-0", counts.CRITICAL > 0 ? "text-critical" : "text-muted-foreground")}
          aria-hidden
        />
        {loading ? (
          <Skeleton className="h-3 w-40 rounded" />
        ) : allDown ? (
          <span className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            Uyarı kaynakları okunamadı — sayaç üretilemiyor.
            <button
              type="button"
              onClick={retryDown}
              className="flex items-center gap-1 rounded border border-border px-1.5 py-px text-[10px] font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <RotateCw className="size-2.5" aria-hidden />
              Yeniden dene
            </button>
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {(["CRITICAL", "HIGH", "MEDIUM"] as const).map((priority) => (
              <span
                key={priority}
                className={cn(
                  "flex items-center gap-1 text-[11px] tabular-nums",
                  counts[priority] > 0 ? PRIORITY_META[priority].text : "text-muted-foreground",
                )}
              >
                <span aria-hidden className={cn("size-1.5 rounded-full", PRIORITY_META[priority].dot)} />
                {counts[priority]} {PRIORITY_META[priority].label.toLocaleUpperCase("tr-TR")}
              </span>
            ))}
            {/* One stream answered and one did not. The counts below are real
                but PARTIAL, and a reader who is not told that will read them
                as the whole picture. */}
            {(alertsDown || risksDown) && (
              <span className="flex items-center gap-1.5 text-[10px] text-warning">
                Eksik: {downLabel}
                <button
                  type="button"
                  onClick={retryDown}
                  className="flex items-center gap-1 rounded border border-border px-1.5 py-px font-medium text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  <RotateCw className="size-2.5" aria-hidden />
                  Yeniden dene
                </button>
              </span>
            )}
          </span>
        )}

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          disabled={rows.length === 0}
          className="rounded border border-border px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-accent disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {open ? "Daralt" : "Genişlet"}
          <ChevronDown
            className={cn("ml-1 inline size-3 transition-transform", open && "rotate-180")}
            aria-hidden
          />
        </button>

        <span className="ml-auto flex gap-3 text-[10px]">
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

      <Collapse open={open && rows.length > 0}>
        <ul className="flex flex-col gap-0.5 pt-1">
          {rows.map((row) => {
            const meta = PRIORITY_META[row.priority];
            const Icon = meta.icon;
            return (
              <li key={row.id}>
                <Link
                  href={row.href}
                  style={{ "--glow-color": "var(--critical)" } as React.CSSProperties}
                  className={cn(
                    "flex h-7 items-center gap-2 rounded px-2 text-xs transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    row.flash && "edge-lit animate-pulse-once",
                  )}
                >
                  <Icon className={cn("size-3 shrink-0", meta.text)} aria-hidden />
                  <span className="sr-only">{meta.label} öncelikli:</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {row.title}
                  </span>
                  <span className="hidden shrink-0 text-[10px] text-muted-foreground lg:inline">
                    {row.kindLabel}
                  </span>
                  <span className="flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground">
                    <Clock className="size-2.5" aria-hidden />
                    {row.createdAt ? formatRelativeTr(row.createdAt) : "—"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </Collapse>
    </div>
  );
}
