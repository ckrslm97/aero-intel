import { describe, expect, it } from "vitest";

import { CATEGORY_SLUGS, SUBCATEGORIES_BY_CATEGORY } from "@/lib/taxonomy.gen";
import {
  CATEGORIES,
  CATEGORY_BY_SLUG,
  NEWSPAPER_CATEGORY_SLUGS,
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

  it("names only categories the backend can actually emit", () => {
    // A section whose slug the backend does not classify into is a heading
    // over a query that can only ever return nothing. There used to be a
    // second list here (NEWSPAPER_EXCLUDED_CATEGORY_SLUGS) and an invariant
    // that the two partitioned the taxonomy; the paper no longer sends
    // `exclude_categories` at all -- each section queries its own category by
    // name -- so the only thing left to check is that the allow-list is a
    // real subset.
    for (const slug of NEWSPAPER_CATEGORY_SLUGS) {
      expect(CATEGORY_SLUGS).toContain(slug);
    }
  });

  it("keeps fleet, finance, network and general out of the paper", () => {
    // Not a taxonomy change: they are still classified, still reach Öneriler,
    // arama and the newsletter, and they still have labels and colours here.
    // A fleet story only reaches the Gazete when the backend's shift rule
    // files it as revenue_management -- see RM_SHIFT_KEYWORDS in
    // backend/app/taxonomy.py.
    for (const slug of ["fleet", "finance", "network", "general"]) {
      expect(NEWSPAPER_CATEGORY_SLUGS).not.toContain(slug);
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
