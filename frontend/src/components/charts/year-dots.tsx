import { ANNUAL_KIND_LABELS_TR, ANNUAL_KIND_SUFFIX } from "@/lib/cockpit";
import type { AnnualPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How many years the micro trend shows. Four, not eight: the 2020 COVID
 * trough is a third of the whole vertical range of most of these series, and
 * including it flattens the 2023-2026 stretch a reader is actually deciding
 * on into a horizontal line. The full eight-year run is one section below, on
 * a chart with an axis. */
const SLOT_COUNT = 4;

interface Slot {
  year: number;
  point: AnnualPoint | null;
}

/** The last `count` YEARS (not the last `count` points), each either filled by
 * a real observation or left empty.
 *
 * The distinction is the whole point. `cask` has no 2025 row -- a de-duplication
 * pass upstream mistook a legitimately-unchanged annual figure for a copy (see
 * D3 in the design spec) -- and a component that simply took "the last four
 * points" would silently draw 2022, 2023, 2024, 2026 as four evenly spaced,
 * consecutive-looking years. The gap has to be visible.
 */
export function buildSlots(points: AnnualPoint[], count = SLOT_COUNT): Slot[] {
  if (points.length === 0) return [];
  const lastYear = points[points.length - 1].year;
  const byYear = new Map(points.map((point) => [point.year, point]));
  return Array.from({ length: count }, (_, index) => {
    const year = lastYear - (count - 1 - index);
    return { year, point: byYear.get(year) ?? null };
  });
}

/**
 * An ANNUAL series drawn as discrete points -- because it is discrete.
 *
 * THE RULE THIS COMPONENT EXISTS TO ENFORCE
 * -----------------------------------------
 * Continuous line = live measurement. Discrete dot = annual publication.
 * Nothing on this page mixes the two inside one cell.
 *
 * IATA publishes these series twice a year, for the industry as a whole, as
 * eight yearly numbers. Drawing them with the same sparkline the FX cells use
 * would tell a reader three untrue things at once:
 *
 *   * CONTINUITY -- a line implies measured values between the points. There
 *     are none; nobody measured global RPK in March.
 *   * RECENCY -- the rightmost pixel of an FX sparkline is fifteen minutes
 *     old. The rightmost pixel here is a FORECAST for a year that has not
 *     finished.
 *   * SHAPE -- see `SLOT_COUNT` above.
 *
 * So: a filled dot is a measured year, a hollow ring is an estimate or a
 * forecast, and the connector into a non-actual year is dashed. Form carries
 * the epistemic status; colour is not used at all here, because colour on this
 * page means good-or-bad and "this is a projection" is neither. For the same
 * reason there is no `glow` on this surface -- glow means "live" in this
 * system, and a glowing IATA forecast would read as a measurement.
 */
export function YearDots({
  points,
  count = SLOT_COUNT,
  unitLabel,
  className,
}: {
  points: AnnualPoint[];
  count?: number;
  /** Appended to each dot's hover text, e.g. "mlr RPK". */
  unitLabel?: string;
  className?: string;
}) {
  const slots = buildSlots(points, count);
  if (slots.length === 0) return null;

  const values = slots.filter((slot) => slot.point).map((slot) => slot.point!.value);
  const min = values.length > 0 ? Math.min(...values) : 0;
  const max = values.length > 0 ? Math.max(...values) : 0;
  // Percent from the TOP of the 20px band, kept inside 15..85 so a dot at
  // either extreme is not half outside its own row.
  const yPct = (value: number) => (max === min ? 50 : 85 - ((value - min) / (max - min)) * 70);
  const slotCentreX = (index: number) => ((index + 0.5) / slots.length) * 100;

  const segments = slots.slice(0, -1).flatMap((slot, index) => {
    const next = slots[index + 1];
    // A missing year breaks the line rather than being interpolated across.
    // Interpolation here would be us inventing an IATA figure.
    if (!slot.point || !next.point) return [];
    return [
      {
        key: `${slot.year}-${next.year}`,
        x1: slotCentreX(index),
        y1: yPct(slot.point.value),
        x2: slotCentreX(index + 1),
        y2: yPct(next.point.value),
        // Dashed as soon as the year it ARRIVES at is not a measurement.
        dashed: next.point.kind !== "actual",
      },
    ];
  });

  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <div className="relative h-5 w-full">
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          aria-hidden
        >
          {segments.map((segment) => (
            <line
              key={segment.key}
              x1={segment.x1}
              y1={segment.y1}
              x2={segment.x2}
              y2={segment.y2}
              stroke="currentColor"
              strokeWidth={0.75}
              strokeDasharray={segment.dashed ? "2 2" : undefined}
              vectorEffect="non-scaling-stroke"
              className="text-muted-foreground/40"
            />
          ))}
        </svg>
        {slots.map((slot, index) => (
          <div key={slot.year} className="absolute inset-y-0" style={{ left: `${slotCentreX(index)}%` }}>
            {slot.point ? (
              <span
                title={`${slot.year}${ANNUAL_KIND_SUFFIX[slot.point.kind]} · ${slot.point.value.toLocaleString(
                  "tr-TR",
                )}${unitLabel ? ` ${unitLabel}` : ""} · ${ANNUAL_KIND_LABELS_TR[slot.point.kind]}`}
                style={{ top: `${yPct(slot.point.value)}%` }}
                className={cn(
                  "absolute size-[5px] -translate-x-1/2 -translate-y-1/2 rounded-full",
                  slot.point.kind === "actual"
                    ? "bg-foreground/70"
                    : // Hollow: this year was not measured.
                      "border border-foreground/60 bg-transparent",
                )}
              />
            ) : (
              // An empty slot is still a slot: the year label below it prints,
              // the dot does not, and no connector crosses it.
              <span
                title={`${slot.year} verisi yok`}
                className="absolute top-1/2 size-[5px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-dashed border-muted-foreground/40"
              />
            )}
          </div>
        ))}
      </div>
      <div className="flex w-full">
        {slots.map((slot) => (
          <span
            key={slot.year}
            // 10px at full opacity, not 9px at 70%. The year is the label
            // that tells a reader an IATA forecast from a measured year, and
            // `text-muted-foreground/70` measured 2,84:1 on the light theme --
            // under AA, for the one caption the dots cannot do without.
            className="flex-1 text-center text-[10px] leading-none tabular-nums text-muted-foreground"
          >
            {String(slot.year).slice(2)}
            {slot.point ? ANNUAL_KIND_SUFFIX[slot.point.kind] : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
