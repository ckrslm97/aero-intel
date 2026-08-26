"use client";

import { ExternalLink } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import type { NetworkSignalGroup, RouteSignalArticle } from "@/lib/types";

// echarts only needed once the map renders -- Faz 14, same pattern as
// newspaper-browser.tsx's RegionMap.
const RouteSignalMap = dynamic(
  () => import("@/components/route-signal-map").then((m) => m.RouteSignalMap),
  { ssr: false, loading: () => <Skeleton className="h-[320px] w-full rounded-xl" /> },
);

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

function formatSignalDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

/** New-route announcements, moved here from İçgörüler and now sourced from
 * pipeline-v2 events (see backend/app/services/network_signals_service.py)
 * -- one row per event rather than per article, so a story three outlets
 * ran doesn't count as three signals. */
export function HubNetworkSignals() {
  const [carrier, setCarrier] = useState<string | null>(null);
  const [city, setCity] = useState<string | null>(null);

  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<NetworkSignalGroup[]>("/hubs/network-signals?days=30", { cache: "default", signal }),
    [],
  );
  const { data: groups, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, []);

  const flatSignals: RouteSignalArticle[] = useMemo(
    () => (groups ?? []).flatMap((group) => group.articles),
    [groups],
  );

  if (!loaded) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-[320px] w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }

  if (error && !groups) {
    return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;
  }

  if (!groups) return null;

  if (groups.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        Son 30 günde yeni hat sinyali yok — uydurma yerine boş gösteriyoruz.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}
      <div className="overflow-hidden rounded-xl shadow-elev-1">
        <RouteSignalMap
          signals={flatSignals}
          carrier={carrier}
          onCarrierChange={setCarrier}
          city={city}
          onCityChange={setCity}
        />
      </div>

      <div className="flex flex-col gap-6">
        {groups.map((group) => (
          <section key={group.region ?? "other"} className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">
              {REGION_NAME[group.region ?? ""] ?? "Diğer"}{" "}
              <span className="font-normal text-muted-foreground">{group.count} sinyal</span>
            </h3>
            <MotionList className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {group.articles.map((signal) => (
                <MotionItem
                  key={signal.id}
                  variant="scalePop"
                  className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4"
                >
                  <a
                    href={signal.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-start gap-1.5 text-sm font-medium leading-relaxed hover:text-primary"
                  >
                    {signal.headline}
                    <ExternalLink className="mt-0.5 size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                  </a>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {signal.airlines.map((code) => (
                      <span key={code} className="flex items-center gap-1">
                        <AirlineLogo code={code} className="size-3.5" />
                        {code}
                      </span>
                    ))}
                    {signal.airports.map((airport) => (
                      <span key={airport.code}>{airport.city}</span>
                    ))}
                    <span>{signal.source_name}</span>
                    {formatSignalDate(signal.published_at) && (
                      <span>{formatSignalDate(signal.published_at)}</span>
                    )}
                  </div>
                </MotionItem>
              ))}
            </MotionList>
          </section>
        ))}
      </div>
      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}
