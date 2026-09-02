import { describe, expect, it } from "vitest";

import { CATEGORY_SLUGS, SUBCATEGORIES_BY_CATEGORY } from "@/lib/taxonomy.gen";
import {
  CATEGORIES,
  CATEGORY_BY_SLUG,
  NEWSPAPER_CATEGORY_SLUGS,
  NEWSPAPER_EXCLUDED_CATEGORY_SLUGS,
  getSubcategoryLabel,
} from "@/lib/taxonomy";

describe("Gazete category allow-list", () => {
  it("shows the desk's three sections, Gelir Yönetimi first", () => {
    expect([...NEWSPAPER_CATEGORY_SLUGS]).toEqual([
      "revenue_management",
      "airport",
      "events",
    ]);
  });

  it("accounts for every backend category exactly once", () => {
    // The invariant that keeps the paper honest. A category the backend can
    // emit that is in neither list is not "hidden" -- it has no tab, so it
    // never reaches `exclude_categories` either, and its articles surface
    // under whichever section happens to be open. Splitting the taxonomy into
    // shown and excluded, with nothing left over, is what prevents that.
    const shown = new Set<string>(NEWSPAPER_CATEGORY_SLUGS);
    const excluded = new Set<string>(NEWSPAPER_EXCLUDED_CATEGORY_SLUGS);

    for (const slug of shown) expect(excluded.has(slug)).toBe(false);
    expect([...shown, ...excluded].sort()).toEqual([...CATEGORY_SLUGS].sort());
  });

  it("hides fleet, finance, network and general from the paper", () => {
    // Not a taxonomy change: they are still classified, still reach Öneriler
    // and the newsletter. A fleet story only reaches the Gazete when the
    // backend's shift rule files it as revenue_management -- see
    // RM_SHIFT_KEYWORDS in backend/app/taxonomy.py.
    for (const slug of ["fleet", "finance", "network", "general"]) {
      expect(NEWSPAPER_EXCLUDED_CATEGORY_SLUGS).toContain(slug);
      expect(CATEGORY_BY_SLUG[slug]).toBeDefined();
    }
  });
});

describe("subcategory labels", () => {
  it("gives every backend subcategory a Turkish chip", () => {
    // taxonomy.ts's own import-time guard checks that a labelled subcategory
    // exists in the backend. This is the other direction, and the one that
    // bites in silence: a slug the backend classifies into with no label here
    // renders as no chip at all, so the filter simply cannot be reached.
    for (const category of CATEGORIES) {
      for (const slug of SUBCATEGORIES_BY_CATEGORY[category.slug]) {
        expect(
          getSubcategoryLabel(category.slug, slug),
          `${category.slug}/${slug} has no Turkish label`,
        ).toBeTruthy();
      }
    }
  });

  it("keeps Talep and Kapasite as separate chips", () => {
    // The split this taxonomy round is for. One combined "Talep & Kapasite"
    // chip could not tell what the market wants from what a carrier supplies.
    expect(getSubcategoryLabel("revenue_management", "demand")).toBe("Talep");
    expect(getSubcategoryLabel("revenue_management", "capacity")).toBe("Kapasite");
    expect(getSubcategoryLabel("revenue_management", "demand_capacity")).toBeNull();
  });

  it("labels all nine Havalimanı beats", () => {
    const airport = CATEGORY_BY_SLUG.airport;
    expect(airport.subcategories).toHaveLength(9);
    expect(airport.subcategories.map((s) => s.slug)).toContain("slot");
  });
});
