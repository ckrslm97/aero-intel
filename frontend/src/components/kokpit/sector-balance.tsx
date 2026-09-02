import { Delta } from "@/components/ui/delta";
import type { AnnualSeries, AnnualSeriesBoardOut, EnergyBoardOut } from "@/lib/types";

export interface BalanceRow {
  key: string;
  label: string;
  /** The number, already formatted with its own unit. "—" when the inputs are
   * not there. */
  value: string;
  /** Sign of the move, for the arrow. null leaves the arrow off entirely. */
  pct: number | null;
  /** Which source and which period this row was computed from. Printed under
   * the row, not hidden in a tooltip: the four rows come from two different
   * publishers on two different clocks and a reader must be able to see that. */
  chip: string;
  /** Why the row is empty, where it is. */
  title?: string;
}

function lastTwo(series: AnnualSeries | undefined): [{ year: number; value: number }, { year: number; value: number }] | null {
  const points = series?.points ?? [];
  if (points.length < 2) return null;
  return [points[points.length - 2], points[points.length - 1]];
}

/** Year-on-year growth in percent, or null when the pair is not there. */
function yoy(series: AnnualSeries | undefined): { pct: number; from: number; to: number } | null {
  const pair = lastTwo(series);
  if (!pair) return null;
  const [previous, latest] = pair;
  if (!previous.value) return null;
  return {
    pct: ((latest.value - previous.value) / previous.value) * 100,
    from: previous.year,
    to: latest.year,
  };
}

function signedPoints(diff: number, digits = 1): string {
  const sign = diff > 0 ? "+" : diff < 0 ? "-" : "";
  return `${sign}${Math.abs(diff).toFixed(digits).replace(".", ",")}pp`;
}

const EMPTY = "yeterli yıllık nokta yok";

/** A scissor: the difference between two growth rates, in percentage POINTS.
 * Demand growing 2,1% while capacity grows 1,5% is a +0,6 POINT gap; calling
 * it "+%0,6" would name a third, different quantity. */
function gapRow(
  key: string,
  label: string,
  a: AnnualSeries | undefined,
  b: AnnualSeries | undefined,
): BalanceRow {
  const left = yoy(a);
  const right = yoy(b);
  if (!left || !right) {
    return { key, label, value: "—", pct: null, chip: "IATA · yıllık", title: EMPTY };
  }
  const diff = left.pct - right.pct;
  return {
    key,
    label,
    value: signedPoints(diff),
    pct: diff,
    chip: `IATA · yıllık · ${String(left.from).slice(2)}→${String(left.to).slice(2)}`,
  };
}

/**
 * Four DERIVED relationships between the industry series -- and deliberately
 * not a composite score.
 *
 * WHY THERE IS NO "AVIATION HEALTH 0-100" HERE
 * --------------------------------------------
 * The owner asked for a health gauge "if the available data meaningfully
 * supports one". It does not. Such a number would have to blend a 15-minute FX
 * reading with a series IATA revises twice a year, under weights nobody in this
 * system can cite; `cockpit_signals_service.py`'s own docstring already refuses
 * the same blend for the same reason. A number that looks precise and means
 * nothing is worse than no number, because it is the one a reader would quote.
 *
 * WHY THESE FOUR ROWS AND NOT FOUR RESTATED LEVELS
 * -----------------------------------------------
 * Each row produces a fact that appears NOWHERE ELSE on the page. Market Pulse
 * shows demand and capacity separately; only this block shows the gap between
 * them. The KPI cards show RASK and CASK separately; only this block shows the
 * unit margin between them narrowing from 0,65 to 0,42. A block that merely
 * repeated the levels above it would be the duplication this redesign removes.
 *
 * All four are computed here, in the client, from props the page already
 * fetched. No new request.
 */
export function buildBalanceRows(
  annual: AnnualSeriesBoardOut | null,
  energy: EnergyBoardOut | null,
): BalanceRow[] {
  const byKey = new Map((annual?.series ?? []).map((entry) => [entry.metric_key, entry]));
  const rows: BalanceRow[] = [
    gapRow("demand_capacity", "Talep–Kapasite makası", byKey.get("rpk"), byKey.get("ask")),
    gapRow(
      "revenue_traffic",
      "Gelir–Trafik makası",
      byKey.get("total_aviation_revenue_ytd"),
      byKey.get("rpk"),
    ),
  ];

  // --- unit margin -------------------------------------------------------
  // RASK and CASK are compared only on years BOTH of them have. `cask` is
  // currently missing its 2025 point (an upstream de-duplication bug, see D3
  // in the design spec), so the honest comparison is 2024 vs 2026T -- and the
  // chip says exactly which years were used rather than letting the reader
  // assume consecutive ones.
  const rask = byKey.get("rask");
  const cask = byKey.get("cask");
  const caskByYear = new Map((cask?.points ?? []).map((point) => [point.year, point.value]));
  const shared = (rask?.points ?? [])
    .filter((point) => caskByYear.has(point.year))
    .map((point) => ({
      year: point.year,
      margin: point.value - (caskByYear.get(point.year) as number),
    }));

  if (shared.length >= 2) {
    const latest = shared[shared.length - 1];
    const previous = shared[shared.length - 2];
    rows.push({
      key: "unit_margin",
      label: "Birim marj (RASK−CASK)",
      value: latest.margin.toFixed(2).replace(".", ","),
      pct: latest.margin - previous.margin,
      chip: `IATA · yıllık · ${previous.year}: ${previous.margin.toFixed(2).replace(".", ",")}`,
    });
  } else if (shared.length === 1) {
    rows.push({
      key: "unit_margin",
      label: "Birim marj (RASK−CASK)",
      value: shared[0].margin.toFixed(2).replace(".", ","),
      pct: null,
      chip: `IATA · yıllık · ${shared[0].year}`,
      title: "Karşılaştırılacak ikinci ortak yıl yok",
    });
  } else {
    rows.push({
      key: "unit_margin",
      label: "Birim marj (RASK−CASK)",
      value: "—",
      pct: null,
      chip: "IATA · yıllık",
      title: "RASK ve CASK'ın ortak bir yılı yok",
    });
  }

  // --- fuel position -----------------------------------------------------
  // The one live row in the block, and the only one whose chip does not say
  // "yıllık". A percentile, not a price: "where today's Brent sits inside its
  // own last year of closes" is the question a cost base raises.
  const brent = (energy?.metrics ?? []).find((metric) => metric.metric_key === "oil_price");
  const percentile = brent?.percentile_1y ?? null;
  rows.push({
    key: "fuel_position",
    label: "Yakıt maliyet konumu",
    value: percentile === null ? "—" : `%${Math.round(percentile)} dilim`,
    pct: null,
    chip: "Yahoo · canlı · 1 yıl",
    title: percentile === null ? "1 yıllık yakıt serisi yeterli değil" : undefined,
  });

  return rows;
}

export function SectorBalance({
  annual,
  energy,
}: {
  annual: AnnualSeriesBoardOut | null;
  energy: EnergyBoardOut | null;
}) {
  const rows = buildBalanceRows(annual, energy);

  return (
    <div className="flex h-full flex-col gap-2 rounded-lg border border-border bg-card/60 px-3 py-2.5">
      <ul className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <li key={row.key} className="flex flex-col gap-px" title={row.title}>
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {row.label}
              </span>
              {/* Arrow only. These rows are percentage-POINT gaps and a
                  cents-per-ASK margin, and `row.value` beside this already
                  prints the number in that unit; a second, percent-formatted
                  copy would be a different and untrue quantity. */}
              {row.pct !== null && <Delta pct={row.pct} tone="signed" form="arrow" />}
              <span className="shrink-0 font-mono text-[13px] tabular-nums">{row.value}</span>
            </div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
              {row.chip}
            </span>
          </li>
        ))}
      </ul>
      {/* Not removable. The block exists because a single score cannot be built
          honestly, and a reader who does not know that will ask for one. */}
      <p className="mt-auto border-t border-border pt-1.5 text-[10px] leading-relaxed text-muted-foreground">
        Tek bileşik sağlık skoru üretilmez — sürücüler farklı kaynak ve dönemlerden gelir.
      </p>
    </div>
  );
}
