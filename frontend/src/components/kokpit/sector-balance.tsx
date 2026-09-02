import { Delta } from "@/components/ui/delta";
import type { AnnualSeriesBoardOut } from "@/lib/types";

export interface BalanceRow {
  key: string;
  label: string;
  /** The number, already formatted. "—" when the inputs are not there. */
  value: string;
  /** The unit, printed next to `value` in the page's small sans face. */
  unit: string | null;
  /** Sign of the move, for the arrow. null leaves the arrow off entirely. */
  pct: number | null;
  /** Which source and which years this row was computed from. Printed under
   * the row, not hidden in a tooltip. */
  chip: string;
  /** Why the row is empty, where it is. */
  title?: string;
}

/**
 * ONE derived relationship: the industry's unit margin, RASK minus CASK.
 *
 * WHY ONE ROW AND NOT FOUR
 * ------------------------
 * This block used to carry four: a demand-capacity scissor, a revenue-traffic
 * scissor, this margin, and a fuel percentile. Three of them were arithmetic
 * on two numbers already printed within two hundred pixels of the block:
 *
 *   * demand - capacity  IS the load factor's direction, and Market Pulse's
 *     third cell already prints that move in its own honest unit ("+0,5pp").
 *     Two numbers, one fact, twenty centimetres apart -- and at +0,6pp against
 *     the cell's +0,5pp they were near enough to read as a contradiction.
 *   * revenue - traffic  IS yield's direction, and the KPI strip's GETİRİ card
 *     prints yield's own year-on-year immediately to the left of this block.
 *   * the fuel percentile was fuel's SECOND appearance on the page (the pulse
 *     cell being the first), against an explicit instruction that fuel appear
 *     once. The pulse cell now carries the fuel threshold band instead.
 *
 * The margin is the one that survives, because it is the one that says
 * something the page cannot say anywhere else: RASK and CASK appear as two
 * separate KPI cards, and only their DIFFERENCE shows the industry's cushion
 * narrowing from 0,65 to 0,42 cents per ASK. The row is therefore rendered as
 * a sixth cell of the KPI strip rather than as a panel of its own.
 *
 * WHY THERE IS STILL NO "AVIATION HEALTH 0-100"
 * ---------------------------------------------
 * The owner asked for a health gauge "if the available data meaningfully
 * supports one". It does not: such a number would blend a 15-minute FX reading
 * with a series IATA revises twice a year, under weights nobody in this system
 * can cite, and `cockpit_signals_service.py`'s own docstring refuses the same
 * blend for the same reason. The section caption says so in words.
 *
 * Computed here, in the client, from a prop the page already fetched. No new
 * request.
 */
export function buildBalanceRows(annual: AnnualSeriesBoardOut | null): BalanceRow[] {
  const byKey = new Map((annual?.series ?? []).map((entry) => [entry.metric_key, entry]));
  const rask = byKey.get("rask");
  const cask = byKey.get("cask");

  // "0,42" alone is unreadable beside a percentage and a rate: a reader cannot
  // tell whether it is a percentage, a ratio or a price. It is cents per ASK,
  // which is what both inputs are measured in.
  const marginUnit = rask?.unit ?? cask?.unit ?? null;

  // RASK and CASK are compared only on years BOTH of them have. `cask` is
  // currently missing its 2025 point (an upstream de-duplication bug, D3 in
  // the design spec), so the honest comparison is 2024 vs 2026T -- and the
  // chip says exactly which years were used rather than letting the reader
  // assume consecutive ones. Interpolating the gap is not an option here: a
  // margin invented for a year nobody published is the single most quotable
  // number on this page.
  const caskByYear = new Map((cask?.points ?? []).map((point) => [point.year, point.value]));
  const shared = (rask?.points ?? [])
    .filter((point) => caskByYear.has(point.year))
    .map((point) => ({
      year: point.year,
      margin: point.value - (caskByYear.get(point.year) as number),
    }));

  const label = "Birim marj (RASK−CASK)";

  if (shared.length >= 2) {
    const latest = shared[shared.length - 1];
    const previous = shared[shared.length - 2];
    return [
      {
        key: "unit_margin",
        label,
        value: latest.margin.toFixed(2).replace(".", ","),
        unit: marginUnit,
        pct: latest.margin - previous.margin,
        chip: `IATA · yıllık · ${previous.year}: ${previous.margin.toFixed(2).replace(".", ",")}`,
      },
    ];
  }

  if (shared.length === 1) {
    return [
      {
        key: "unit_margin",
        label,
        value: shared[0].margin.toFixed(2).replace(".", ","),
        unit: marginUnit,
        pct: null,
        chip: `IATA · yıllık · ${shared[0].year}`,
        title: "Karşılaştırılacak ikinci ortak yıl yok",
      },
    ];
  }

  return [
    {
      key: "unit_margin",
      label,
      value: "—",
      unit: null,
      pct: null,
      chip: "IATA · yıllık",
      title: "RASK ve CASK'ın ortak bir yılı yok",
    },
  ];
}

/** The margin cell, shaped like the five KPI cells it sits beside so the row
 * reads as one strip rather than as a strip plus a panel. */
export function SectorBalance({ annual }: { annual: AnnualSeriesBoardOut | null }) {
  const row = buildBalanceRows(annual)[0];

  return (
    <div
      title={row.title ?? `${row.label} · ${row.chip}`}
      className="flex h-full min-h-[104px] flex-col justify-between gap-1 rounded-lg border border-border bg-card/60 px-3 py-2"
    >
      {/* Wraps rather than truncates. This is the one cell label that names
          two series, and "BİRİM MARJ (RASK−CA…" at 375px hides exactly the
          half that says what was subtracted from what. */}
      <span className="shrink-0 text-[10px] font-semibold uppercase leading-tight tracking-wider text-muted-foreground">
        {row.label}
      </span>
      <span className="flex shrink-0 items-baseline gap-1">
        <span className="text-xl font-semibold leading-none tabular-nums">{row.value}</span>
        {row.unit && <span className="truncate text-[10px] text-muted-foreground">{row.unit}</span>}
      </span>
      {/* Arrow only. This row is a cents-per-ASK margin, and `row.value` beside
          it already prints the number in that unit; a second, percent-formatted
          copy would be a different and untrue quantity. */}
      <span className="flex h-4 shrink-0 items-center">
        {row.pct !== null && <Delta pct={row.pct} tone="signed" form="arrow" />}
      </span>
      <span className="shrink-0 truncate text-[10px] uppercase tracking-wider text-muted-foreground">
        {row.chip}
      </span>
    </div>
  );
}
