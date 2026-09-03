import { describe, expect, it } from "vitest";

import { riskCountry, riskFunnel, riskItem, riskQuality } from "@/lib/__fixtures__/risk";
import {
  aviationLinkLabel,
  buildRiskFunnel,
  buildRiskTrendSeries,
  confidenceBand,
  coverageBadge,
  EMPTY_RISK_FILTERS,
  filterRiskCountries,
  headlinePresentation,
  liveFeedItems,
  partitionByVisibility,
  rejectionFilterOptions,
  rejectionPlaceLabel,
  riskSourceTierLabel,
  riskTypeBreakdown,
  scoreOrUnscored,
  staleBadge,
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

describe("staleBadge", () => {
  const now = new Date("2026-08-30T12:00:00Z");
  const at = (iso: string | null) =>
    riskItem({ is_fresh: false, is_updated: false, last_reported_at: iso, published_at: iso });

  it("marks a signal nobody has written about in over a week", () => {
    expect(staleBadge(at("2026-08-20T12:00:00Z"), 30, now)?.label).toBe("ESKİ");
  });

  it("says nothing about the event, only about the coverage", () => {
    // Same discipline as coverageBadge. A wildfire can burn for a month with
    // the wires having moved on after day three, and this page has no lifecycle
    // data that could tell the difference.
    expect(staleBadge(at("2026-08-01T12:00:00Z"), 90, now)?.title).toContain(
      "olayın bittiği anlamına gelmez",
    );
  });

  it("leaves the boundary alone -- exactly seven days is not yet old", () => {
    expect(staleBadge(at("2026-08-23T12:00:00Z"), 30, now)).toBeNull();
    expect(staleBadge(at("2026-08-23T11:00:00Z"), 30, now)?.label).toBe("ESKİ");
  });

  it("is drawn only in the wide windows", () => {
    // In a 7g or 14g view almost everything is past the threshold, so the tag
    // would fire on most of the list and carry no information.
    const old = at("2026-08-10T12:00:00Z");
    expect(staleBadge(old, 7, now)).toBeNull();
    expect(staleBadge(old, 14, now)).toBeNull();
    expect(staleBadge(old, 30, now)?.label).toBe("ESKİ");
    expect(staleBadge(old, 90, now)?.label).toBe("ESKİ");
  });

  it("never contradicts a freshness badge", () => {
    // Impossible by arithmetic -- both halves cannot hold -- but a card
    // carrying "Yeni" and "ESKİ" at once would be the worst thing on the page,
    // so the rule is enforced rather than assumed.
    const fresh = riskItem({
      is_fresh: true,
      last_reported_at: "2026-08-01T12:00:00Z",
      published_at: "2026-08-01T12:00:00Z",
    });
    expect(staleBadge(fresh, 90, now)).toBeNull();
    const updated = riskItem({
      is_fresh: false,
      is_updated: true,
      last_reported_at: "2026-08-01T12:00:00Z",
      published_at: "2026-08-01T12:00:00Z",
    });
    expect(staleBadge(updated, 90, now)).toBeNull();
  });

  it("says nothing when there is no date to judge", () => {
    expect(staleBadge(at(null), 90, now)).toBeNull();
  });
});

describe("partitionByVisibility", () => {
  it("splits the weak tail out without reordering either half", () => {
    const { normal, low } = partitionByVisibility([
      riskItem({ id: "a" }),
      riskItem({ id: "b", visibility: "low" }),
      riskItem({ id: "c" }),
      riskItem({ id: "d", visibility: "low" }),
    ]);
    expect(normal.map((i) => i.id)).toEqual(["a", "c"]);
    expect(low.map((i) => i.id)).toEqual(["b", "d"]);
  });

  it("treats an unfamiliar band as a normal signal", () => {
    // A band the backend grows later must render as a signal, not vanish into
    // a collapsed block nobody opens.
    const { normal, low } = partitionByVisibility([riskItem({ id: "x", visibility: "brand-new" })]);
    expect(normal.map((i) => i.id)).toEqual(["x"]);
    expect(low).toEqual([]);
  });
});

describe("headlinePresentation", () => {
  it("offers the source-language original behind a translated headline", () => {
    const shown = headlinePresentation(
      riskItem({
        headline: "Rodos'ta orman yangını: tahliye sürüyor",
        headline_original: "Wildfires force evacuation of Rhodes",
        is_translated: true,
      }),
    );
    expect(shown.text).toBe("Rodos'ta orman yangını: tahliye sürüyor");
    expect(shown.original).toBe("Wildfires force evacuation of Rhodes");
    expect(shown.untranslated).toBe(false);
  });

  it("flags an untranslated headline instead of letting it pass as Turkish", () => {
    const shown = headlinePresentation(
      riskItem({ headline: "Wildfires force evacuation of Rhodes", is_translated: false }),
    );
    expect(shown.untranslated).toBe(true);
    // Nothing to reveal -- the text shown IS the original, and a tooltip
    // repeating the words underneath it is noise a screen reader reads twice.
    expect(shown.original).toBeNull();
  });

  it("does not echo the headline back at itself when the two are the same", () => {
    const shown = headlinePresentation(
      riskItem({ headline: "Aynı başlık", headline_original: "Aynı başlık", is_translated: true }),
    );
    expect(shown.original).toBeNull();
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

describe("buildRiskFunnel", () => {
  const stages = riskFunnel([
    { key: "toplam", label: "Toplam makale", passed: 1000 },
    { key: "risk_adayi", label: "Risk adayı", passed: 100, dropKind: null },
    { key: "guven", label: "Güven kapısı", passed: 50, reason: "confidence_below_floor" },
  ]);

  it("scales every bar against the FIRST stage, not the previous one", () => {
    // A bar scaled to its predecessor makes every stage look like it kept most
    // of what reached it -- which is exactly the impression the funnel exists
    // to correct when 13.906 articles become 9 signals.
    const bars = buildRiskFunnel(stages);
    expect(bars.map((b) => Math.round(b.widthPct))).toEqual([100, 10, 5]);
  });

  it("reports what share of the stage above survived, separately from the width", () => {
    const bars = buildRiskFunnel(stages);
    expect(bars[0].keptPct).toBeNull(); // nothing above the first stage
    expect(bars[1].keptPct).toBe(10);
    expect(bars[2].keptPct).toBe(50);
  });

  it("gives a non-zero stage a visible sliver and a zero stage nothing", () => {
    const bars = buildRiskFunnel(
      riskFunnel([
        { key: "toplam", label: "Toplam", passed: 100000 },
        { key: "kalan", label: "Kalan", passed: 1 },
        { key: "hic", label: "Hiç", passed: 0 },
      ]),
    );
    expect(bars[1].widthPct).toBeGreaterThan(0);
    expect(bars[2].widthPct).toBe(0);
  });

  it("survives an entirely empty window without dividing by zero", () => {
    const bars = buildRiskFunnel(
      riskFunnel([
        { key: "toplam", label: "Toplam", passed: 0 },
        { key: "risk_adayi", label: "Risk adayı", passed: 0, dropKind: null },
      ]),
    );
    expect(bars.map((b) => b.widthPct)).toEqual([0, 0]);
    expect(bars[1].keptPct).toBeNull();
  });
});

describe("rejectionFilterOptions", () => {
  it("orders the reasons the way the rules run, not the way the counts sort", () => {
    // A filter whose options come and go with the data cannot be learned.
    const quality = riskQuality(
      riskFunnel([
        { key: "toplam", label: "Toplam makale", passed: 100 },
        { key: "risk_adayi", label: "Risk adayı", passed: 40, dropKind: null },
        { key: "pencere", label: "Pencere içinde", passed: 30, reason: "outside_window" },
        { key: "guncel", label: "Güncel olay", passed: 20, reason: "not_current_event" },
        { key: "guven", label: "Güven kapısı", passed: 5, reason: "confidence_below_floor" },
      ]),
    );
    expect(rejectionFilterOptions(quality).map((o) => o.reason)).toEqual([
      "outside_window",
      "not_current_event",
      "confidence_below_floor",
    ]);
  });

  it("keeps a reason with zero rejections rather than dropping the chip", () => {
    const quality = riskQuality(
      riskFunnel([
        { key: "toplam", label: "Toplam makale", passed: 10 },
        { key: "guncel", label: "Güncel olay", passed: 10, reason: "not_current_event" },
      ]),
    );
    const option = rejectionFilterOptions(quality).find(
      (o) => o.reason === "not_current_event",
    );
    expect(option?.count).toBe(0);
  });

  it("reaches a reason that only exists in the counts, never in a stage", () => {
    // The location stage carries one of its two reasons; leaving the other out
    // would make a whole class of rejection unreachable from the filter.
    const quality = riskQuality(
      riskFunnel([
        { key: "toplam", label: "Toplam makale", passed: 10 },
        { key: "konum", label: "Konum doğrulandı", passed: 8, reason: "location_unresolved" },
      ]),
      { rejected_counts: { location_unresolved: 1, location_conflict: 1 } },
    );
    const reasons = rejectionFilterOptions(quality).map((o) => o.reason);
    expect(reasons).toContain("location_conflict");
  });

  it("labels a reason the backend sent no Turkish for with its own slug", () => {
    const quality = riskQuality(
      riskFunnel([
        { key: "toplam", label: "Toplam makale", passed: 10 },
        { key: "yeni", label: "Yeni kapı", passed: 9, reason: "brand_new_gate" },
      ]),
    );
    const option = rejectionFilterOptions(quality).find((o) => o.reason === "brand_new_gate");
    expect(option?.label).toBe("brand_new_gate");
  });
});

describe("rejectionPlaceLabel and scoreOrUnscored", () => {
  it("never renders a place without saying what it is worth", () => {
    expect(
      rejectionPlaceLabel({
        detected_country: "Japan",
        detected_city: "Tokyo",
        location_confidence: 0.9,
      }),
    ).toBe("Tokyo, Japan (0.90)");
  });

  it("distinguishes an unmeasured placement from a weak one", () => {
    expect(
      rejectionPlaceLabel({
        detected_country: "Japan",
        detected_city: null,
        location_confidence: null,
      }),
    ).toBe("Japan (ölçülmedi)");
    expect(
      rejectionPlaceLabel({
        detected_country: null,
        detected_city: null,
        location_confidence: null,
      }),
    ).toBe("Konum çözülemedi");
  });

  it("renders a null score as a word and a real zero as a number", () => {
    expect(scoreOrUnscored(null)).toBe("ölçülmedi");
    expect(scoreOrUnscored(undefined)).toBe("ölçülmedi");
    expect(scoreOrUnscored(0)).toBe("0.00");
  });
});
