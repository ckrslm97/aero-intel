"use client";

import { Megaphone, RotateCw, Route, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import type { PromotionNewCountOut, SignalOut, SignalStreamOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME = new Map<string, string>(
  worldRegions.map((region) => [region.slug, region.name]),
);

/** Where each cell's own stream is listed in full.
 *
 * These are the SAME strings backend/app/services/signals_service.py puts on
 * that stream's rows (NETWORK_HREF, MOMENTUM_HREF), and the cells below prefer
 * a row's own `href` when there is a row to read it from. The constants exist
 * for the empty state, which still has to offer a way through.
 *
 * Both were wrong until this round, in the same way: the cell header linked
 * somewhere the stream is not drawn. Momentum pointed at /biz, which is the
 * THY desk and has carried no rival momentum since the signals block moved
 * out of it; routes pointed at bare /hublar, which lands on the hub map rather
 * than the Ağ Sinyalleri tab that actually lists route announcements.
 */
const MOMENTUM_HOME = "/sinyaller?kind=competitor";
const NETWORK_HOME = "/hublar?view=network-signals";

/** "The stream did not answer" -- which is NOT "the stream answered zero".
 *
 * All three cells used to branch on `loaded` alone and then read
 * `data?.count ?? 0` / an empty array, so a 500 printed a confident "0" and
 * "Son 48 saatte yeni kampanya yok." A count is a claim about the world; an
 * error is a claim about us.
 *
 * `onRetry` is optional because two of the three cells no longer own their
 * request: the signal feed is read once on the server, so its retry is the
 * page-level one printed directly above this row (ServerSourceError). A second
 * button per cell would ask again for the same thing three times over. What
 * the cells still owe the reader is WHICH of them went dark -- the campaign
 * count has its own source and is unaffected -- and that is this sentence.
 */
function SourceDown({ onRetry }: { onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
      <span>Kaynak okunamadı.</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="flex items-center gap-1 rounded border border-border px-1.5 py-px font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <RotateCw className="size-2.5" aria-hidden />
          Yeniden dene
        </button>
      )}
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

/** The stream key behind each of this row's two signal cells.
 *
 * Named constants rather than literals inline, because the cells below filter
 * by them AND `PULSE_STREAMS` is built out of them. The set used to be written
 * separately from the two literals the cells actually used, which made the
 * routing contract decorative for this row: a stream added to the set alone
 * would have satisfied signal-routing.test.ts's "covers every stream" while
 * this row drew nothing -- exactly the silent drop that test exists to catch.
 * Membership and rendering now come from one pair of names. */
const MOMENTUM_STREAM = "momentum";
const NETWORK_STREAM = "network";

/** The two streams this row draws. Exported for the same reason
 * `KOKPIT_STREAMS` and `ALERT_STREAMS` are: together the three sets have to
 * cover all seven streams exactly once, or a stream is either drawn twice on
 * one page or silently drawn nowhere. See signal-routing.test.ts, and
 * competitive-pulse.test.tsx for the half that pins each member to a cell. */
export const PULSE_STREAMS = new Set([MOMENTUM_STREAM, NETWORK_STREAM]);

/** How many movers / route signals the cells print. The rows arrive ordered by
 * the backend, so the head is the strongest -- see `sort_signals`. */
const CELL_ROW_LIMIT = 3;

/**
 * REKABET / PİYASA GÖRÜNÜMÜ -- three counts, one row.
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
 * TWO OF THE THREE CELLS NO LONGER FETCH. Momentum came from `/insights` and
 * routes from `/hubs/network-signals`, which is how this row and /sinyaller
 * came to draw the same two streams from two different reads, with two
 * different caps and two different orderings. They read the page's one
 * server-side `/signals` now, filtered by stream, in the backend's order --
 * so a mover shown here is the same row, in the same place, that /sinyaller
 * lists. The 48-hour campaign count stays a fetch of its own: it is a
 * promotion count, not a signal, and no stream publishes it.
 *
 * WHAT MOVING THE MOMENTUM CELL COST, stated rather than hidden: it used to
 * separate three empty states -- "no measurement at all", "the feed was
 * measured and held no rival", "rivals were measured and none moved" -- by
 * inspecting the raw `/insights` list. The signal feed publishes the stream's
 * output, not its input, so those three collapse into one: no momentum signal.
 * The distinction is gone because the evidence for it is gone, and the cell
 * says only what it can still see. What is NOT lost is the failure case: an
 * unread feed arrives as `unavailable`, the two cells say so instead of
 * reporting a stillness, and the retry is the page's one line above this row
 * rather than three buttons asking for the same response.
 */
export function CompetitivePulse({
  signals,
  streams,
  unavailable = false,
}: {
  /** The page's one read of `/signals`, unfiltered and in the backend's own
   * order. */
  signals: SignalOut[];
  /** The per-stream tally from the same response -- the only place the
   * worldwide route total survives the list's display cap. */
  streams: SignalStreamOut[];
  /** The feed was NOT READ. Not derivable from `signals` being empty: an empty
   * feed is a measurement ("no rival moved this week") and an unread one is
   * not, and the two must not render the same. The campaign cell keeps its own
   * source and is unaffected either way. */
  unavailable?: boolean;
}) {
  const newCountFetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<PromotionNewCountOut>("/promotions/new-count", { cache: "default", signal }),
    [],
  );
  const newCount = useDataSource(newCountFetcher, []);

  // One cell per member of PULSE_STREAMS, filtered by the very constants that
  // set is built from -- filtered rather than re-sorted, so the head shown
  // here is the head /sinyaller shows.
  const movers = signals.filter((row) => row.stream === MOMENTUM_STREAM);
  const routes = signals.filter((row) => row.stream === NETWORK_STREAM);
  // The stream's own worldwide total -- wider than the rows listed here, and
  // itself capped by the backend's event limit (see SignalStreamOut.total).
  // `null` means the backend published no total for this stream, which is NOT
  // zero -- so the line is omitted rather than printed with a number this page
  // does not have.
  const routeTotal =
    streams.find((stream) => stream.key === NETWORK_STREAM)?.total ?? null;

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

      <Cell
        icon={TrendingUp}
        title="Rakip haber momentumu (7g vs 7g)"
        href={movers[0]?.href ?? MOMENTUM_HOME}
      >
        {unavailable ? (
          <SourceDown />
        ) : movers.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">
            Bu hafta rakip haber momentumu sinyali yok.
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {movers.slice(0, CELL_ROW_LIMIT).map((mover) => (
              <li key={mover.id} className="flex items-center gap-1 text-[11px]">
                {mover.airline_codes[0] && (
                  <AirlineLogo code={mover.airline_codes[0]} className="size-3 shrink-0" />
                )}
                {/* The backend's own sentence -- "Emirates haber hacmi +4
                    (12→16)" -- not a re-assembly of it here. It is neutral on
                    purpose: more press coverage is not "good", it is more
                    press coverage, so the delta takes no colour. */}
                <span className="truncate">{mover.title_tr}</span>
              </li>
            ))}
          </ul>
        )}
      </Cell>

      <Cell
        icon={Route}
        title="Yeni rota sinyali (30g)"
        href={routes[0]?.href ?? NETWORK_HOME}
      >
        {unavailable ? (
          <SourceDown />
        ) : routes.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">Yeni rota sinyali yok.</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {/* The count is WORLDWIDE; the region belongs to the headline
                underneath it. They used to share one line -- "14 · Avrupa" --
                which reads as "fourteen new route signals in Europe" and was
                never true: 14 is every region added up, Europe is merely the
                region of the newest announcement. Two scopes, two lines. */}
            {routeTotal !== null && (
              <span className="text-[11px] tabular-nums">
                <b>{routeTotal}</b> sinyal · 30g · tüm bölgeler
              </span>
            )}
            {/* In-app, not out to the wire. The headline used to link straight
                to the article, which the signal feed does not publish -- a row
                carries `source_label`, not a source URL. So it goes where the
                announcement is listed WITH its source link, which is also
                where this cell's arrow goes. */}
            <Link
              href={routes[0].href ?? NETWORK_HOME}
              className="truncate rounded text-[10px] text-muted-foreground hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {REGION_NAME.get(routes[0].region ?? "") ?? "Diğer"} · {routes[0].title_tr}
            </Link>
          </div>
        )}
      </Cell>
    </div>
  );
}
