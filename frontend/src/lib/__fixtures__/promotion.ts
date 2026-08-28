import type { PromotionOut } from "@/lib/types";

/** A fully-populated campaign row, overridable field by field.
 *
 * Test-only, and in `__fixtures__/` so nothing in the app can import it by
 * accident. The defaults describe the *legacy* shape -- no campaign_type, no
 * band, no route -- because that is what ~200 production rows actually look
 * like, and a fixture that defaults to fully-classified would let a filter
 * that silently drops unclassified rows pass every test. */
export function promotion(overrides: Partial<PromotionOut> = {}): PromotionOut {
  return {
    id: overrides.id ?? "00000000-0000-0000-0000-000000000001",
    airline_code: "PC",
    airline_name: "Pegasus Airlines",
    title_tr: "Kuzey Kıbrıs uçuşlarında %40 indirim",
    summary_tr: "",
    discount_pct: 40,
    markets: null,
    sale_starts: null,
    sale_ends: null,
    travel_starts: null,
    travel_ends: null,
    url: "https://example.com/kampanya",
    source_name: "Rakip Kampanya Takibi",
    region: null,
    detected_at: "2026-08-20T09:00:00Z",
    sale_range_tr: "Belirtilmedi",
    travel_range_tr: "Belirtilmedi",
    status: "UNKNOWN",
    campaign_type: null,
    business_class: null,
    route_scope: null,
    ond: null,
    origin_code: null,
    dest_code: null,
    route_json: null,
    confidence_score: null,
    confidence_band: null,
    review_required: null,
    conflict_detected: null,
    classification_reason: null,
    first_seen_at: null,
    last_changed_at: null,
    attrs_json: null,
    evidence_json: null,
    date_flags_json: null,
    version_count: 0,
    source_count: 0,
    ...overrides,
  };
}
