"use client";

import { BellRing, Clock } from "lucide-react";
import { useCallback } from "react";

import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import { priorityToSeverity, severityMeta } from "@/lib/severity";
import type { CampaignAlert } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALERT_LIMIT = 10;

const TYPE_LABELS: Record<CampaignAlert["alert_type"], string> = {
  NEW: "Yeni kampanya",
  CHANGE: "Değişiklik",
  EXPIRING: "Bitmek üzere",
  EXPIRED: "Sona erdi",
  LOW_CONFIDENCE: "Düşük güven",
};

/** The campaign radar strip: what changed since the analyst last looked.
 *
 * Three ways this renders nothing at all, and all three are deliberate:
 * the endpoint is missing (it ships in its own PR, and a 404 must not put an
 * error box at the top of a working page), the request failed, or there is
 * simply nothing unacknowledged. An alert strip is an addition to this page,
 * never a precondition for it -- so it fails silent rather than loud, which is
 * the one place on the site where a swallowed error is the correct behaviour.
 *
 * The items are not interactive. An alert can reference a campaign outside the
 * timeline's eight-week window, and a click that sometimes opens a drawer and
 * sometimes does nothing is worse than a line of text that never promised to.
 */
export function CampaignAlertStrip({ limit = ALERT_LIMIT }: { limit?: number }) {
  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<CampaignAlert[]>(`/campaign-alerts?limit=${limit}`, {
        cache: "default",
        signal,
      }),
    [limit],
  );
  const { data, error } = useDataSource(fetcher, [limit]);

  if (error || !data || data.length === 0) return null;

  return (
    <section
      aria-label="Kampanya radarı"
      className="flex flex-col gap-2 rounded-xl border border-border bg-card bg-card-sheen p-3 shadow-elev-1"
    >
      <div className="flex items-center gap-2">
        <BellRing className="size-4 text-signal" />
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Kampanya radarı
        </h2>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {data.length} bekleyen uyarı
        </span>
      </div>

      <ul className="flex flex-col gap-1.5">
        {data.map((alert) => {
          // Priority is icon + word + colour, and the table it reads from is
          // the app's ONE severity ladder (lib/severity.ts) rather than the
          // fifth private copy that used to live at the top of this file.
          // `priorityToSeverity` is the single place that says which rung each
          // of the four alert priorities is. Only the top three rungs take a
          // hue: a strip where every item is coloured tells a reader nothing
          // about which one to read first.
          const meta = severityMeta(priorityToSeverity(alert.priority));
          const Icon = meta.icon;
          return (
            <li
              key={alert.id}
              className={cn(
                "flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2.5 py-1.5 text-xs",
                meta.pill,
              )}
            >
              <Icon className="size-3.5 shrink-0" aria-hidden />
              <span className="sr-only">{meta.label} öncelikli uyarı:</span>
              <span className="rounded-full bg-background/60 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide">
                {TYPE_LABELS[alert.alert_type] ?? alert.alert_type}
              </span>
              <span className="min-w-0 flex-1 font-medium text-foreground">
                {alert.title_tr}
              </span>
              <span className="flex items-center gap-1 text-[11px] tabular-nums text-muted-foreground">
                <Clock className="size-3" aria-hidden />
                {relativeTimeTr(alert.created_at)}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
