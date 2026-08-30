import type { ArticleOut } from "@/lib/types";

/** A plain, enrichment-less article row, overridable field by field.
 *
 * Same contract as `promotion.ts` next door: test-only, and defaulting to the
 * least-decorated shape the pipeline actually produces -- no enrichment, no
 * mentions -- so a component that quietly assumes a fully-enriched story fails
 * its test instead of its first unenriched render. */
export function article(overrides: Partial<ArticleOut> = {}): ArticleOut {
  return {
    id: overrides.id ?? "00000000-0000-0000-0000-000000000101",
    url: "https://example.com/haber",
    title: "THY yeni kabin düzenini duyurdu",
    author: null,
    published_at: null,
    fetched_at: "2026-08-20T09:00:00Z",
    status: "enriched",
    source: {
      id: "00000000-0000-0000-0000-000000000201",
      name: "Havacılık Gazetesi",
      url: "https://example.com",
      category: "news",
      trust_weight: 1,
    },
    enrichment: null,
    reading_time_minutes: 3,
    airlines: [],
    airports: [],
    ...overrides,
  };
}
