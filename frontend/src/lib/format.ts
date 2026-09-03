const compactFormatter = new Intl.NumberFormat("tr-TR", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatCompactNumber(value: number): string {
  return compactFormatter.format(value);
}

/** A movement in POINTS, for a metric that is already a percentage.
 *
 * A load factor going 83.0 -> 83.4 rose 0.4 points; rendering that same move
 * as "+0.5%" (its percent form, 0.48) prints a number nobody in revenue
 * management would recognise, under the unit they do. The backend sends
 * exactly one of `delta_pct` / `delta_points` per metric so a surface cannot
 * pick the wrong one -- see KpiOut in lib/types.ts. */
export function formatDeltaPoints(deltaPoints: number): string {
  const sign = deltaPoints > 0 ? "+" : "";
  // Turkish separator, like every other number this page prints. Market
  // Pulse's own point pill already read "+0,5pp"; a detail page answering
  // "+0.4 puan" for the same kind of move is the same figure in two
  // vocabularies, one of them not the reader's.
  return `${sign}${deltaPoints.toFixed(1).replace(".", ",")} puan`;
}

const rateFormatters = new Map<number, Intl.NumberFormat>();

/** A rate or price with Turkish separators: 41.7231 -> "41,72".
 *
 * Kokpit's strip, FX board and forecast table all print rates, and before this
 * each did its own `toFixed()` -- which renders "41.7231" with an English
 * decimal point in a page whose every other number is Turkish-separated.
 *
 * `digits` is a parameter rather than a constant because the right precision
 * genuinely differs: two decimals for a price or a TRY rate, four for a cross
 * where the fourth digit is the one that moves (EUR/GBP at 0,8570).
 */
export function formatRate(value: number, digits = 2): string {
  let formatter = rateFormatters.get(digits);
  if (!formatter) {
    formatter = new Intl.NumberFormat("tr-TR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    rateFormatters.set(digits, formatter);
  }
  return formatter.format(value);
}

/* --- one metric, one precision ------------------------------------------ */

/** Metric keys for a currency cross. `kpi_service.py` names every FX pair
 * `fx_<base>_<quote>` and the unit column carries only the QUOTE currency
 * ("TRY", "USD"), so the unit alone cannot tell a rate from a price -- the key
 * is the only discriminator on the wire. */
const FX_METRIC_PREFIX = "fx_";

/** Below this a cross is quoted to four decimals, at or above it to two.
 *
 * EUR/USD trades at 1,0850 and its fourth decimal is the one that moves;
 * USD/TRY at 41,72 has no meaningful fourth. The FX board and Market Pulse
 * both already applied exactly this cut inline -- this is that rule, named. */
const FX_FOUR_DECIMAL_BELOW = 10;

/** Units whose second decimal is meaningful: percents, cents and money prices.
 *
 * A predicate over the unit's SHAPE rather than a fixed set, so a unit this
 * app grows later ("¢/ASK-km", "$/gal") is precise by construction instead of
 * silently falling through to compact notation -- which renders 8,63¢ as "8,6"
 * and Brent's 68,40 $/bbl as "68,4".
 *
 * A money price is in the set because cents are part of a quoted price. A
 * COUNT is not, however large its unit word ("USD milyar", "yolcu"): those are
 * read as magnitudes and compact notation is the honest rendering of them.
 */
function isPreciseUnit(unit: string | null | undefined): boolean {
  if (!unit) return false;
  return unit === "%" || unit.startsWith("¢") || unit.startsWith("$");
}

/** THE precision rule for a KPI value -- every surface calls this one.
 *
 * /kpi/fx_eur_usd printed "1,1" (compact notation, one fraction digit) for the
 * same reading Kokpit printed as "1,0850", and the KPI strip and Market Pulse
 * each carried their own private copy of the "percent and cents keep two
 * decimals" rule. One number rendered three ways is three chances for a reader
 * to conclude the surfaces are reading different data.
 *
 * Three cases, in the order they are decided:
 *
 *   * an FX cross      -- four decimals below 10, two at or above it
 *   * a %, ¢ or $ metric -- two decimals, never compacted
 *   * everything else  -- compact ("1,5 Mn"), because a passenger count is
 *                         read as a magnitude and not to the unit
 *
 * The value is returned WITHOUT its unit: "%" sits before the number in
 * Turkish and after it in the detail page's layout, so placement stays with
 * the caller that knows the layout.
 */
export function formatMetricValue(
  value: number,
  unit?: string | null,
  metricKey?: string | null,
): string {
  if (metricKey?.startsWith(FX_METRIC_PREFIX)) {
    return formatRate(value, Math.abs(value) < FX_FOUR_DECIMAL_BELOW ? 4 : 2);
  }
  if (isPreciseUnit(unit)) return formatRate(value, 2);
  return formatCompactNumber(value);
}

/** A percent with an explicit sign and Turkish separators: "+%2,4" / "-%1,8".
 * The sign is what makes a delta pill readable at a glance, and Turkish puts
 * the % before the number -- both were being hand-rolled per component. */
export function formatSignedPct(deltaPct: number, digits = 1): string {
  const sign = deltaPct > 0 ? "+" : deltaPct < 0 ? "-" : "";
  return `${sign}%${Math.abs(deltaPct).toFixed(digits).replace(".", ",")}`;
}

/** UTC HH:MM of a reading, or null for a missing/unparseable timestamp.
 *
 * Every "canlı" claim on Kokpit is stamped with the reading's OWN time, never
 * with render time, and three surfaces (the header, the Market Pulse cells,
 * the FX table's row titles) need the same string. It was `utcTimeLabel` in
 * market-strip.tsx, which is being deleted; the rule outlives the component.
 */
export function formatUtcTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("tr-TR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "2 sa önce" -- coarse, deliberately.
 *
 * The signal board's ZAMAN column and the alert rows want elapsed time, not a
 * date. Precision stops at the day because the underlying `detected_at` is a
 * detection time, not an event time, and minute-level precision on it would
 * claim more than the pipeline knows.
 *
 * `relativeTimeTr` in lib/campaigns.ts is the same function under its older
 * name and now delegates here: seven call sites already import it from there,
 * and two identical implementations is exactly the duplication this redesign
 * is removing.
 */
export function formatRelativeTr(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((now - then) / 60_000);
  if (minutes < 1) return "az önce";
  if (minutes < 60) return `${minutes} dk önce`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} sa önce`;
  return `${Math.floor(hours / 24)} gün önce`;
}
