import { describe, expect, it } from "vitest";

import { riskCountry, riskItem } from "@/lib/__fixtures__/risk";
import {
  aviationLinkLabel,
  buildRiskTrendSeries,
  confidenceBand,
  coverageBadge,
  EMPTY_RISK_FILTERS,
  filterRiskCountries,
  liveFeedItems,
  riskSourceTierLabel,
  riskTypeBreakdown,
  UNKNOWN_COUNTRY,
} from "@/lib/risk";

const filters = (overrides: Partial<typeof EMPTY_RISK_FILTERS> = {}) => ({
  ...EMPTY_RISK_FILTERS,
  ...overrides,
});

describe("coverageBadge", () => {
  it("says nothing about the event, only about the coverage", () => {
    // The words matter as much as the logic here: this data has no lifecycle,
    // so a badge reading "Aktif" or "Sürüyor" would be a claim with no source.
    expect(coverageBadge({ is_fresh: true, is_updated: false })?.label).toBe("Yeni");
    expect(coverageBadge({ is_fresh: false, is_updated: true })?.label).toBe("Güncellendi");
  });

  it("prefers Yeni when the backend somehow flags both", () => {
    // The two are mutually exclusive by construction (is_fresh means the first
    // telling is inside 24h, is_updated means it is not), but a UI that renders
    // two badges on one card because the API contradicted itself is worse than
    // one that picks.
    expect(coverageBadge({ is_fresh: true, is_updated: true })?.tone).toBe("new");
  });

  it("renders nothing for the ordinary older signal", () => {
    expect(coverageBadge({ is_fresh: false, is_updated: false })).toBeNull();
  });
});

describe("aviationLinkLabel", () => {
  it("badges only the direct link, and never as an impact claim", () => {
    const direct = aviationLinkLabel("direct");
    expect(direct?.label).toBe("Havacılık bağlantılı");
    // The disclaimer is the point of the tooltip -- "named in the article" is
    // not "flights were affected", and this product has no data for the second.
    expect(direct?.title).toContain("Uçuşların etkilendiği anlamına gelmez");
  });

  it("shows nothing at all for indirect signals", () => {
    // Most signals are indirect; a badge on the majority is noise.
    expect(aviationLinkLabel("indirect")).toBeNull();
  });
});

describe("confidenceBand", () => {
  it("maps the score onto the app's existing three bands", () => {
    expect(confidenceBand(0.9)).toBe("high");
    expect(confidenceBand(0.75)).toBe("high");
    expect(confidenceBand(0.74)).toBe("medium");
    expect(confidenceBand(0.5)).toBe("medium");
    expect(confidenceBand(0.49)).toBe("low");
  });

  it("returns no band at all when there is no score", () => {
    // "We did not compute this" and "we computed this and it came out weak"
    // are different facts; only the second is a judgement about the story.
    expect(confidenceBand(null)).toBeNull();
  });
});

describe("riskSourceTierLabel", () => {
  it("labels the five article tiers, not the campaign page's three", () => {
    expect(riskSourceTierLabel("regulator")).toBe("Düzenleyici");
    expect(riskSourceTierLabel("agency")).toBe("Ajans");
    expect(riskSourceTierLabel("aggregator")).toBe("Toplayıcı");
    expect(riskSourceTierLabel(null)).toBe("Bilinmiyor");
    // An unknown tier prints itself rather than disappearing.
    expect(riskSourceTierLabel("brand-new-tier")).toBe("brand-new-tier");
  });
});

describe("filterRiskCountries", () => {
  const greece = riskCountry("Greece", [
    riskItem({ id: "g1", severity: "high", risk_type: "wildfire", risk_family: "natural" }),
    riskItem({
      id: "g2",
      severity: "low",
      risk_type: "storm",
      risk_family: "natural",
      risk_type_label_tr: "Fırtına",
      headline: "Ege'de fırtına uyarısı",
      city: "Athens",
      is_fresh: true,
    }),
  ]);
  const egypt = riskCountry("Egypt", [
    riskItem({
      id: "e1",
      severity: "medium",
      risk_type: "attack",
      risk_family: "conflict",
      risk_type_label_tr: "Saldırı",
      headline: "Kahire'de saldırı",
      country: "Egypt",
      city: "Cairo",
      region: "africa",
      source_name: "Reuters",
      is_updated: true,
    }),
  ]);
  const all = [greece, egypt];

  it("recomputes each country's score for the FILTERED set", () => {
    // The whole reason this is not "pass the server's numbers through": a hot
    // spot ranking still scoring on all of Greece while the list below shows
    // one storm would be a page contradicting itself.
    const [only] = filterRiskCountries(all, filters({ severity: "low" }));
    expect(only.country).toBe("Greece");
    expect(only.count).toBe(1);
    expect(only.score).toBe(1);
    expect(only.severity_counts).toEqual({ high: 0, medium: 0, low: 1 });
  });

  it("drops countries with nothing left rather than showing empty sections", () => {
    expect(filterRiskCountries(all, filters({ family: "conflict" })).map((c) => c.country)).toEqual(
      ["Egypt"],
    );
  });

  it("treats the two flow toggles as OR, not AND", () => {
    // A signal cannot be both new and updated, so an AND would always be empty.
    const both = filterRiskCountries(all, filters({ onlyNew: true, onlyUpdated: true }));
    expect(both.flatMap((c) => c.items).map((i) => i.id).sort()).toEqual(["e1", "g2"]);
  });

  it("searches headline, place and source together", () => {
    expect(
      filterRiskCountries(all, filters({ search: "reuters" })).flatMap((c) => c.items).map((i) => i.id),
    ).toEqual(["e1"]);
    expect(
      filterRiskCountries(all, filters({ search: "kahire" })).flatMap((c) => c.items).map((i) => i.id),
    ).toEqual(["e1"]);
  });

  it("folds Turkish case so İSTANBUL and istanbul meet", () => {
    // The default lowercase maps "İ" to i + combining dot, and the two never
    // match. Every search over Turkish city names would silently miss.
    const istanbul = [
      riskCountry("Turkey", [riskItem({ id: "t1", city: "İstanbul", headline: "İSTANBUL'da sel" })]),
    ];
    expect(filterRiskCountries(istanbul, filters({ search: "istanbul" }))).toHaveLength(1);
    expect(filterRiskCountries(istanbul, filters({ search: "İSTANBUL" }))).toHaveLength(1);
  });

  it("keeps the unplaced bucket last however high it scores", () => {
    const unplaced = riskCountry(UNKNOWN_COUNTRY, [
      riskItem({ id: "u1", severity: "high" }),
      riskItem({ id: "u2", severity: "high" }),
      riskItem({ id: "u3", severity: "high" }),
    ]);
    const ordered = filterRiskCountries([unplaced, ...all], filters());
    expect(ordered.at(-1)?.country).toBe(UNKNOWN_COUNTRY);
  });
});

describe("liveFeedItems", () => {
  it("orders by the newest coverage, not by the primary article's own date", () => {
    // A three-day-old story that just got a fourth article IS the newest thing
    // in the feed; ordering by published_at would bury it.
    const rows = liveFeedItems([
      riskCountry("Greece", [
        riskItem({
          id: "old-story-new-article",
          published_at: "2026-08-25T08:00:00Z",
          last_reported_at: "2026-08-29T20:00:00Z",
        }),
      ]),
      riskCountry("Egypt", [
        riskItem({
          id: "newer-story",
          published_at: "2026-08-28T08:00:00Z",
          last_reported_at: "2026-08-28T08:00:00Z",
        }),
      ]),
    ]);
    expect(rows.map((r) => r.item.id)).toEqual(["old-story-new-article", "newer-story"]);
  });

  it("falls back to published_at when no coverage span was served", () => {
    const rows = liveFeedItems([
      riskCountry("Greece", [
        riskItem({ id: "a", last_reported_at: null, published_at: "2026-08-20T08:00:00Z" }),
        riskItem({ id: "b", last_reported_at: null, published_at: "2026-08-27T08:00:00Z" }),
      ]),
    ]);
    expect(rows.map((r) => r.item.id)).toEqual(["b", "a"]);
  });
});

describe("riskTypeBreakdown", () => {
  it("counts the visible set and marks the high-severity share", () => {
    const rows = riskTypeBreakdown([
      riskCountry("Greece", [
        riskItem({ id: "1", risk_type: "wildfire", severity: "high" }),
        riskItem({ id: "2", risk_type: "wildfire", severity: "low" }),
        riskItem({ id: "3", risk_type: "storm", risk_type_label_tr: "Fırtına", severity: "high" }),
      ]),
    ]);
    expect(rows).toEqual([
      { type: "wildfire", label: "Yangın", count: 2, high: 1 },
      { type: "storm", label: "Fırtına", count: 1, high: 1 },
    ]);
  });
});

describe("buildRiskTrendSeries", () => {
  const today = new Date("2026-08-30T11:00:00Z");

  it("zero-fills the days the API omitted", () => {
    // The API leaves empty days out because an absent day is not a measured
    // zero -- but an axis with holes would draw a quiet week as one wide bar.
    const series = buildRiskTrendSeries(
      [{ day: "2026-08-30", family: "natural", severity: "high", count: 2 }],
      3,
      today,
    );
    expect(series.days).toEqual(["2026-08-28", "2026-08-29", "2026-08-30"]);
    expect(series.natural).toEqual([0, 0, 2]);
    expect(series.conflict).toEqual([0, 0, 0]);
  });

  it("counts high severity into its own line without unstacking the families", () => {
    // High severity is a SUBSET of the two families; it rides a line over the
    // stack rather than a third bar, which would double-count those articles.
    const series = buildRiskTrendSeries(
      [
        { day: "2026-08-30", family: "natural", severity: "high", count: 2 },
        { day: "2026-08-30", family: "conflict", severity: "low", count: 1 },
      ],
      1,
      today,
    );
    expect(series.natural).toEqual([2]);
    expect(series.conflict).toEqual([1]);
    expect(series.high).toEqual([2]);
  });

  it("ignores points outside the drawn window", () => {
    const series = buildRiskTrendSeries(
      [{ day: "2026-01-01", family: "natural", severity: "low", count: 9 }],
      2,
      today,
    );
    expect(series.natural).toEqual([0, 0]);
  });
});
