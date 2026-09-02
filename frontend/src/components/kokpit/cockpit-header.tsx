import { freshnessOf, latestAsOf } from "@/lib/cockpit";
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
 * earned from data: "Canlı" appears when the FX board's newest reading is
 * inside `LIVE_WINDOW_MINUTES`, and otherwise the band says exactly how late
 * it is. There is deliberately no "%98,7 veri sağlığı" figure -- no such
 * measurement exists in this system, and inventing one at the top of the page
 * would undermine every honest number below it.
 */
export function CockpitHeader({ board }: { board: KokpitFxBoardOut | null }) {
  const asOf = board ? latestAsOf(board.pairs) : null;
  const freshness = freshnessOf(asOf);
  const perSource = board?.pairs
    .map(
      (pair) =>
        `${pair.currency_pair}: ${new Date(pair.as_of).toLocaleTimeString("tr-TR", {
          timeZone: "UTC",
          hour: "2-digit",
          minute: "2-digit",
        })} UTC`,
    )
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

        <div
          className="flex items-center gap-2 text-[11px] tabular-nums text-muted-foreground"
          title={perSource || undefined}
        >
          <span
            aria-hidden
            style={{ "--glow-color": freshness.live ? "var(--good)" : "var(--warning)" } as React.CSSProperties}
            className={cn(
              "size-1.5 rounded-full",
              freshness.live ? "bg-good dark:glow-soft" : "bg-warning",
            )}
          />
          <span className={cn("font-medium", freshness.live ? "text-good" : "text-warning")}>
            {freshness.label}
          </span>
          {freshness.timeLabel && (
            <>
              <span aria-hidden className="h-3 w-px bg-border" />
              <span>Veri: {freshness.timeLabel} UTC</span>
            </>
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
