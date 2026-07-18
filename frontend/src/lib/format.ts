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

/** Fund price/NAV: USD to 2dp, TRY to 4dp (TEFAS NAVs are small per-share
 * numbers where the 4th decimal is meaningful). */
export function formatFundValue(value: number, currency: string): string {
  const digits = currency === "USD" ? 2 : 4;
  const symbol = currency === "USD" ? "$" : currency === "TRY" ? "₺" : "";
  return `${symbol}${value.toLocaleString("tr-TR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function formatPercent(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}%${value.toFixed(digits)}`;
}
