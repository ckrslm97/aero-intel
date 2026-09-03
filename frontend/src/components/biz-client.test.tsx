import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BizClient } from "./biz-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

/** The smallest /tk payload the page will render, with `collected_through`
 * as the only thing a test varies. */
function serve(collectedThrough: string | null) {
  apiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/articles")) return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve({
      review_count: 3,
      collected_through: collectedThrough,
      rating: { average: 7.5, count: 3 },
      sentiment: { positive: 2, neutral: 1, negative: 0 },
      themes: [],
      sources: [{ name: "Skytrax", count: 3 }],
      quotes: [],
      digest: null,
    });
  });
}

beforeEach(() => {
  apiFetch.mockReset();
});

/** "SON TOPLAMA" IS A RECORD'S TIMESTAMP, NOT THE READER'S.
 *
 * `collected_through` is the corpus's own `max(collected_at)` -- a full UTC
 * datetime. Formatted in whatever zone the reader happens to sit in, a row
 * stamped 2026-07-19T21:30Z reads "19 Temmuz" in London and "20 Temmuz" in
 * Istanbul: one fact, two dates, and neither reader can tell. The runner's TZ
 * is pinned to Europe/Istanbul (UTC+3) precisely so this is measurable -- see
 * vitest.config.ts.
 */
describe("BizClient: son toplama tarihi okuyucuya göre değişmez", () => {
  it("prints the corpus's own UTC day for a late-evening timestamp", async () => {
    serve("2026-07-19T21:30:00Z");
    render(<BizClient />);

    // A local formatter would print "20 Temmuz 2026" under Europe/Istanbul.
    expect(await screen.findByText(/Son toplama: 19 Temmuz 2026\./)).toBeInTheDocument();
  });

  it("says nothing at all when the corpus has no collection date", async () => {
    // NULL is "nothing has been collected", which is not a date and must not
    // be rendered as one -- the sentence simply ends.
    serve(null);
    render(<BizClient />);

    // The sentence the stamp is appended to renders either way -- so its
    // presence proves the section loaded and the stamp was genuinely omitted,
    // rather than the whole block being absent.
    await waitFor(() =>
      expect(screen.getByText(/dağılım bulunan yorumların gerçek dağılımıdır/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Son toplama/)).not.toBeInTheDocument();
  });
});
