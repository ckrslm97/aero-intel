const compactFormatter = new Intl.NumberFormat("en-US", {
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
