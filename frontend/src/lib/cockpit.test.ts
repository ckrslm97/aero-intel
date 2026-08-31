import { describe, expect, it } from "vitest";

import {
  forecastBuckets,
  forecastSplitIndex,
  freshnessOf,
  HIGH_IMPACT_IMPORTANCE,
  latestAsOf,
  LIVE_WINDOW_MINUTES,
  MEDIAN_MIN_INSTITUTIONS,
  sentimentTotals,
  signalLevelStyle,
  splitForecast,
  toFeedRow,
  topByImportance,
  type FeedRow,
} from "./cockpit";
import type { AnnualPoint, ArticleOut, FxForecastOut } from "./types";

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

  it("carries the raw importance and severity through, unenriched as null", () => {
    // "no enrichment at all" and "scored zero" must stay distinguishable: only
    // the first is allowed to sink a row silently in topByImportance.
    expect(toFeedRow(article()).importance).toBe(0.4);
    expect(toFeedRow(article({ importance_score: 0 })).importance).toBe(0);
    expect(toFeedRow(article({}, { enrichment: null })).importance).toBeNull();
    expect(toFeedRow(article({ risk_severity: "medium" })).riskSeverity).toBe("medium");
    expect(toFeedRow(article({}, { enrichment: null })).riskSeverity).toBeNull();
  });

  describe("topByImportance", () => {
    const row = (id: string, importance: number | null): FeedRow => ({
      id,
      headline: id,
      url: `https://example.test/${id}`,
      category: "general",
      region: null,
      publishedAt: null,
      sourceName: "Reuters",
      highImpact: false,
      sentiment: null,
      importance,
      riskSeverity: null,
    });

    it("ranks by the enrichment's own score, most important first", () => {
      const ranked = topByImportance([row("a", 0.3), row("b", 0.9), row("c", 0.6)]);
      expect(ranked.map((entry) => entry.id)).toEqual(["b", "c", "a"]);
    });

    it("takes only the requested count", () => {
      const ranked = topByImportance(
        [row("a", 0.3), row("b", 0.9), row("c", 0.6), row("d", 0.7)],
        3,
      );
      expect(ranked).toHaveLength(3);
      expect(ranked.map((entry) => entry.id)).toEqual(["b", "d", "c"]);
    });

    it("sorts unenriched stories last but never drops them", () => {
      const ranked = topByImportance([row("unenriched", null), row("scored", 0.1)]);
      expect(ranked.map((entry) => entry.id)).toEqual(["scored", "unenriched"]);
      expect(ranked).toHaveLength(2);
    });

    it("does not mutate the caller's array", () => {
      const input = [row("a", 0.1), row("b", 0.9)];
      topByImportance(input);
      expect(input.map((entry) => entry.id)).toEqual(["a", "b"]);
    });
  });
});

describe("sentimentTotals", () => {
  const rows = [
    { category: "network", positive: 3, neutral: 5, negative: 1 },
    { category: "fleet", positive: 2, neutral: 4, negative: 6 },
  ];

  it("sums the per-category counts the insights endpoint returns", () => {
    const totals = sentimentTotals(rows);
    expect(totals).toEqual({ positive: 5, neutral: 9, negative: 7, total: 21 });
  });

  it("returns a zero total rather than a fabricated split for no data", () => {
    // The bar renders "henüz sınıflandırılmış haber yok" off this, never a
    // three-way 33% split of nothing.
    expect(sentimentTotals([]).total).toBe(0);
    expect(sentimentTotals(undefined).total).toBe(0);
  });
});

describe("forecastBuckets", () => {
  const forecast = (overrides: Partial<FxForecastOut> = {}): FxForecastOut => ({
    institution: "Danske Bank",
    currency_pair: "USD/TRY",
    horizon_label: "+12m",
    horizon_months: 12,
    value: 66,
    publication_date: "2026-08-21",
    source_url: "https://example.test/danske",
    note_tr: null,
    target_date: "2027-08-21",
    target_date_basis_tr: "Kurumun kendi vadesi eklendi.",
    ...overrides,
  });

  it("groups by the date a forecast targets and reports the spread", () => {
    const buckets = forecastBuckets([
      forecast({ institution: "A", value: 50, target_date: "2026-12-31" }),
      forecast({ institution: "B", value: 54, target_date: "2026-12-31" }),
    ]);

    expect(buckets).toHaveLength(1);
    expect(buckets[0].min).toBe(50);
    expect(buckets[0].max).toBe(54);
    expect(buckets[0].institutionCount).toBe(2);
  });

  it("draws NO median below three institutions on one date", () => {
    // Two numbers have a midpoint, not a consensus. Drawing one would be the
    // averaging backend/app/ingest/curated_seed.py forbids, moved into a chart.
    const one = forecastBuckets([forecast({ institution: "A", target_date: "2026-12-31" })]);
    expect(one[0].median).toBeNull();

    const two = forecastBuckets([
      forecast({ institution: "A", value: 50, target_date: "2026-12-31" }),
      forecast({ institution: "B", value: 54, target_date: "2026-12-31" }),
    ]);
    expect(two[0].median).toBeNull();
  });

  it("draws the median at exactly three institutions and labels the count", () => {
    const buckets = forecastBuckets([
      forecast({ institution: "A", value: 50, target_date: "2026-12-31" }),
      forecast({ institution: "B", value: 54, target_date: "2026-12-31" }),
      forecast({ institution: "C", value: 61, target_date: "2026-12-31" }),
    ]);

    expect(MEDIAN_MIN_INSTITUTIONS).toBe(3);
    expect(buckets[0].median).toBe(54);
    expect(buckets[0].institutionCount).toBe(3);
  });

  it("counts institutions, not rows -- one bank twice is still one opinion", () => {
    const buckets = forecastBuckets([
      forecast({ institution: "A", value: 50, target_date: "2026-12-31" }),
      forecast({ institution: "A", value: 52, target_date: "2026-12-31", horizon_label: "+4m" }),
      forecast({ institution: "B", value: 54, target_date: "2026-12-31" }),
    ]);

    expect(buckets[0].institutionCount).toBe(2);
    expect(buckets[0].median).toBeNull();
  });

  it("never blends across horizons -- different target dates are different buckets", () => {
    const buckets = forecastBuckets([
      forecast({ institution: "A", value: 50, target_date: "2026-12-31" }),
      forecast({ institution: "B", value: 54, target_date: "2026-12-31" }),
      forecast({ institution: "C", value: 90, target_date: "2027-08-21" }),
    ]);

    expect(buckets.map((bucket) => bucket.targetDate)).toEqual(["2026-12-31", "2027-08-21"]);
    // Three institutions overall, but no single date has three: no median.
    expect(buckets.every((bucket) => bucket.median === null)).toBe(true);
  });

  it("drops rows whose horizon could not be dated, rather than guessing an x", () => {
    const buckets = forecastBuckets([
      forecast({ institution: "A", target_date: "2026-12-31" }),
      forecast({ institution: "B", target_date: null, target_date_basis_tr: null }),
    ]);

    expect(buckets).toHaveLength(1);
    expect(buckets[0].rows).toHaveLength(1);
  });

  it("returns buckets in chronological order", () => {
    const buckets = forecastBuckets([
      forecast({ target_date: "2027-08-21" }),
      forecast({ target_date: "2026-11-15" }),
      forecast({ target_date: "2026-12-31" }),
    ]);
    expect(buckets.map((bucket) => bucket.targetDate)).toEqual([
      "2026-11-15",
      "2026-12-31",
      "2027-08-21",
    ]);
  });
});
