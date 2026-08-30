import type { RiskCountry, RiskItem } from "@/lib/types";

/** One risk signal, overridable field by field.
 *
 * Test-only, and in `__fixtures__/` so nothing in the app can import it by
 * accident. The defaults describe the THIN shape -- no summary, no airports, no
 * confidence, a single member -- because that is what most production rows
 * actually look like: the enrichment pass often produces a headline and a
 * country and nothing else. A fixture that defaulted to fully-populated would
 * let a component that crashes on a null summary pass every test. */
export function riskItem(overrides: Partial<RiskItem> = {}): RiskItem {
  return {
    id: overrides.id ?? "00000000-0000-0000-0000-000000000001",
    headline: "Rodos'ta orman yangını: tahliye sürüyor",
    url: "https://example.com/haber",
    source_name: "Havayolu 101",
    published_at: "2026-08-28T08:00:00Z",
    risk_type: "wildfire",
    risk_family: "natural",
    risk_type_label_tr: "Yangın",
    severity: "high",
    country: "Greece",
    city: "Rhodes",
    region: "europe",
    is_fresh: false,
    source_count: 1,
    summary_tr: null,
    confidence_score: null,
    corroborating_source_count: null,
    first_reported_at: "2026-08-28T08:00:00Z",
    last_reported_at: "2026-08-28T08:00:00Z",
    is_updated: false,
    airports: [],
    aviation_link: "indirect",
    members: [
      {
        title: "Rodos'ta orman yangını",
        url: "https://example.com/haber",
        source_name: "Havayolu 101",
        source_tier: "trade",
        published_at: "2026-08-28T08:00:00Z",
      },
    ],
    members_truncated: false,
    ...overrides,
  };
}

/** A country group whose count/score/severity split are DERIVED from its
 * items, so a fixture can never claim a score its own items do not add up to
 * -- which is the exact bug filterRiskCountries exists to prevent. */
export function riskCountry(country: string, items: RiskItem[]): RiskCountry {
  const counts = { high: 0, medium: 0, low: 0 };
  let score = 0;
  for (const item of items) {
    if (item.severity in counts) counts[item.severity as keyof typeof counts] += 1;
    score += item.severity === "high" ? 3 : item.severity === "medium" ? 2 : 1;
  }
  return {
    country,
    region: items[0]?.region ?? null,
    count: items.length,
    score,
    severity_counts: counts,
    items,
  };
}
