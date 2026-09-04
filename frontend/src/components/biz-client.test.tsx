import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

/** THE SIXTY-DAY CLAIM. "Son 60 günde TK ile ilişkilendirilmiş haber yok" is a
 * statement about the archive that a competitive analyst acts on. It used to be
 * manufactured by `.catch(() => setArticles([]))` -- one HTTP error, rendered as
 * two months of silence. */
describe("BizClient: haber akışı", () => {
  function serveTk() {
    return {
      review_count: 3,
      collected_through: null,
      rating: { average: 7.5, count: 3 },
      sentiment: { positive: 2, neutral: 1, negative: 0 },
      themes: [],
      sources: [],
      quotes: [],
      digest: null,
    };
  }

  it("says the news feed could not be read instead of claiming 60 empty days", async () => {
    const user = userEvent.setup();
    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/articles")
        ? Promise.reject(new Error("API request failed: 500"))
        : Promise.resolve(serveTk()),
    );

    render(<BizClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Son 60 günde TK ile ilişkilendirilmiş haber yok."),
    ).not.toBeInTheDocument();
    // The rest of the desk is untouched -- the review corpus answered.
    expect(screen.getByText("Toplanan Yorum")).toBeInTheDocument();

    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/articles")
        ? Promise.resolve({ total: 0, items: [] })
        : Promise.resolve(serveTk()),
    );
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));

    // ...and once it answers with nothing, the sixty-day sentence is earned.
    expect(
      await screen.findByText("Son 60 günde TK ile ilişkilendirilmiş haber yok."),
    ).toBeInTheDocument();
  });

  it("offers a retry when the review corpus itself is unreadable", async () => {
    // The whole-page failure branch was a dead-end sentence: a five-second
    // outage could only be answered by reloading the route.
    const user = userEvent.setup();
    apiFetch.mockRejectedValue(new Error("API request failed: 500"));

    render(<BizClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();

    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/articles")
        ? Promise.resolve({ total: 0, items: [] })
        : Promise.resolve(serveTk()),
    );
    await user.click(screen.getAllByRole("button", { name: /Yeniden dene/ })[0]);

    expect(await screen.findByText("Toplanan Yorum")).toBeInTheDocument();
  });
});

/** THE ÖNERİLER CARD POINTED AT A REDIRECT, AND SAID THE WRONG THING.
 *
 * "Ticari sinyaller: Öneriler … kendi sayfasında" linked to `/oneriler`, which
 * has not been a page since Öneriler became a tab: app/oneriler/page.tsx is a
 * `redirect("/insights?tab=oneriler")`. One click therefore cost two
 * navigations, and the place it landed was not the "own page" the card had
 * promised. The route still exists for old bookmarks; this card names the real
 * destination.
 */
describe("BizClient: taşınan bölümlerin işaret kartları", () => {
  beforeEach(() => {
    serve("2026-07-19T21:30:00Z");
  });

  it("links Öneriler straight to the tab that draws it", async () => {
    render(<BizClient />);

    const card = await screen.findByRole("link", { name: /Öneriler/ });
    expect(card).toHaveAttribute("href", "/insights?tab=oneriler");
    // The redirect is not an acceptable target: it is one extra hop to a
    // destination this card can name itself.
    expect(card).not.toHaveAttribute("href", "/oneriler");
  });

  it("no longer claims Öneriler has a page of its own", async () => {
    render(<BizClient />);

    expect(await screen.findByText(/Öneriler sekmesinde/)).toBeInTheDocument();
    expect(screen.queryByText(/kendi sayfasında\./)).not.toBeInTheDocument();
  });

  it("still points the moved signal block at Sinyaller", async () => {
    render(<BizClient />);

    expect(await screen.findByRole("link", { name: /Sinyaller artık/ })).toHaveAttribute(
      "href",
      "/sinyaller",
    );
  });
});
