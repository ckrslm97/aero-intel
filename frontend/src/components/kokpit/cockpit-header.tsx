"use client";

import { useNow } from "@/hooks/use-now";
import { freshnessOf, oldestAsOf } from "@/lib/cockpit";
import { formatUtcTime } from "@/lib/format";
import type { KokpitFxBoardOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Kokpit's title band.
 *
 * Replaces a tall hero-mesh block that spent a third of the fold on a gradient
 * and a sentence. The page has to answer four things in five seconds -- durum
 * ne, risk var mı, ne değişiyor, neye dikkat -- and none of them were above
 * the fold while the hero was.
 *
 * The right-hand side is the only new claim here, and it is a claim, so it is
 * earned from data: "Canlı" appears when the FX board's OLDEST reading is
 * inside `LIVE_WINDOW_MINUTES`, and otherwise the band says exactly how late
 * it is. There is deliberately no "%98,7 veri sağlığı" figure -- no such
 * measurement exists in this system, and inventing one at the top of the page
 * would undermine every honest number below it.
 *
 * TWO THINGS MOVED HERE, and both were the same bug seen from different sides:
 * a claim about NOW, decided somewhere that is not now.
 *
 *   * The clock. This was a server component, so `freshnessOf` compared the
 *     data against the PRE-RENDER instant and that verdict was then cached for
 *     `revalidate: 60` and beyond. Production served an 18:03 UTC reading under
 *     a lit "Canlı" dot at 18:41. The verdict is now taken on the reader's own
 *     clock, and before its first tick the band prints the stamp and makes no
 *     freshness claim at all (see hooks/use-now.ts).
 *
 *   * The reading. This stamped itself with the FRESHEST pair on a board of
 *     seven. One pair updating while another's cron had been failing for two
 *     hours lit "Canlı" over a two-hour-old row. One badge over many readings
 *     can only describe the worst of them, so it is `oldestAsOf` -- the only
 *     board-wide stamp lib/cockpit.ts still exports; the per-pair detail lives
 *     on the rows (fx-board-table.tsx).
 *
 * AND ONE THING THE BAND MAY NOT SAY. `board === null` has two causes -- a
 * board with no pairs on it, and `/kokpit/fx` not answering -- and
 * `freshnessOf(null)` collapses both into "Veri yok", in amber, in the top
 * right corner of the product's first screen. To an RM desk that reads as "no
 * exchange-rate data exists", which is a claim about the world assembled out
 * of an HTTP failure. `unavailable` is the caller's statement that the request
 * failed (app/page.tsx passes `board.failed`), and it buys the one honest
 * sentence available: the board was not read.
 */
export function CockpitHeader({
  board,
  /** The FX board request failed, as opposed to answering with an empty board.
   * Same `board === null` prop, opposite facts -- see the badge below. */
  unavailable = false,
}: {
  board: KokpitFxBoardOut | null;
  unavailable?: boolean;
}) {
  const now = useNow();
  const asOf = board ? oldestAsOf(board.pairs) : null;
  const freshness = freshnessOf(asOf, now);
  const perSource = board?.pairs
    .map((pair) => `${pair.currency_pair}: ${formatUtcTime(pair.as_of) ?? "—"} UTC`)
    .concat("Rozet panonun EN ESKİ okumasına göre verilir.")
    .join("\n");

  return (
    <header className="flex flex-col gap-2 pb-2">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-lg font-semibold leading-none tracking-tight">
            <span className="gradient-text">KOKPİT</span>
          </h1>
          {/* The subtitle drops to the page's smallest type. The header's job
              is to be identifiable and to stamp the data's freshness; every
              pixel it spends on describing itself is a pixel the fold does not
              spend on the market. */}
          {/* `lang="en"` is load-bearing, not decoration. The document is
              lang="tr", and CSS `text-transform: uppercase` is LOCALE-SENSITIVE:
              under Turkish casing rules a dotless "i" uppercases to "İ", so
              this English phrase rendered as "AVİATİON INTELLİGENCE" -- which
              reads as a typo in the product's own name. Tagging the span as
              English restores "AVIATION INTELLIGENCE". */}
          <p
            lang="en"
            className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground"
          >
            Aviation Intelligence
          </p>
        </div>

        {/* ONE chip, ONE timestamp.
            It used to be two: "Gecikmeli · son 16:50" beside "Veri: 16:50
            UTC" -- the same minute printed twice, in two formats, and neither
            of them saying how late "late" was. A reader could read "son
            16:50" as today's 16:50 while the board was two days old. The dot
            carries the status, the time carries the reading, and the delay
            carries the only part that decides whether the numbers below are
            usable. */}
        <div
          className="flex items-center gap-1.5 text-[11px] tabular-nums text-muted-foreground"
          title={perSource || undefined}
        >
          {/* Three colours for four states, and the split is the point: green
              is an earned claim, amber is an admitted problem, and MUTED is
              "not judged yet" -- the pre-tick state must look like neither of
              the other two, or the placeholder becomes a claim of its own. */}
          <span
            aria-hidden
            style={
              {
                "--glow-color":
                  freshness.state === "live" ? "var(--good)" : "var(--warning)",
              } as React.CSSProperties
            }
            className={cn(
              "size-1.5 rounded-full",
              freshness.state === "live" && "bg-good dark:glow-soft",
              freshness.state === "pending" && "bg-muted-foreground",
              (freshness.state === "stale" || freshness.state === "missing") && "bg-warning",
            )}
          />
          {freshness.timeLabel ? (
            <>
              {freshness.state === "live" && (
                <span className="font-medium text-good">Canlı ·</span>
              )}
              <span>Veri {freshness.timeLabel} UTC</span>
              {freshness.delayLabel && (
                <span className="font-medium text-warning">· {freshness.delayLabel} gecikmeli</span>
              )}
            </>
          ) : (
            <span className="font-medium text-warning">
              {unavailable ? "Kur panosu okunamadı" : freshness.label}
            </span>
          )}
        </div>
      </div>
      <span
        aria-hidden
        style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
        className="hairline-glow block w-full"
      />
    </header>
  );
}
