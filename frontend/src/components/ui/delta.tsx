import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** What a move MEANS, which is a different question from which way it went.
 *
 * * `neutral` -- the metric has no polarity. A currency pair rising is neither
 *   good nor bad for an airline (it lifts some costs and some revenues), and
 *   the backend fixes this at the type level: `AnnualSeriesOut` carries
 *   `up_is_good`, `KokpitFxPairOut` and `EnergyMetricOut` deliberately do not.
 *   A neutral delta therefore renders with NO status colour at all, ever --
 *   `delta.test.tsx` asserts that as a regression lock, because the surface
 *   this replaces (market-strip.tsx) wrote `tone: "neutral"` on the number and
 *   then drew a green sparkline underneath it.
 * * `signed`  -- up is good (RPK, revenue, yield).
 * * `costly`  -- up is bad (Brent, CASK, any cost base).
 */
export type DeltaTone = "neutral" | "signed" | "costly";

/** `bare` is the default and covers ~40 of the ~45 deltas on the page: an
 * arrow and a number, no box. `pill` is rationed to the five KPI cards.
 *
 * Why ration it: an 11px number inside a rounded box spends roughly three
 * times the ink of the number alone, and if every delta is a pill then no
 * delta is emphasis.
 *
 * `arrow` prints the DIRECTION AND NOTHING ELSE, for rows where the number
 * already appears beside it in its own true unit. Sektör Dengesi is the reason
 * it exists: its rows carry percentage-POINT gaps and a cents-per-ASK margin,
 * and running those through this component's percent formatter produced
 * "+%0,6" next to "+0,6pp" (one quantity, printed twice, once in a unit it is
 * not) and "-%0,2" next to "0,42" (a 0,23¢ move relabelled as a percentage).
 * The arrow is the only part of a Delta that is unit-free, so it is the only
 * part such a row can borrow. */
export type DeltaForm = "bare" | "pill" | "arrow";

/** Direction in words, for the arrow-only form's assistive label. */
const DIRECTION_TR = { up: "yükseldi", down: "geriledi", flat: "değişmedi" } as const;

const TONE_UP: Record<DeltaTone, string> = {
  neutral: "text-muted-foreground",
  signed: "text-good",
  costly: "text-critical",
};

const TONE_DOWN: Record<DeltaTone, string> = {
  neutral: "text-muted-foreground",
  signed: "text-critical",
  costly: "text-good",
};

const PILL_UP: Record<DeltaTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  signed: "bg-good/10 text-good",
  costly: "bg-critical/10 text-critical",
};

const PILL_DOWN: Record<DeltaTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  signed: "bg-critical/10 text-critical",
  costly: "bg-good/10 text-good",
};

/**
 * The one place a change is turned into a direction, a colour and a string.
 *
 * Before this there were four hand-rolled copies (market-strip's `Delta`,
 * kpi-strip's inline pill, fuel-energy's `DeltaPill` and `Change`), and they
 * had already drifted: two of them coloured a flat 0% and two did not.
 *
 * `pct === null` prints an em dash with a stated reason rather than a 0%. The
 * distinction is load-bearing on this page -- a pair the 15-minute cron
 * started recording an hour ago genuinely has no day-over-day change, and
 * printing "%0,0" would be a fabrication, not a rounding.
 */
export function Delta({
  pct,
  tone = "neutral",
  form = "bare",
  /** A "1g" / "1h" / "25→26T" prefix. Rendered in muted weight so the window
   * reads as a label and the number as the reading. */
  scope,
  /** Overrides the formatted percentage -- for a percentage-POINT change,
   * where "+0,5pp" is the honest unit and "+%0,5" would be wrong. */
  valueLabel,
  emptyTitle = "Yeterli geçmiş henüz yok",
  className,
}: {
  pct: number | null;
  tone?: DeltaTone;
  form?: DeltaForm;
  scope?: string;
  valueLabel?: string;
  emptyTitle?: string;
  className?: string;
}) {
  if (pct === null) {
    return (
      <span
        title={emptyTitle}
        className={cn("text-[11px] text-muted-foreground/70 tabular-nums", className)}
      >
        {scope ? `${scope} ` : ""}—
      </span>
    );
  }

  const flat = pct === 0;
  const up = pct > 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  // A flat reading is never a judgement: nothing happened, so nothing is good
  // or bad about it. Same rule in both forms.
  const colour = flat
    ? form === "pill"
      ? "bg-muted text-muted-foreground"
      : "text-muted-foreground"
    : form === "pill"
      ? (up ? PILL_UP : PILL_DOWN)[tone]
      : (up ? TONE_UP : TONE_DOWN)[tone];

  if (form === "arrow") {
    const direction = flat ? "flat" : up ? "up" : "down";
    return (
      // No number, and no `scope` either: the caller is printing the reading
      // itself, in its own unit, immediately beside this.
      <span className={cn("flex items-center", colour, className)}>
        <Icon className="size-2.5 shrink-0" aria-hidden />
        <span className="sr-only">{DIRECTION_TR[direction]}</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "flex items-center gap-px text-[11px] font-semibold tabular-nums",
        form === "pill" && "w-fit rounded-full px-1.5 py-0.5",
        colour,
        className,
      )}
    >
      {scope && <span className="font-normal text-muted-foreground">{scope}</span>}
      <Icon className="size-2.5 shrink-0" aria-hidden />
      {valueLabel ?? formatSignedPct(pct)}
    </span>
  );
}
