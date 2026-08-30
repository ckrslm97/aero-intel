import { describe, expect, it } from "vitest";

import {
  freshnessOf,
  forecastSplitIndex,
  HIGH_IMPACT_IMPORTANCE,
  latestAsOf,
  LIVE_WINDOW_MINUTES,
  signalLevelStyle,
  splitForecast,
  toFeedRow,
} from "./cockpit";
import type { AnnualPoint, ArticleOut } from "./types";

const NOW = new Date("2026-08-30T12:00:00Z");
const minutesAgo = (minutes: number) =>
  new Date(NOW.getTime() - minutes * 60_000).toISOString();

describe("freshnessOf", () => {
  it("calls a reading inside the live window live", () => {
    const freshness = freshnessOf(minutesAgo(5), NOW);
    expect(freshness.live).toBe(true);
    expect(freshness.label).toBe("Canlı");
  });

  it("stops claiming live the moment the window is exceeded", () => {
    expect(freshnessOf(minutesAgo(LIVE_WINDOW_MINUTES), NOW).live).toBe(true);
    expect(freshnessOf(minutesAgo(LIVE_WINDOW_MINUTES + 1), NOW).live).toBe(false);
  });

  it("says how late it is rather than going quiet", () => {
    const freshness = freshnessOf("2026-08-30T09:15:00Z", NOW);
    expect(freshness.live).toBe(false);
    expect(freshness.label).toContain("Gecikmeli");
    expect(freshness.label).toContain("09:15");
  });

  it("says 'Veri yok' rather than inventing a timestamp", () => {
    // The header must never be able to print an unearned freshness claim --
    // that is the whole reason this is computed instead of decorated.
    for (const value of [null, undefined, "not-a-date"]) {
      const freshness = freshnessOf(value, NOW);
      expect(freshness.label).toBe("Veri yok");
      expect(freshness.live).toBe(false);
      expect(freshness.timeLabel).toBeNull();
    }
  });
});

describe("latestAsOf", () => {
  it("picks the newest reading across the board", () => {
    expect(
      latestAsOf([
        { as_of: "2026-08-30T10:00:00Z" },
        { as_of: "2026-08-30T11:45:00Z" },
        { as_of: "2026-08-30T09:00:00Z" },
      ]),
    ).toBe("2026-08-30T11:45:00Z");
  });

  it("is null for an empty board", () => {
    expect(latestAsOf([])).toBeNull();
  });
});

describe("signalLevelStyle", () => {
  it("keeps an unreadable driver neutral rather than green", () => {
    // A tile whose data could not be read must not look like an all-clear.
    expect(signalLevelStyle("unknown").pill).toContain("muted");
    expect(signalLevelStyle("unknown").pill).not.toContain("good");
  });

  it("falls back to the neutral style for a level it has never heard of", () => {
    expect(signalLevelStyle("banana")).toBe(signalLevelStyle("unknown"));
  });

  it("gives warning and critical distinct hues", () => {
    expect(signalLevelStyle("warning").glowVar).toBe("var(--warning)");
    expect(signalLevelStyle("critical").glowVar).toBe("var(--critical)");
  });
});

describe("splitForecast", () => {
  const points: AnnualPoint[] = [
    { year: 2023, value: 1, kind: "actual" },
    { year: 2024, value: 2, kind: "actual" },
    { year: 2025, value: 3, kind: "estimate" },
    { year: 2026, value: 4, kind: "forecast" },
  ];

  it("finds the first year that is no longer history", () => {
    expect(forecastSplitIndex(points)).toBe(2);
  });

  it("draws the last real year in BOTH halves so the dashed tail joins on", () => {
    const { actual, projected } = splitForecast(points);
    expect(actual).toEqual([1, 2, null, null]);
    // 2024 appears again here: without it the dashed segment would start in
    // mid-air with a visible gap where the line changes style.
    expect(projected).toEqual([null, 2, 3, 4]);
  });

  it("leaves an all-actual series entirely solid", () => {
    const solid: AnnualPoint[] = [
      { year: 2023, value: 1, kind: "actual" },
      { year: 2024, value: 2, kind: "actual" },
    ];
    const { actual, projected } = splitForecast(solid);
    expect(actual).toEqual([1, 2]);
    expect(projected).toEqual([null, 2]);
  });

  it("handles a series that is forecast from the very first point", () => {
    const allForecast: AnnualPoint[] = [{ year: 2026, value: 4, kind: "forecast" }];
    const { actual, projected } = splitForecast(allForecast);
    expect(actual).toEqual([null]);
    // split is 0, so there is no preceding real year to join to -- the guard
    // in splitForecast is what stops index -1 leaking a stray point.
    expect(projected).toEqual([null]);
  });
});

describe("toFeedRow", () => {
  const article = (overrides: Partial<ArticleOut["enrichment"]> = {}, rest: Partial<ArticleOut> = {}) =>
    ({
      id: "a1",
      url: "https://example.test/a",
      title: "Original English Title",
      author: null,
      published_at: "2026-08-30T09:00:00Z",
      fetched_at: "2026-08-30T09:05:00Z",
      status: "published",
      source: { id: "s", name: "Reuters", url: "u", category: "wire", trust_weight: 1 },
      enrichment: {
        headline: "English headline",
        summary: "s",
        category: "network",
        subcategory: null,
        region: "europe",
        importance_score: 0.4,
        sentiment: "neutral",
        confidence_score: 0.7,
        corroborating_source_count: 1,
        verified_at: null,
        tags: "",
        headline_tr: "Türkçe başlık",
        summary_tr: null,
        translated_at: "2026-08-30T09:06:00Z",
        is_translated: true,
        risk_severity: null,
        ...overrides,
      },
      reading_time_minutes: 2,
      airlines: [],
      airports: [],
      ...rest,
    }) as ArticleOut;

  it("prefers the Turkish headline", () => {
    expect(toFeedRow(article()).headline).toBe("Türkçe başlık");
  });

  it("falls back through the English headline to the raw title, never inventing one", () => {
    expect(toFeedRow(article({ headline_tr: null })).headline).toBe("English headline");
    expect(toFeedRow(article({ headline_tr: null, headline: "" })).headline).toBe(
      "Original English Title",
    );
    expect(toFeedRow(article({}, { enrichment: null })).headline).toBe("Original English Title");
  });

  it("earns the high-impact badge from a real classification, not from a guess", () => {
    expect(toFeedRow(article()).highImpact).toBe(false);
    expect(toFeedRow(article({ risk_severity: "high" })).highImpact).toBe(true);
    expect(toFeedRow(article({ risk_severity: "medium" })).highImpact).toBe(false);
    expect(
      toFeedRow(article({ importance_score: HIGH_IMPACT_IMPORTANCE })).highImpact,
    ).toBe(false);
    expect(
      toFeedRow(article({ importance_score: HIGH_IMPACT_IMPORTANCE + 0.01 })).highImpact,
    ).toBe(true);
  });

  it("keeps an unclassified article renderable rather than dropping it", () => {
    const row = toFeedRow(article({}, { enrichment: null }));
    expect(row.category).toBe("general");
    expect(row.region).toBeNull();
    expect(row.sentiment).toBeNull();
    expect(row.highImpact).toBe(false);
  });
});
