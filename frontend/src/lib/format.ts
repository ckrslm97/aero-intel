const compactFormatter = new Intl.NumberFormat("tr-TR", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatCompactNumber(value: number): string {
  return compactFormatter.format(value);
}

export function formatDelta(deltaPct: number): string {
  const sign = deltaPct > 0 ? "+" : "";
  return `${sign}${deltaPct.toFixed(1)}%`;
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

/** A percent with an explicit sign and Turkish separators: "+%2,4" / "-%1,8".
 * The sign is what makes a delta pill readable at a glance, and Turkish puts
 * the % before the number -- both were being hand-rolled per component. */
export function formatSignedPct(deltaPct: number, digits = 1): string {
  const sign = deltaPct > 0 ? "+" : deltaPct < 0 ? "-" : "";
  return `${sign}%${Math.abs(deltaPct).toFixed(digits).replace(".", ",")}`;
}
