import { cn } from "@/lib/utils";
import type { PromotionOut } from "@/lib/types";

/** The two windows a campaign has, drawn as two separate tracks.
 *
 * THIS IS THE PAGE'S CENTRAL DATA DISTINCTION (§11), and the reason it is a
 * component rather than two lines of text: "you can buy it until 15 September"
 * and "you can fly it until 31 December" are different facts about different
 * dates, and a desk that reads one as the other prices against a window that
 * closed two months ago. So they are never rendered as one range, never
 * adjacent in the same visual channel, and never in the same fill:
 *
 *   * SATIŞ is a solid bar. It is the commercial deadline -- the thing that
 *     expires while you read the page.
 *   * SEYAHAT is a hatched bar. Same geometry, unmistakably different texture,
 *     so the two are told apart at a glance and still told apart in greyscale,
 *     which colour alone would not survive.
 *
 * Both carry their own uppercase label and their own pre-formatted Turkish
 * range, because the labels are the primary separation and the geometry is
 * reinforcement -- never the other way round.
 *
 * The scale is shared and LOCAL to one campaign: both bars are positioned
 * against the same [earliest known date, latest known date] span, so the
 * offset between selling and flying is readable inside a row. It is not a
 * calendar and does not pretend to be one -- there are no tick marks, no
 * "today" line and no cross-row alignment, because a 3mm bar cannot carry a
 * date axis honestly.
 *
 * A window with no stated edge at all draws NO bar. An unstated window is not
 * a zero-length one, and a hairline at the left edge would read as "starts
 * today".
 */

/** A window's edges plus the label the backend already formatted for it. */
interface CampaignWindow {
  key: "sale" | "travel";
  label: string;
  start: string | null;
  end: string | null;
  text: string;
}

function span(day: string | null): number | null {
  const at = Date.parse(`${(day ?? "").slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(at) ? null : at;
}

/** Where a window sits on the shared scale, as CSS percentages, or null when
 * there is nothing to draw. */
function place(
  window: CampaignWindow,
  min: number,
  max: number,
): { left: number; width: number; openStart: boolean; openEnd: boolean } | null {
  const start = span(window.start);
  const end = span(window.end);
  if (start === null && end === null) return null;

  const total = Math.max(max - min, 1);
  const from = start ?? min;
  const to = Math.max(end ?? max, from);
  return {
    left: ((from - min) / total) * 100,
    // A single-day window still has to be visible, hence the floor.
    width: Math.max(((to - from) / total) * 100, 7),
    openStart: start === null,
    openEnd: end === null,
  };
}

export function CampaignWindows({
  promo,
  className,
}: {
  promo: PromotionOut;
  className?: string;
}) {
  const windows: CampaignWindow[] = [
    {
      key: "sale",
      label: "Satış",
      start: promo.sale_starts,
      end: promo.sale_ends,
      text: promo.sale_range_tr,
    },
    {
      key: "travel",
      label: "Seyahat",
      start: promo.travel_starts,
      end: promo.travel_ends,
      text: promo.travel_range_tr,
    },
  ];

  const points = windows
    .flatMap((w) => [span(w.start), span(w.end)])
    .filter((value): value is number => value !== null);
  const min = points.length > 0 ? Math.min(...points) : 0;
  const max = points.length > 0 ? Math.max(...points) : 1;

  return (
    <dl className={cn("grid grid-cols-[3.5rem_1fr] items-center gap-x-2 gap-y-1", className)}>
      {windows.map((window) => {
        const placed = place(window, min, max);
        const sale = window.key === "sale";
        return (
          <div key={window.key} data-window={window.key} className="contents">
            <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {window.label}
            </dt>
            <dd className="flex min-w-0 items-center gap-2">
              <span
                aria-hidden
                className="hidden h-1.5 w-24 shrink-0 rounded-sm bg-muted sm:block"
              >
                {placed && (
                  <span
                    data-track={window.key}
                    className={cn("block h-full rounded-sm", sale && "bg-foreground")}
                    style={{
                      marginLeft: `${placed.left}%`,
                      width: `${placed.width}%`,
                      // Hatching, not a second hue: the travel bar has to be
                      // distinguishable from the sale bar on a monochrome
                      // screen and for a reader who cannot separate the hues.
                      ...(sale
                        ? {}
                        : {
                            backgroundImage:
                              "repeating-linear-gradient(115deg, var(--muted-foreground) 0 2px, transparent 2px 4px)",
                          }),
                      // An unstated edge dissolves rather than ending: there
                      // is no published date, so there is no edge to draw.
                      ...(placed.openEnd || placed.openStart
                        ? {
                            maskImage: `linear-gradient(90deg, ${placed.openStart ? "transparent" : "#000"} 0%, #000 40%, #000 60%, ${placed.openEnd ? "transparent" : "#000"} 100%)`,
                          }
                        : {}),
                    }}
                  />
                )}
              </span>
              <span
                className={cn(
                  "truncate text-[11px] tabular-nums",
                  placed ? "text-foreground/80" : "text-muted-foreground",
                )}
                title={window.text}
              >
                {window.text}
              </span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
