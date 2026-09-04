/** The Sinyaller page's pure rules, kept out of the components so they can be
 * asserted directly (see signals.test.ts).
 *
 * Everything here is presentation of bands the backend already decided --
 * app/services/signals_service.py owns which stream reaches which kind and how
 * a severity was arrived at. Nothing in this file re-derives a severity, and
 * nothing invents one for a stream that has none.
 */
import { SEVERITY_LADDER } from "@/lib/severity";
import type { SignalKind, SignalOut, SignalSeverity } from "@/lib/types";

/** Display order for the kind chips. Risk and Rakip first because they are the
 * two a desk opens this page for; Piyasa and Finans are context. Mirrors
 * `KIND_ORDER` in backend/app/services/signals_service.py. */
export const KIND_ORDER: readonly SignalKind[] = [
  "risk",
  "competitor",
  "market",
  "financial",
] as const;

/** Worst first -- the order the list is sorted in server-side, restated here
 * so the chip row reads in the same direction the list does. */
export const SEVERITY_ORDER: readonly SignalSeverity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "unknown",
] as const;

/** Severity -> how loudly the card is drawn.
 *
 * DERIVED, not declared. The rungs, their labels, their hues and the rule that
 * `unknown` is neutral rather than green all live in lib/severity.ts, which is
 * the app's single severity ladder. This alias stays because it is the name
 * the Sinyaller components already import; what it must never become again is
 * a SECOND table that can drift from the first one (it was one of six, and the
 * six disagreed -- see the note at the top of lib/severity.ts).
 *
 * Only the top three take a hue. A list where every row is coloured tells a
 * reader nothing about which one to read first -- the same rule
 * kokpit/alert-center.tsx and campaign-alert-strip.tsx already set.
 */
export const SEVERITY_STYLES: Record<
  SignalSeverity,
  { pill: string; dot: string; text: string; glowVar: string }
> = SEVERITY_LADDER;

export function severityStyle(severity: string) {
  return SEVERITY_STYLES[severity as SignalSeverity] ?? SEVERITY_STYLES.unknown;
}

/** What the two chip rows select. `null` on either axis means "no narrowing on
 * this axis", which is what the "Hepsi" chip sets. */
export interface SignalFilters {
  kind: SignalKind | null;
  severity: SignalSeverity | null;
}

export const NO_FILTERS: SignalFilters = { kind: null, severity: null };

/** The rows the current filters keep, in the order the API sent them.
 *
 * Order is deliberately preserved rather than re-sorted: the backend already
 * sorted by severity and then recency (one implementation, so the page and any
 * other consumer agree), and a second client-side sort would be a second
 * chance to disagree with it.
 */
export function filterSignals(rows: SignalOut[], filters: SignalFilters): SignalOut[] {
  return rows.filter(
    (row) =>
      (filters.kind === null || row.kind === filters.kind) &&
      (filters.severity === null || row.severity === filters.severity),
  );
}

/** How many rows each value of one axis holds, counted over the rows the OTHER
 * axis currently keeps.
 *
 * Counting over the already-filtered list would make every chip but the active
 * one read 0 the moment one was pressed -- a chip row that erases its own
 * options. Counting over the whole feed instead would promise rows the other
 * filter has already excluded. Cross-counting is the only version whose
 * numbers a reader can act on.
 */
export function countBy<K extends keyof SignalFilters>(
  rows: SignalOut[],
  axis: K,
  filters: SignalFilters,
): Record<string, number> {
  const otherAxis: keyof SignalFilters = axis === "kind" ? "severity" : "kind";
  const scoped = filterSignals(rows, { ...NO_FILTERS, [otherAxis]: filters[otherAxis] });
  const tally: Record<string, number> = {};
  for (const row of scoped) {
    const value = axis === "kind" ? row.kind : row.severity;
    tally[value] = (tally[value] ?? 0) + 1;
  }
  return tally;
}

/* --- URL round-trip -------------------------------------------------------
 * Modelled on `parseCampaignFilters` / `campaignFiltersToSearchParams` in
 * lib/campaigns.ts. Sinyaller is an early-warning centre, and the message a
 * desk actually sends is "şu an dört kritik risk sinyali var" with a link --
 * a link that has to open on the same two chips the sender had lit.
 */

/** The query-string name of each axis. */
const SIGNAL_PARAM_NAMES: Record<keyof SignalFilters, string> = {
  kind: "kind",
  severity: "severity",
};

/** Filters out of the address bar.
 *
 * A value outside the known set is dropped rather than kept: `?severity=pink`
 * held verbatim would empty the list while both chip rows still read "Hepsi",
 * which looks exactly like a broken build. */
export function parseSignalFilters(params: URLSearchParams): SignalFilters {
  const kind = params.get(SIGNAL_PARAM_NAMES.kind);
  const severity = params.get(SIGNAL_PARAM_NAMES.severity);
  return {
    kind: KIND_ORDER.includes(kind as SignalKind) ? (kind as SignalKind) : null,
    severity: SEVERITY_ORDER.includes(severity as SignalSeverity)
      ? (severity as SignalSeverity)
      : null,
  };
}

/** Filters back into the address bar, onto `base` so unrelated params survive.
 * A cleared axis deletes its key rather than writing an empty one, so an
 * unfiltered page has a clean URL. */
export function signalFiltersToSearchParams(
  filters: SignalFilters,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");
  for (const [axis, name] of Object.entries(SIGNAL_PARAM_NAMES)) {
    const value = filters[axis as keyof SignalFilters];
    if (value) params.set(name, value);
    else params.delete(name);
  }
  return params;
}
