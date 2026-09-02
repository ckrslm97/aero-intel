import { describe, expect, it } from "vitest";

import {
  appendGazeteFilters,
  applyWindowParams,
  BREAKING_WINDOW_HOURS,
  DEFAULT_FILTERS,
  DEFAULT_WINDOW_ID,
  isBreaking,
  MIN_INTELLIGENCE,
  parseFilters,
  scoreBand,
  scoreReasonTr,
  serializeFilters,
  sourceTierLabelTr,
  windowOption,
  WINDOW_OPTIONS,
} from "./gazete";

describe("window chips", () => {
  it("maps each rung to exactly one API param, or declares it sends none", () => {
    // The API 422s on a request carrying two time windows, so a rung that
    // claimed both would be an un-fetchable filter. "Hepsi" claims neither
    // and has to say so out loud -- a rung that lost its hours/days by
    // accident would otherwise become a silent whole-archive query.
    for (const option of WINDOW_OPTIONS) {
      expect(Boolean(option.hours) !== Boolean(option.days)).toBe(!option.unbounded);
      // Every rung needs a span the empty state can name.
      expect(option.scopeLabel.length).toBeGreaterThan(0);
    }
  });

  it("sends no time param at all for Hepsi", () => {
    // Absence IS how the API expresses "no cutoff" (see
    // backend/app/api/v1/articles.py `_window_start`) -- there is no days=0 or
    // sentinel to send, and inventing one would be a second way to say what an
    // absent param already says.
    const params = new URLSearchParams("hours=24&category=fleet");
    applyWindowParams(params, windowOption("all"));
    expect(params.get("hours")).toBeNull();
    expect(params.get("days")).toBeNull();
    expect(params.get("category")).toBe("fleet");
  });

  it("defaults to 3 gün, not to 30 and not to Hepsi", () => {
    // The 30-day default belonged to a paginated archive with a filter row on
    // top. The paper prints the day's critical developments, of which the
    // backend hands out at most 18 per run -- so 30 days is roughly 500 cards
    // under two headings. Hepsi would additionally make the first paint a
    // query over the whole archive.
    expect(DEFAULT_WINDOW_ID).toBe("3d");
    expect(windowOption(DEFAULT_WINDOW_ID).days).toBe(3);
    expect(windowOption(DEFAULT_WINDOW_ID).unbounded).toBeUndefined();
  });

  it("sends hours for the short rungs and days for the rest", () => {
    expect(applyWindowParams(new URLSearchParams(), windowOption("6h")).toString()).toBe(
      "hours=6",
    );
    expect(applyWindowParams(new URLSearchParams(), windowOption("7d")).toString()).toBe(
      "days=7",
    );
  });

  it("clears the other window key when switching rungs", () => {
    // 24 saat -> 7 gün on a URL that already carries `hours` would otherwise
    // send hours=24&days=7 and earn a 422 instead of a list.
    const params = new URLSearchParams("hours=24&category=fleet");
    applyWindowParams(params, windowOption("7d"));
    expect(params.get("hours")).toBeNull();
    expect(params.get("days")).toBe("7");
    expect(params.get("category")).toBe("fleet");
  });

  it("falls back to the default rung for an unknown id", () => {
    expect(windowOption(null).id).toBe(DEFAULT_WINDOW_ID);
    expect(windowOption("nonsense").id).toBe(DEFAULT_WINDOW_ID);
  });
});

describe("shared query params", () => {
  it("asks for translated, judged articles and nothing else", () => {
    // `exclude_categories` used to be here, because one query filled a list
    // under a tab row and every other beat had to be named and shut out. Each
    // section now queries its own category by name, so the exclusion is
    // structural -- a query that asks for `airport` cannot return `fleet`.
    const params = appendGazeteFilters(new URLSearchParams({ category: "airport" }));
    expect(params.get("translated_only")).toBe("true");
    expect(params.get("min_intelligence")).toBe(String(MIN_INTELLIGENCE));
    expect(params.getAll("exclude_categories")).toEqual([]);
    expect(params.get("category")).toBe("airport");
  });

  it("no longer sends min_importance", () => {
    // The column it floors reduces, at the corroboration count every
    // production row has, to `0.34 + 0.21 * source.trust_weight` -- so a floor
    // on it selects publishers, not stories. `min_intelligence` replaces it.
    expect(appendGazeteFilters(new URLSearchParams()).get("min_importance")).toBeNull();
  });

  it("keeps the floor low enough that it is not the thing thinning the paper", () => {
    // Thinning is the per-category quota's job, upstream, where it can be done
    // per section. A floor high enough to thin here would cut whichever
    // category scores lowest and empty it -- the exact failure min_importance
    // produced.
    expect(MIN_INTELLIGENCE).toBeLessThan(0.5);
    expect(MIN_INTELLIGENCE).toBeGreaterThan(0);
  });
});

describe("URL filter state", () => {
  it("round-trips every filter", () => {
    const filters = {
      // A category the paper shows, with one of the Havalimanı subcategories
      // the taxonomy round added -- a round-trip through a category the
      // allow-list rejects would be testing the fallback, not the round-trip.
      category: "airport",
      subcategory: "slot",
      region: "europe",
      country: "Germany",
      airline: "RIVALS",
      window: "7d",
    };
    expect(parseFilters(serializeFilters(filters))).toEqual(filters);
  });

  it("omits defaults so an unfiltered paper has a clean URL", () => {
    expect(serializeFilters(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("defaults to no category at all, which renders every section", () => {
    // The paper is a front page, not a tab strip: "no category" is a real
    // view, so it has to be representable rather than falling back to the
    // first tab.
    expect(DEFAULT_FILTERS.category).toBeNull();
    expect(parseFilters(new URLSearchParams("")).category).toBeNull();
  });

  it("falls back for a category the Gazete does not show", () => {
    // ?category=safety and Know How's ?category=network have no section to
    // select and would sit on an empty list nothing could fix.
    for (const slug of ["safety", "network", "fleet", "finance", "general"]) {
      expect(parseFilters(new URLSearchParams(`category=${slug}`)).category).toBeNull();
    }
    expect(parseFilters(new URLSearchParams("category=airport")).category).toBe("airport");
  });

  it("drops an unknown region rather than forwarding it", () => {
    // Region is the one filter this page sends to TWO endpoints, and /events
    // types it as an enum: a typo would 422 there and take the event blocks
    // down over a bad bookmark.
    expect(parseFilters(new URLSearchParams("region=erupoe")).region).toBeNull();
    expect(parseFilters(new URLSearchParams("region=europe")).region).toBe("europe");
  });

  it("has no source, tier or page filter left to serialise", () => {
    // PR #60's source-authority chips and named-outlet row are gone (they
    // asked a newsroom's question, not a desk's), and so is pagination. A URL
    // still carrying them from a bookmark must be ignored, not half-honoured.
    const parsed = parseFilters(
      new URLSearchParams("tier=official&source=Reuters&page=4&category=airport"),
    );
    expect(parsed).not.toHaveProperty("tier");
    expect(parsed).not.toHaveProperty("source");
    expect(parsed).not.toHaveProperty("page");
    // The one legible param on that URL still works.
    expect(parsed.category).toBe("airport");
    expect(serializeFilters(parsed).toString()).toBe("category=airport");
  });
});

describe("son dakika derivation", () => {
  const now = new Date("2026-08-30T12:00:00Z").getTime();

  it("counts a story inside the window", () => {
    expect(isBreaking("2026-08-30T09:00:00Z", now)).toBe(true);
  });

  it("drops one just past it", () => {
    const past = new Date(now - (BREAKING_WINDOW_HOURS + 1) * 3_600_000).toISOString();
    expect(isBreaking(past, now)).toBe(false);
  });

  it("never calls an undated story breaking", () => {
    // Treating "we don't know when" as "just now" would put the loudest label
    // in the paper on its least certain rows.
    expect(isBreaking(null, now)).toBe(false);
    expect(isBreaking("not-a-date", now)).toBe(false);
  });

  it("treats a feed's future timestamp as fresh, not as excluded", () => {
    expect(isBreaking("2026-08-30T12:30:00Z", now)).toBe(true);
  });
});

describe("source tiers", () => {
  it("labels all five tiers the backend can emit", () => {
    // The tier FILTER is gone; the tier LABEL is not. The analysis drawer and
    // the corroborating-source list still name the rung an outlet sits on.
    for (const tier of ["official", "regulator", "agency", "trade", "aggregator"]) {
      expect(sourceTierLabelTr(tier)).not.toBe("Bilinmiyor");
    }
  });

  it("says so rather than inventing a label", () => {
    expect(sourceTierLabelTr(null)).toBe("Bilinmiyor");
  });
});

describe("intelligence score presentation", () => {
  it("bands a score instead of printing its decimals", () => {
    expect(scoreBand(0.82)).toBe("critical");
    expect(scoreBand(0.6)).toBe("high");
    expect(scoreBand(0.45)).toBe("medium");
    expect(scoreBand(0.1)).toBe("low");
  });

  it("has no band at all for a row the scorer never reached", () => {
    // NULL is "nobody looked", never "judged unimportant" -- so the drawer's
    // whole block is absent rather than showing a low band.
    expect(scoreBand(null)).toBeNull();
    expect(scoreBand(undefined)).toBeNull();
    expect(scoreBand(Number.NaN)).toBeNull();
  });

  it("names the two components that CONTRIBUTED most, not the two highest", () => {
    // source_reliability is the highest raw value here and the smallest
    // weight; naming it would explain a number it barely moved.
    const detail = {
      components: {
        source_reliability: 1.0,
        competitive_impact: 0.8,
        freshness: 0.9,
        relevance: 0.1,
      },
      weights: {
        source_reliability: 0.07,
        competitive_impact: 0.14,
        freshness: 0.1,
        relevance: 0.16,
      },
    };
    expect(scoreReasonTr(detail)).toBe("rakip hamlesi + tazelik");
  });

  it("stays silent on a detail blob it cannot read", () => {
    // JSONB: a row written by an older or newer scorer is still a row, and the
    // drawer omits the line rather than printing "Neden seçildi: ".
    expect(scoreReasonTr(null)).toBeNull();
    expect(scoreReasonTr(undefined)).toBeNull();
    expect(scoreReasonTr({})).toBeNull();
    expect(scoreReasonTr({ components: "nonsense" })).toBeNull();
    expect(scoreReasonTr({ components: { unknown_future_component: 0.9 } })).toBeNull();
  });
});
