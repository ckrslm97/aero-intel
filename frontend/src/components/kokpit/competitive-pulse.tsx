"use client";

import { ArrowDown, ArrowUp, Megaphone, Route, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { airlineTabs, worldRegions } from "@/lib/nav";
import type { InsightsOut, NetworkSignalGroup, PromotionNewCountOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// Keyed by plain string: the codes arriving from the API are strings, and
// narrowing them to CarrierCode at every lookup would be a cast asserting
// something the response cannot guarantee.
const BRAND_COLOR = new Map<string, string>(
  airlineTabs.map((airline) => [airline.code, airline.color]),
);
const REGION_NAME = new Map<string, string>(
  worldRegions.map((region) => [region.slug, region.name]),
);

function Panel({
  icon: Icon,
  title,
  caption,
  href,
  hrefLabel,
  children,
}: {
  icon: typeof Megaphone;
  title: string;
  /** What the number in this panel actually measures. Not optional, and not a
   * tooltip: every figure in this section is a NEWS/CAMPAIGN VOLUME, and a
   * reader who skims one of them as market share has been misled by us. */
  caption: string;
  href: string;
  hrefLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-card bg-card-sheen p-3 shadow-elev-1">
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 text-muted-foreground" aria-hidden />
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        <Link
          href={href}
          className="ml-auto rounded text-[10px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {hrefLabel} →
        </Link>
      </div>
      <div className="flex flex-1 flex-col gap-2">{children}</div>
      <p className="text-[10px] leading-relaxed text-muted-foreground">{caption}</p>
    </div>
  );
}

/** "Rekabet Nabzı": three counts of what rivals are being written about.
 *
 * Everything here is a COUNT OF NEWS AND CAMPAIGNS. This system has no rival
 * capacity, load factor, market share or schedule data of any kind -- see the
 * Hub page's own note about there being no OAG feed on the free tier -- so no
 * number in this section may be captioned as any of those, and each panel
 * carries the caveat in its own footer rather than relying on one shared line
 * a reader might scroll past.
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
  const newRoutes = (routes.data ?? [])
    .flatMap((group) =>
      group.articles.map((article) => ({ ...article, region: group.region })),
    )
    .slice(0, 3);

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      <Panel
        icon={Megaphone}
        title="Son 48 saat"
        caption="Tespit edilen kampanya duyurusu sayısı — kapasite veya fiyat endeksi değil."
        href="/kampanyalar"
        hrefLabel="Kampanyalar"
      >
        {!newCount.loaded ? (
          <Skeleton className="h-16 w-full rounded-lg" />
        ) : (
          <>
            <span className="text-3xl font-semibold tabular-nums leading-none dark:text-glow">
              {newCount.data?.count ?? 0}
            </span>
            <div className="flex flex-wrap gap-1">
              {(newCount.data?.airline_codes ?? []).map((code) => (
                <span
                  key={code}
                  style={{ "--glow-color": BRAND_COLOR.get(code) ?? "var(--primary)" } as React.CSSProperties}
                  className="flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium edge-lit"
                >
                  <AirlineLogo code={code} className="size-3" />
                  {code}
                </span>
              ))}
              {(newCount.data?.airline_codes ?? []).length === 0 && (
                <span className="text-[11px] text-muted-foreground">
                  Son 48 saatte yeni kampanya yok.
                </span>
              )}
            </div>
          </>
        )}
      </Panel>

      <Panel
        icon={TrendingUp}
        title="Haber momentumu"
        caption="Son 7 günün haber sayısı, önceki 7 güne göre. Haber hacmi ölçüsüdür; performans değil."
        href="/biz"
        hrefLabel="Biz"
      >
        {!insights.loaded ? (
          <Skeleton className="h-16 w-full rounded-lg" />
        ) : movers.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Bu hafta belirgin bir hareket yok.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {movers.map((mover) => {
              const up = mover.delta > 0;
              return (
                <li key={mover.code} className="flex items-center gap-2 text-xs">
                  <AirlineLogo code={mover.code} className="size-3.5 shrink-0" />
                  <span
                    className="size-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: BRAND_COLOR.get(mover.code) ?? "var(--primary)" }}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate">{mover.name}</span>
                  <span
                    className={cn(
                      "flex shrink-0 items-center gap-0.5 tabular-nums font-semibold",
                      up ? "text-good" : "text-critical",
                    )}
                  >
                    {up ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />}
                    {Math.abs(mover.delta)}
                  </span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {mover.previous}→{mover.current}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <Panel
        icon={Route}
        title="Yeni rota sinyalleri"
        caption="Son 30 günde yeni hat duyurusu olarak sınıflanan haberler — tarife verisi değil."
        href="/hublar"
        hrefLabel="Hublar"
      >
        {!routes.loaded ? (
          <Skeleton className="h-16 w-full rounded-lg" />
        ) : newRoutes.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Son 30 günde yeni hat sinyali yok.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {newRoutes.map((signal) => (
              <li key={signal.id} className="flex flex-col gap-0.5">
                <a
                  href={signal.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="line-clamp-2 rounded text-xs leading-snug hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  {signal.headline}
                </a>
                <span className="text-[10px] text-muted-foreground">
                  {REGION_NAME.get(signal.region ?? "") ?? "Diğer"}
                  {signal.airlines.length > 0 && ` · ${signal.airlines.join(", ")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
