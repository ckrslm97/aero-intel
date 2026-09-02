"use client";

import { Megaphone, Route, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Delta } from "@/components/ui/delta";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import type { InsightsOut, NetworkSignalGroup, PromotionNewCountOut } from "@/lib/types";

const REGION_NAME = new Map<string, string>(
  worldRegions.map((region) => [region.slug, region.name]),
);

function Cell({
  icon: Icon,
  title,
  href,
  children,
}: {
  icon: typeof Megaphone;
  title: string;
  href: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-[68px] flex-col gap-1 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex items-center gap-1.5">
        <Icon className="size-3 shrink-0 text-muted-foreground" aria-hidden />
        <h3 className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        <Link
          href={href}
          className="shrink-0 rounded text-[10px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          →
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </div>
  );
}

/**
 * REKABET / PİYASA GÖRÜNÜMÜ -- three counts, one row, 68px.
 *
 * EVERY NUMBER IN THIS SECTION IS A COUNT OF NEWS AND CAMPAIGNS. This system
 * carries no rival capacity, load factor, market share, yield or price-pressure
 * data of any kind -- not in a model, not in a column, not behind an endpoint.
 * The owner's example dashboard showed "COMPETITOR CAPACITY +5,2% / MARKET LF
 * 82,1% / PRICE PRESSURE MEDIUM"; none of those three numbers can be produced
 * here, and producing something that looked like them would be a fabrication
 * dressed as a KPI. The section caption says so in the reader's own language,
 * above these cells, and it is not removable.
 *
 * The 48-hour campaign count stays here (rather than moving to Günün Özeti)
 * precisely because the Günün Özeti tiles print no numbers at all -- so this
 * is the only place on the page the figure appears, and no duplication is
 * created by keeping it.
 */
export function CompetitivePulse() {
  const newCountFetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<PromotionNewCountOut>("/promotions/new-count", { cache: "default", signal }),
    [],
  );
  const insightsFetcher = useCallback(
    (signal: AbortSignal) => apiFetch<InsightsOut>("/insights", { cache: "default", signal }),
    [],
  );
  const routesFetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<NetworkSignalGroup[]>("/hubs/network-signals?days=30", {
        cache: "default",
        signal,
      }),
    [],
  );

  const newCount = useDataSource(newCountFetcher, []);
  const insights = useDataSource(insightsFetcher, []);
  const routes = useDataSource(routesFetcher, []);

  const movers = (insights.data?.airline_momentum ?? [])
    .filter((mover) => mover.delta !== 0)
    .slice(0, 3);
  const routeGroups = routes.data ?? [];
  const routeTotal = routeGroups.reduce((sum, group) => sum + group.count, 0);
  const firstRoute = routeGroups.find((group) => group.articles.length > 0);

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <Cell icon={Megaphone} title="48 saatte kampanya" href="/kampanyalar">
        {!newCount.loaded ? (
          <Skeleton className="h-6 w-full rounded" />
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xl font-semibold leading-none tabular-nums">
              {newCount.data?.count ?? 0}
            </span>
            <div className="flex min-w-0 flex-wrap gap-1">
              {(newCount.data?.airline_codes ?? []).slice(0, 4).map((code) => (
                <span
                  key={code}
                  className="flex items-center gap-0.5 rounded-full border border-border px-1 text-[9px]"
                >
                  <AirlineLogo code={code} className="size-2.5" />
                  {code}
                </span>
              ))}
              {(newCount.data?.airline_codes ?? []).length === 0 && (
                <span className="text-[10px] text-muted-foreground">
                  Son 48 saatte yeni kampanya yok.
                </span>
              )}
            </div>
          </div>
        )}
      </Cell>

      <Cell icon={TrendingUp} title="Haber momentumu (7g vs 7g)" href="/biz">
        {!insights.loaded ? (
          <Skeleton className="h-6 w-full rounded" />
        ) : movers.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">Momentum verisi yok.</p>
        ) : (
          <ul className="flex flex-wrap gap-x-3 gap-y-0.5">
            {movers.map((mover) => (
              <li key={mover.code} className="flex items-center gap-1 text-[11px]">
                <AirlineLogo code={mover.code} className="size-3 shrink-0" />
                <span className="font-medium">{mover.code}</span>
                {/* Neutral: more press coverage is not "good". It is more
                    press coverage. */}
                <Delta pct={mover.delta} tone="neutral" valueLabel={`${mover.previous}→${mover.current}`} />
              </li>
            ))}
          </ul>
        )}
      </Cell>

      <Cell icon={Route} title="Yeni rota sinyali (30g)" href="/hublar">
        {!routes.loaded ? (
          <Skeleton className="h-6 w-full rounded" />
        ) : !firstRoute ? (
          <p className="text-[10px] text-muted-foreground">Yeni rota sinyali yok.</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] tabular-nums">
              <b>{routeTotal}</b> · {REGION_NAME.get(firstRoute.region ?? "") ?? "Diğer"}
            </span>
            <a
              href={firstRoute.articles[0].url}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate rounded text-[10px] text-muted-foreground hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {firstRoute.articles[0].headline}
            </a>
          </div>
        )}
      </Cell>
    </div>
  );
}
