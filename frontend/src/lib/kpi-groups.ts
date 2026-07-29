/** How the dashboard splits `GET /kpis` into sections.
 *
 * Deliberately a plain module, not a const inside a `"use client"` file: the
 * dashboard is a server component, and non-component exports from a client
 * module come back as client references on the server, not as real values.
 */

/** Gelir Yönetimi -- the portal's focus section, rendered first. */
export const REVENUE_MANAGEMENT_KEYS = new Set([
  "total_aviation_revenue_ytd",
  "passenger_revenue_ytd",
  "ancillary_revenue_ytd",
  "rask",
  "cask",
  "yield_per_rpk",
  "ask",
  "rpk",
]);

/** Market context (fuel, oil, FX) -- the quiet ticker at the top of the page,
 * deliberately not full KPI cards. */
export const MARKET_KEYS = new Set(["oil_price", "fx_usd_try", "fuel_price"]);

/** The $-denominated revenue lines RevenueOverviewChart plots as bars. Only
 * these three share a unit, so only these three can sit on one bar axis. */
export const REVENUE_BAR_KEYS = [
  "total_aviation_revenue_ytd",
  "passenger_revenue_ytd",
  "ancillary_revenue_ytd",
] as const;
