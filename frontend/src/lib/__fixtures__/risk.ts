import type {
  RiskCountry,
  RiskFunnelStage,
  RiskItem,
  RiskQualityOut,
  RiskRejection,
} from "@/lib/types";

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
    // The thin shape again: an ordinary, publishable signal whose headline is
    // whatever the source wrote. "low" and "translated" are states a fixture
    // must ask for, so a component that only ever renders the happy path
    // cannot pass by accident.
    visibility: "normal",
    headline_original: null,
    is_translated: false,
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

/** One funnel stage. Defaults describe an ordinary REJECTING stage, because
 * the interesting states -- the merge at the bottom, the non-rejection drop at
 * `risk_adayi` -- are the ones a component gets wrong, and a fixture must make
 * a test ask for them explicitly. */
export function riskFunnelStage(overrides: Partial<RiskFunnelStage> = {}): RiskFunnelStage {
  return {
    key: "guven",
    label_tr: "Güven kapısı",
    passed: 8,
    dropped: 2,
    reason: "confidence_below_floor",
    reason_counts: { confidence_below_floor: 2 },
    drop_kind: "rejected",
    note_tr: null,
    ...overrides,
  };
}

/** A funnel whose arithmetic CLOSES: each stage's passed + dropped equals the
 * previous stage's passed, exactly as the API guarantees. Written as a derived
 * builder rather than as literals so a fixture can never assert a shape the
 * real payload could not produce. */
export function riskFunnel(
  steps: readonly {
    key: string;
    label: string;
    passed: number;
    reason?: string | null;
    /** For the one stage that rejects for two reasons. Must add up to the
     * stage's own drop, exactly as the API guarantees. */
    reasonCounts?: Record<string, number>;
    dropKind?: string | null;
    note?: string | null;
  }[],
): RiskFunnelStage[] {
  return steps.map((step, index) => {
    const dropped = index === 0 ? 0 : steps[index - 1].passed - step.passed;
    const dropKind = step.dropKind ?? (index === 0 ? null : "rejected");
    return {
      key: step.key,
      label_tr: step.label,
      passed: step.passed,
      dropped,
      reason: step.reason ?? null,
      reason_counts:
        step.reasonCounts ??
        (dropKind === "rejected" && step.reason ? { [step.reason]: dropped } : {}),
      drop_kind: dropKind,
      note_tr: step.note ?? null,
    };
  });
}

/** One rejected candidate. The defaults are the THIN shape again: nothing
 * measured, no other gate failed, no places named -- which is what most rows
 * genuinely look like while the LLM's coverage is partial. */
export function riskRejection(overrides: Partial<RiskRejection> = {}): RiskRejection {
  return {
    article_id: "11111111-1111-1111-1111-111111111111",
    title: "EASA instructs airlines to avoid Gulf airspace",
    url: "https://example.com/easa",
    source_name: "AeroTime",
    source_tier: "trade",
    published_at: "2026-08-28T08:00:00Z",
    reason: "aviation_relevance_low",
    reason_label_tr: "Havacılıkla ilgisiz",
    also_failed: [],
    risk_type: "war",
    risk_severity: "high",
    confidence_score: null,
    corroborating_source_count: null,
    aviation_relevance_score: null,
    aviation_relevance_source: null,
    location_confidence: null,
    detected_country: null,
    detected_city: null,
    mentioned_locations: [],
    ...overrides,
  };
}

/** A quality payload built around a funnel, with the reason counts derived
 * from the stages -- so the filter chips a test renders can never disagree
 * with the funnel it rendered them from. */
export function riskQuality(
  stages: RiskFunnelStage[],
  overrides: Partial<RiskQualityOut> = {},
): RiskQualityOut {
  const counts: Record<string, number> = { outside_window: 0 };
  for (const stage of stages) {
    if (stage.drop_kind === "rejected" && stage.reason) {
      counts[stage.reason] = (counts[stage.reason] ?? 0) + stage.dropped;
    }
  }
  return {
    days: 5,
    generated_at: "2026-08-28T09:00:00Z",
    since: "2026-08-23T09:00:00Z",
    stages,
    rejected_counts: counts,
    reason_labels_tr: {
      outside_window: "Pencere dışında",
      duplicate: "Yinelenen haber",
      not_current_event: "Güncel olay değil",
      confidence_below_floor: "Güven eşiğinin altında",
      aviation_relevance_low: "Havacılıkla ilgisiz",
      location_unresolved: "Konum doğrulanamadı",
      location_conflict: "Konum çelişkili",
    },
    aviation_unscored: 0,
    location_unscored: 0,
    confidence_unscored: 0,
    aviation_by_source: {},
    ...overrides,
  };
}
