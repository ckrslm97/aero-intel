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
