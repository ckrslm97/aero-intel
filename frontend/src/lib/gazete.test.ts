import { describe, expect, it } from "vitest";

import {
  applyWindowParams,
  BREAKING_WINDOW_HOURS,
  DEFAULT_FILTERS,
  DEFAULT_WINDOW_ID,
  hasNarrowingFilters,
  isBreaking,
  parseFilters,
  serializeFilters,
  sourceTierLabelTr,
  TIER_FILTERS,
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

  it("keeps 30 gün as the default rather than Hepsi", () => {
    // Hepsi as the default would make the paper's first paint a query over the
    // whole archive -- and the tab badges and source facets are unpaginated
    // aggregates over whatever window they are handed.
    expect(DEFAULT_WINDOW_ID).toBe("30d");
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

  it("falls back to the 30-day default for an unknown id", () => {
    // A bookmarked link that predates this row, or a typo, must show the paper
    // it always showed rather than an empty one.
    expect(windowOption(null).id).toBe(DEFAULT_WINDOW_ID);
    expect(windowOption("nonsense").id).toBe(DEFAULT_WINDOW_ID);
    expect(windowOption(DEFAULT_WINDOW_ID).days).toBe(30);
  });
});

describe("URL filter state", () => {
  it("round-trips every filter", () => {
    const filters = {
      category: "fleet",
      subcategory: "maintenance",
      region: "europe",
      country: "Germany",
      airline: "RIVALS",
      window: "7d",
      tier: "official",
      source: "Reuters",
      page: 3,
    };
    expect(parseFilters(serializeFilters(filters))).toEqual(filters);
  });

  it("omits defaults so an unfiltered paper has a clean URL", () => {
    expect(serializeFilters(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("falls back for a category the Gazete does not show", () => {
    // ?category=safety (excluded) and Know How's ?category=network have no tab
    // to select and would sit on an empty list nothing could fix.
    expect(parseFilters(new URLSearchParams("category=safety")).category).toBe(
      DEFAULT_FILTERS.category,
    );
    expect(parseFilters(new URLSearchParams("category=network")).category).toBe(
      DEFAULT_FILTERS.category,
    );
    expect(parseFilters(new URLSearchParams("category=fleet")).category).toBe("fleet");
  });

  it("drops an unknown tier rather than passing it to the API", () => {
    expect(parseFilters(new URLSearchParams("tier=made_up")).tier).toBeNull();
    expect(parseFilters(new URLSearchParams("tier=official")).tier).toBe("official");
  });

  it("reads a missing or broken page as page 1", () => {
    expect(parseFilters(new URLSearchParams("")).page).toBe(1);
    expect(parseFilters(new URLSearchParams("page=abc")).page).toBe(1);
    expect(parseFilters(new URLSearchParams("page=0")).page).toBe(1);
    expect(parseFilters(new URLSearchParams("page=4")).page).toBe(4);
  });
});

describe("strip visibility", () => {
  it("keeps the strips on the default view", () => {
    expect(hasNarrowingFilters(DEFAULT_FILTERS)).toBe(false);
  });

  it("keeps them while only the category tab changes", () => {
    // A category IS the paper's tab row, not a narrowing of it -- the strips
    // follow the selected tab rather than disappearing on it.
    expect(hasNarrowingFilters({ ...DEFAULT_FILTERS, category: "fleet" })).toBe(false);
  });

  it("hides them as soon as a filter narrows the paper", () => {
    // A top-4 that ignored the region chip the reader just pressed would be
    // four unrelated stories sitting above their filtered list.
    for (const patch of [
      { region: "europe" },
      { country: "Germany" },
      { airline: "EK" },
      { subcategory: "pricing" },
      { tier: "official" },
      { source: "Reuters" },
      { window: "6h" },
      { window: "all" },
      { page: 2 },
    ]) {
      expect(hasNarrowingFilters({ ...DEFAULT_FILTERS, ...patch })).toBe(true);
    }
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
    for (const tier of ["official", "regulator", "agency", "trade", "aggregator"]) {
      expect(sourceTierLabelTr(tier)).not.toBe("Bilinmiyor");
    }
  });

  it("says so rather than inventing a label", () => {
    expect(sourceTierLabelTr(null)).toBe("Bilinmiyor");
  });

  it("covers every tier across the filter chips exactly once", () => {
    // A tier missing from the row would be unreachable; a tier in two chips
    // would make two chips return overlapping lists.
    const covered = TIER_FILTERS.flatMap((filter) => filter.tiers);
    expect([...covered].sort()).toEqual(
      ["aggregator", "agency", "official", "regulator", "trade"].sort(),
    );
    expect(new Set(covered).size).toBe(covered.length);
  });
});
