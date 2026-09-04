import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";
import type { ArticleOut } from "@/lib/types";

import { ArchiveClient } from "./archive-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

// A real (fake) address bar: ?category arrives from Gazete's "Arşivde tümü"
// link and ?date is written back, so both have to actually move.
vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open: vi.fn() }),
}));

/** The clock the strip is built from. Pinned so "today" and "yesterday" are
 * the same two days on every run. */
const TODAY = "2026-09-02";
const YESTERDAY = "2026-09-01";

function article(overrides: Partial<ArticleOut> = {}): ArticleOut {
  return {
    id: "a1",
    url: "https://example.com/story",
    title: "Rakip Atlantik ötesi ücretleri düşürdü",
    author: null,
    published_at: `${TODAY}T09:00:00Z`,
    fetched_at: `${TODAY}T09:05:00Z`,
    status: "published",
    source: {
      id: "s1",
      name: "Reuters",
      url: "https://reuters.com",
      category: "agency",
      trust_weight: 0.9,
      tier: "agency",
    },
    enrichment: null,
    reading_time_minutes: 3,
    airlines: [],
    airports: [],
    ...overrides,
  };
}

/** Which `/articles` and `/articles/daily-counts` paths were requested. */
const requested: string[] = [];

interface Feed {
  /** Per-day counts, keyed by the `category` the strip asked for ("" = none). */
  counts: Record<string, Record<string, number>>;
  /** Articles per requested day. */
  byDay?: Record<string, ArticleOut[]>;
}

function serve({ counts, byDay = {} }: Feed) {
  apiFetch.mockImplementation((path: string) => {
    requested.push(path);
    const query = new URL(path, "http://test").searchParams;
    if (path.startsWith("/articles/daily-counts")) {
      return Promise.resolve(counts[query.get("category") ?? ""] ?? {});
    }
    if (path.startsWith("/articles")) {
      const items = byDay[query.get("date") ?? ""] ?? [];
      return Promise.resolve({ total: items.length, items });
    }
    if (path.startsWith("/editions")) return Promise.resolve([]);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

/** The `/articles` list paths only -- the counts endpoint is asserted apart. */
const listPaths = () =>
  requested.filter((path) => path.startsWith("/articles?"));

describe("ArchiveClient", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
    apiFetch.mockReset();
    requested.length = 0;
    resetNavigation("/archive");
  });

  it("asks for the day only, with no beat, when the URL names no category", async () => {
    serve({
      counts: { "": { [TODAY]: 4 } },
      byDay: { [TODAY]: [article()] },
    });

    render(<ArchiveClient />);

    await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü");
    expect(listPaths().at(-1)).toBe(`/articles?date=${TODAY}&limit=100`);
    expect(requested).toContain("/articles/daily-counts?days=7");
    // No chip to take off, because nothing was put on.
    expect(screen.queryByText("Filtre")).not.toBeInTheDocument();
  });

  it("applies ?category to the list, the counts and the chip row", async () => {
    // C2: Gazete's "Arşivde tümü" writes this link. It used to be a param
    // nothing here read -- the reader got an unfiltered list with `category=`
    // still in the address bar, which is worse than no filter at all.
    setUrl("/archive?category=revenue_management");
    serve({
      counts: { revenue_management: { [TODAY]: 2 } },
      byDay: { [TODAY]: [article()] },
    });

    render(<ArchiveClient />);

    await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü");
    expect(listPaths().at(-1)).toBe(
      `/articles?date=${TODAY}&limit=100&category=revenue_management`,
    );
    // The badges count the same rows the list renders, or they are a heading
    // lying about its own list.
    expect(requested).toContain(
      "/articles/daily-counts?days=7&category=revenue_management",
    );
    expect(
      screen.getByRole("button", { name: "Gelir Yönetimi filtresini kaldır" }),
    ).toBeInTheDocument();
  });

  it("jumps to the newest day that has news IN THIS BEAT", async () => {
    // The interaction the whole item turns on. Today has plenty of news and
    // none of it is Gelir Yönetimi; an unfiltered jump would leave the reader
    // on today looking at an empty list under a filter they cannot see.
    setUrl("/archive?category=revenue_management");
    serve({
      counts: {
        "": { [TODAY]: 40, [YESTERDAY]: 12 },
        revenue_management: { [YESTERDAY]: 3 },
      },
      byDay: { [YESTERDAY]: [article({ id: "y1", title: "Dünkü RM haberi" })] },
    });

    render(<ArchiveClient />);

    expect(await screen.findByText("Dünkü RM haberi")).toBeInTheDocument();
    await waitFor(() =>
      expect(listPaths().at(-1)).toBe(
        `/articles?date=${YESTERDAY}&limit=100&category=revenue_management`,
      ),
    );
  });

  it("writes the day the reader picks into the URL and keeps the beat", async () => {
    const user = userEvent.setup();
    setUrl("/archive?category=revenue_management");
    serve({
      counts: { revenue_management: { [TODAY]: 2, [YESTERDAY]: 1 } },
      byDay: {
        [TODAY]: [article()],
        [YESTERDAY]: [article({ id: "y1", title: "Dünkü RM haberi" })],
      },
    });

    render(<ArchiveClient />);
    await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü");

    await user.click(screen.getByText("1 Eyl"));

    await waitFor(() => expect(currentParams().get("date")).toBe(YESTERDAY));
    expect(currentParams().get("category")).toBe("revenue_management");
    expect(await screen.findByText("Dünkü RM haberi")).toBeInTheDocument();
  });

  it("clears both keys when the beat chip is taken off, and stays on a day that still has news", async () => {
    const user = userEvent.setup();
    setUrl(`/archive?category=revenue_management&date=${YESTERDAY}`);
    serve({
      counts: {
        "": { [TODAY]: 40, [YESTERDAY]: 12 },
        revenue_management: { [YESTERDAY]: 3 },
      },
      byDay: {
        [TODAY]: [article()],
        [YESTERDAY]: [article({ id: "y1", title: "Dünkü RM haberi" })],
      },
    });

    render(<ArchiveClient />);
    await screen.findByText("Dünkü RM haberi");

    await user.click(
      screen.getByRole("button", { name: "Gelir Yönetimi filtresini kaldır" }),
    );

    // Both keys go, not just the category: the day was pinned inside the beat.
    await waitFor(() => expect(currentParams().has("category")).toBe(false));
    expect(currentParams().has("date")).toBe(false);

    // ...and the page does NOT jump. 1 Eyl carries 12 unfiltered stories, so
    // the strip's rule keeps it: a page that moved out from under a reader who
    // only pressed "clear filter" would be answering a question nobody asked.
    await waitFor(() =>
      expect(listPaths().at(-1)).toBe(`/articles?date=${YESTERDAY}&limit=100`),
    );
    expect(screen.getByText("Dünkü RM haberi")).toBeInTheDocument();
  });

  it("jumps off a pinned day that the newly cleared beat left empty", async () => {
    const user = userEvent.setup();
    setUrl(`/archive?category=revenue_management&date=${YESTERDAY}`);
    serve({
      // Unfiltered, yesterday is empty and today is not -- the reverse of the
      // case above, and the reason the jump rule is a rule and not a constant.
      counts: {
        "": { [TODAY]: 40 },
        revenue_management: { [YESTERDAY]: 3 },
      },
      byDay: {
        [TODAY]: [article()],
        [YESTERDAY]: [article({ id: "y1", title: "Dünkü RM haberi" })],
      },
    });

    render(<ArchiveClient />);
    await screen.findByText("Dünkü RM haberi");

    await user.click(
      screen.getByRole("button", { name: "Gelir Yönetimi filtresini kaldır" }),
    );

    expect(await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü")).toBeInTheDocument();
    expect(listPaths().at(-1)).toBe(`/articles?date=${TODAY}&limit=100`);
  });

  it("ignores a category slug the taxonomy does not know", async () => {
    // Passed through, `/articles` would answer with an empty list and the page
    // would print "haber toplanmamış" over a full archive.
    setUrl("/archive?category=uydurma");
    serve({
      counts: { "": { [TODAY]: 4 } },
      byDay: { [TODAY]: [article()] },
    });

    render(<ArchiveClient />);

    await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü");
    expect(listPaths().every((path) => !path.includes("category"))).toBe(true);
    expect(screen.queryByText("Filtre")).not.toBeInTheDocument();
  });

  it("shows no day counts at all rather than a week of zeroes when the tally fails", async () => {
    // THE FAILURE THIS ROUND IS NAMED FOR. The counts request used to be caught
    // into `{}`, so all seven chips read "0" and the strip stated, in the
    // product's own voice, that a week of the archive was empty. A revenue desk
    // reading that stops looking.
    const user = userEvent.setup();
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles/daily-counts")) {
        return Promise.reject(new Error("API request failed: 500"));
      }
      if (path.startsWith("/articles")) {
        return Promise.resolve({ total: 1, items: [article()] });
      }
      return Promise.resolve([]);
    });

    render(<ArchiveClient />);

    expect(
      await screen.findByText("Gün sayaçları okunamadı; gün rozetleri bu yüzden boş."),
    ).toBeInTheDocument();
    // Not one zero anywhere on the strip -- "—" is the only honest badge.
    const strip = screen.getByText("2 Eyl").closest("button")!;
    expect(strip).toHaveTextContent("—");
    expect(strip).not.toHaveTextContent("0");

    // ...and it can be asked again without leaving the day in view.
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles/daily-counts")) return Promise.resolve({ [TODAY]: 4 });
      if (path.startsWith("/articles")) return Promise.resolve({ total: 1, items: [article()] });
      return Promise.resolve([]);
    });
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    await waitFor(() => expect(strip).toHaveTextContent("4"));
  });

  it("does not call an unanswered day counter unreadable", async () => {
    // The third branch, and the one the tooltip used to swallow. The badge
    // already drew "…" for a request in flight and "—" for one that failed,
    // but the accessible text asked only whether `counts` had arrived -- so a
    // reader hovering a still-loading badge was told the day's count could not
    // be read, an error asserted about an answer nobody had yet.
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles/daily-counts")) return new Promise(() => {});
      if (path.startsWith("/articles")) {
        return Promise.resolve({ total: 1, items: [article()] });
      }
      return Promise.resolve([]);
    });

    render(<ArchiveClient />);

    const badge = (await screen.findByText("2 Eyl")).closest("button")!;
    await waitFor(() => expect(badge).toHaveTextContent("…"));
    expect(screen.queryByTitle(/okunamadı/)).not.toBeInTheDocument();
    // All seven day badges, not just the one -- the whole strip is waiting.
    expect(screen.getAllByTitle("Gün sayacı yükleniyor")).toHaveLength(7);
    // And nothing anywhere on the strip has yet claimed the tally failed.
    expect(
      screen.queryByText("Gün sayaçları okunamadı; gün rozetleri bu yüzden boş."),
    ).not.toBeInTheDocument();
  });

  it("never says a day collected nothing when the day's request failed", async () => {
    const user = userEvent.setup();
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles/daily-counts")) return Promise.resolve({ [TODAY]: 4 });
      if (path.startsWith("/articles")) {
        return Promise.reject(new Error("API request failed: 500"));
      }
      return Promise.resolve([]);
    });

    render(<ArchiveClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Bu günde haber toplanmamış")).not.toBeInTheDocument();

    serve({ counts: { "": { [TODAY]: 4 } }, byDay: { [TODAY]: [article()] } });
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(
      await screen.findByText("Rakip Atlantik ötesi ücretleri düşürdü"),
    ).toBeInTheDocument();
  });

  it("still says a day collected nothing when it genuinely did", async () => {
    // The negative half. An answered request with no rows is a measurement and
    // keeps its own sentence -- the error branch must not swallow it.
    serve({ counts: { "": { [TODAY]: 0 } }, byDay: {} });

    render(<ArchiveClient />);

    expect(await screen.findByText("Bu günde haber toplanmamış")).toBeInTheDocument();
    expect(
      screen.queryByText("Veri geçici olarak kullanılamıyor."),
    ).not.toBeInTheDocument();
  });

  it("says the edition list could not be read rather than dropping the section", async () => {
    // It is still a bonus section -- it does not take the page down -- but a
    // silently absent "Günlük Sayılar" is the page asserting there are no
    // editions.
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles/daily-counts")) return Promise.resolve({ [TODAY]: 1 });
      if (path.startsWith("/articles")) return Promise.resolve({ total: 1, items: [article()] });
      return Promise.reject(new Error("API request failed: 500"));
    });

    render(<ArchiveClient />);

    expect(
      await screen.findByText("Günlük sayılar listesi okunamadı."),
    ).toBeInTheDocument();
    // The day's news is untouched: one source down thins the page, never blanks it.
    expect(
      screen.getByText("Rakip Atlantik ötesi ücretleri düşürdü"),
    ).toBeInTheDocument();
  });
});
