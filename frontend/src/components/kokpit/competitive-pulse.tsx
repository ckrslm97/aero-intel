"use client";

import { Megaphone, RotateCw, Route, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Delta } from "@/components/ui/delta";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { regionsOf } from "@/lib/network-signals";
import { worldRegions } from "@/lib/nav";
import { RIVAL_CODES } from "@/lib/taxonomy.gen";
import type {
  InsightsOut,
  NetworkSignalGroup,
  NetworkSignalsOut,
  PromotionNewCountOut,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME = new Map<string, string>(
  worldRegions.map((region) => [region.slug, region.name]),
);

/** The carriers this cell is allowed to rank, from the generated taxonomy.
 *
 * TK is the home carrier and is deliberately absent (backend/app/taxonomy.py
 * RIVAL_CODES, and SQ with it) -- but `/insights` counts mentions across the
 * whole feed, and in a Turkish-language feed the most-mentioned carrier is
 * always TK. A "Rekabet" cell whose top mover is the airline it is written for
 * is not a competitive reading; it is the feed's own language, ranked.
 *
 * A Set, so a taxonomy that grows a rival costs no scan per row. */
const RIVAL_CODE_SET = new Set<string>(RIVAL_CODES);

/** "The stream did not answer" -- which is NOT "the stream answered zero".
 *
 * All three cells used to branch on `loaded` alone and then read
 * `data?.count ?? 0` / an empty array, so a 500 from any of the three
 * endpoints printed a confident "0" and "Son 48 saatte yeni kampanya yok."
 * A count is a claim about the world; an error is a claim about us. The page's
 * whole argument is that it never prints the first when it only knows the
 * second. `SignalStream` already had this right with `DataSourceError`; this
 * is the same contract at cell scale, where a full error panel would not fit.
 */
function SourceDown({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
      <span>Kaynak okunamadı.</span>
      <button
        type="button"
        onClick={onRetry}
        className="flex items-center gap-1 rounded border border-border px-1.5 py-px font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <RotateCw className="size-2.5" aria-hidden />
        Yeniden dene
      </button>
    </div>
  );
}

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
    <div className="flex min-h-[56px] flex-col gap-1 rounded-lg border border-border bg-card/60 px-3 py-2">
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
      apiFetch<NetworkSignalsOut | NetworkSignalGroup[]>("/hubs/network-signals?days=30", {
        cache: "default",
        signal,
      }),
    [],
  );

  const newCount = useDataSource(newCountFetcher, []);
  const insights = useDataSource(insightsFetcher, []);
  const routes = useDataSource(routesFetcher, []);

  const momentum = insights.data?.airline_momentum ?? [];
  // Rivals only -- see RIVAL_CODE_SET. Filtered BEFORE the "did anything move"
  // test so the empty state below still distinguishes "the stream returned
  // nothing" from "it returned rows and no rival moved".
  const rivalMomentum = momentum.filter((mover) => RIVAL_CODE_SET.has(mover.code));
  const movers = rivalMomentum.filter((mover) => mover.delta !== 0).slice(0, 3);
  // `regionsOf`, not `.regions`: the edge can still hand this new code the
  // pre-envelope array for the length of one cache lifetime (lib/network-
  // signals.ts). `?? []` only after that, and only because the cell below
  // separately distinguishes "never answered" via `routes.loaded`/`routes.data`.
  const routeGroups = regionsOf(routes.data) ?? [];
  const routeTotal = routeGroups.reduce((sum, group) => sum + group.count, 0);
  const firstRoute = routeGroups.find((group) => group.articles.length > 0);

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <Cell icon={Megaphone} title="48 saatte kampanya" href="/kampanyalar">
        {!newCount.loaded ? (
          <Skeleton className="h-6 w-full rounded" />
        ) : !newCount.data ? (
          <SourceDown onRetry={newCount.retry} />
        ) : (
          <div className="flex items-center gap-2">
            {/* A zero is printed ONCE, and quietly. It used to be a 20px/600
                figure -- the same weight as the KPI strip's real numbers --
                followed by a sentence repeating it in words: the largest type
                in the section, spent twice on "nothing happened". */}
            <span
              className={cn(
                "leading-none tabular-nums",
                newCount.data.count === 0
                  ? "text-sm font-medium text-muted-foreground"
                  : "text-xl font-semibold",
              )}
            >
              {newCount.data.count}
            </span>
            <span className="text-[10px] text-muted-foreground">son 48 saat</span>
            <div className="flex min-w-0 flex-wrap gap-1">
              {newCount.data.airline_codes.slice(0, 4).map((code) => (
                <span
                  key={code}
                  className="flex items-center gap-0.5 rounded-full border border-border px-1 text-[10px]"
                >
                  <AirlineLogo code={code} className="size-2.5" />
                  {code}
                </span>
              ))}
            </div>
          </div>
        )}
      </Cell>

      <Cell icon={TrendingUp} title="Rakip haber momentumu (7g vs 7g)" href="/biz">
        {!insights.loaded ? (
          <Skeleton className="h-6 w-full rounded" />
        ) : !insights.data ? (
          <SourceDown onRetry={insights.retry} />
        ) : movers.length === 0 ? (
          // THREE facts, three sentences. "We have no measurement", "we
          // measured the feed and no RIVAL was in it" and "rivals were
          // measured and none moved" are different things to go and check, and
          // one sentence for all three would hide the middle one entirely --
          // which is the state the TK filter above can now produce.
          <p className="text-[10px] text-muted-foreground">
            {momentum.length === 0
              ? "Momentum verisi yok."
              : rivalMomentum.length === 0
                ? "Bu hafta rakip taşıyıcı ölçülmedi."
                : "Bu hafta belirgin bir hareket yok."}
          </p>
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
        ) : !routes.data ? (
          <SourceDown onRetry={routes.retry} />
        ) : !firstRoute ? (
          <p className="text-[10px] text-muted-foreground">Yeni rota sinyali yok.</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {/* The count is WORLDWIDE; the region belongs to the headline
                underneath it. They used to share one line -- "14 · Avrupa" --
                which reads as "fourteen new route signals in Europe" and was
                never true: 14 is every region added up, Europe is merely the
                first group that had an article. Two scopes, two lines. */}
            <span className="text-[11px] tabular-nums">
              <b>{routeTotal}</b> sinyal · 30g · tüm bölgeler
            </span>
            <a
              href={firstRoute.articles[0].url}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate rounded text-[10px] text-muted-foreground hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {REGION_NAME.get(firstRoute.region ?? "") ?? "Diğer"} · {firstRoute.articles[0].headline}
            </a>
          </div>
        )}
      </Cell>
    </div>
  );
}
