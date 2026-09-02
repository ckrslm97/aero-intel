import { cn } from "@/lib/utils";

/** Whether the metric has a direction that is good or bad.
 *
 * `neutral` -- an FX pair. The endpoint takes the plain foreground tone.
 * `costly`  -- a cost base (Brent). A rise IS bad, so the endpoint may redden.
 *
 * The LINE is never coloured either way. See the note on the component. */
export type MicroTrendTone = "neutral" | "costly";

const VIEW_W = 64;
const VIEW_H = 20;
/** Vertical inset so the endpoint dot is never clipped by the viewBox edge. */
const INSET = 2;

/**
 * A 20px trend line for a LIVE series -- continuous, because the underlying
 * measurement is continuous.
 *
 * WHY THIS EXISTS RATHER THAN `charts/sparkline.tsx`
 * -------------------------------------------------
 * Two independent reasons, one visual and one about honesty.
 *
 * 1. `Sparkline` is broken below ~26px. Its `grid {top: 4, bottom: 2}` eats
 *    6 of 20 available pixels, and its endpoint `markPoint` is `symbolSize: 8`
 *    -- two thirds of what is left -- centred on the grid's right edge with
 *    `right: 2`, so half the dot is clipped. It also mounts a full ECharts
 *    instance per cell, which for a five-cell pulse row plus five KPI cells is
 *    ten chart instances that only redraw on `window resize`.
 *
 * 2. `Sparkline`'s `positive` prop defaults to TRUE, and market-strip.tsx
 *    never passed it. So every FX cell -- whose delta was carefully rendered
 *    in a neutral tone one row above, precisely because a currency move is
 *    neither good nor bad -- drew a GREEN trend line underneath it regardless
 *    of direction. The text said neutral and the graphic said "good". This
 *    component closes that structurally rather than by remembering to pass a
 *    prop: the line has no status colour available to it at all.
 *
 * Fewer than two points draws nothing. The caller then prints "yeterli geçmiş
 * yok" in the same 20px slot -- a trend through one observation is decoration,
 * and the slot must not change height or the fold arithmetic moves.
 */
export function MicroTrend({
  data,
  tone = "neutral",
  className,
  title,
}: {
  data: number[];
  tone?: MicroTrendTone;
  className?: string;
  title?: string;
}) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  // A series that genuinely has not moved has min === max, which collapses the
  // range to zero and makes every y NaN. Pad it so an unchanged metric renders
  // as a visible flat line through the middle -- the same guard, and the same
  // reasoning, as charts/sparkline.tsx.
  const pad = min === max ? Math.abs(min) * 0.05 || 1 : 0;
  const lo = min - pad;
  const hi = max + pad;
  const span = hi - lo;

  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * VIEW_W;
    const y = VIEW_H - INSET - ((value - lo) / span) * (VIEW_H - INSET * 2);
    return [x, y] as const;
  });
  const [lastX, lastY] = points[points.length - 1];
  const rising = data[data.length - 1] > data[0];

  return (
    <svg
      // The box stretches to the cell's width; `non-scaling-stroke` below keeps
      // the line exactly 1px however far it is stretched.
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="none"
      className={cn("block h-5 w-full overflow-visible", className)}
      role="img"
      aria-label={title ?? "Trend"}
    >
      {title && <title>{title}</title>}
      <polyline
        points={points.map(([x, y]) => `${x},${y}`).join(" ")}
        fill="none"
        // ALWAYS neutral. No area fill either: a filled sparkline reads as a
        // volume, and this is a price.
        stroke="currentColor"
        strokeWidth={1}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        className="text-muted-foreground"
      />
      {/* The endpoint, drawn as a zero-length round-capped stroke rather than
          a <circle>: with preserveAspectRatio="none" the x axis is stretched,
          which would turn a circle into an ellipse. A round cap under
          non-scaling-stroke stays a 3px circle at any stretch. */}
      <path
        d={`M${lastX} ${lastY}L${lastX} ${lastY}`}
        stroke="currentColor"
        strokeWidth={3}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        className={cn(
          tone === "costly"
            ? rising
              ? "text-critical"
              : "text-good"
            : "text-foreground/70",
        )}
      />
    </svg>
  );
}
