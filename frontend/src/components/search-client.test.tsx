import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";
import type { ArticleOut } from "@/lib/types";

import { SearchClient } from "./search-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open: vi.fn() }),
}));

function article(): ArticleOut {
  return {
    id: "a1",
    url: "https://example.com/story",
    title: "Yakıt maliyeti düştü",
    author: null,
    published_at: "2026-09-01T09:00:00Z",
    fetched_at: "2026-09-01T09:05:00Z",
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
  };
}

const requested: string[] = [];

function serve(items: ArticleOut[] = [article()]) {
  apiFetch.mockImplementation((path: string) => {
    requested.push(path);
    return Promise.resolve({ total: items.length, items });
  });
}

const lastQuery = () => new URL(requested.at(-1)!, "http://test").searchParams;

describe("SearchClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    requested.length = 0;
    resetNavigation("/search");
    serve();
  });

  it("asks for nothing at all when the URL carries no query", () => {
    render(<SearchClient />);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("runs the search the URL names, filters included", async () => {
    setUrl("/search?q=yak%C4%B1t&category=revenue_management&window=7d");
    render(<SearchClient />);

    expect(await screen.findByText("Yakıt maliyeti düştü")).toBeInTheDocument();
    expect(lastQuery().get("q")).toBe("yakıt");
    expect(lastQuery().get("category")).toBe("revenue_management");
    expect(lastQuery().get("days")).toBe("7");
    // The box shows what is being searched for, not an empty field over a
    // list of results.
    expect(screen.getByRole("textbox")).toHaveValue("yakıt");
  });

  it("follows the URL when something else moves it -- the header search box", async () => {
    // components/layout/quick-search.tsx is in the Topbar on every route,
    // /search included, and does router.push("/search?q=..."). On this route
    // that is a re-render, not a remount: the results moved to the new query
    // while the page's own box still showed the old one, so "N sonuç" and the
    // field disagreed and pressing "Ara" re-ran the query the reader had just
    // left.
    setUrl("/search?q=istanbul");
    render(<SearchClient />);
    await waitFor(() => expect(lastQuery().get("q")).toBe("istanbul"));
    expect(screen.getByRole("textbox")).toHaveValue("istanbul");

    act(() => setUrl("/search?q=ankara"));

    await waitFor(() => expect(lastQuery().get("q")).toBe("ankara"));
    expect(screen.getByRole("textbox")).toHaveValue("ankara");
  });

  it("does not overwrite what the reader is typing", async () => {
    // The other direction of the same rule: the box follows the URL only when
    // the URL moves on its own. A draft has to survive the re-renders its own
    // keystrokes cause, or the field would be unusable.
    const user = userEvent.setup();
    setUrl("/search?q=istanbul");
    render(<SearchClient />);
    await screen.findByText("Yakıt maliyeti düştü");

    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "ankara");

    expect(screen.getByRole("textbox")).toHaveValue("ankara");
    // Still the old query on screen: nothing was submitted.
    expect(currentParams().get("q")).toBe("istanbul");
  });

  it("writes the submitted query back into the URL", async () => {
    // The whole point: a search used to arrive through ?q= and never go back,
    // so the one thing worth sending was the one thing that could not be sent.
    const user = userEvent.setup();
    render(<SearchClient />);

    await user.type(screen.getByRole("textbox"), "yakıt");
    await user.click(screen.getByRole("button", { name: "Ara" }));

    await waitFor(() => expect(currentParams().get("q")).toBe("yakıt"));
    expect(await screen.findByText("Yakıt maliyeti düştü")).toBeInTheDocument();
  });

  it("writes a filter press into the URL and re-runs the same query", async () => {
    const user = userEvent.setup();
    setUrl("/search?q=yak%C4%B1t");
    render(<SearchClient />);
    await screen.findByText("Yakıt maliyeti düştü");

    await user.click(screen.getByRole("button", { name: "30 gün" }));

    await waitFor(() => expect(currentParams().get("window")).toBe("30d"));
    expect(currentParams().get("q")).toBe("yakıt");
    await waitFor(() => expect(lastQuery().get("days")).toBe("30"));
  });

  it("keeps 'Tümü' out of the URL and out of the request", async () => {
    const user = userEvent.setup();
    setUrl("/search?q=yak%C4%B1t&window=30d");
    render(<SearchClient />);
    await screen.findByText("Yakıt maliyeti düştü");

    await user.click(screen.getByRole("button", { name: "Tümü" }));

    // The default window writes no key, and "no cutoff" is expressed by an
    // absent `days` -- there is no sentinel to invent.
    await waitFor(() => expect(currentParams().has("window")).toBe(false));
    await waitFor(() => expect(lastQuery().has("days")).toBe(false));
  });

  it("ignores a window id the page does not offer", async () => {
    // `?window=6h` is a Gazete rung; /search filters on days only, so a
    // hand-carried hour window must fall back rather than send `days=NaN`.
    setUrl("/search?q=yak%C4%B1t&window=6h");
    render(<SearchClient />);

    await screen.findByText("Yakıt maliyeti düştü");
    expect(lastQuery().has("days")).toBe(false);
    expect(screen.getByRole("button", { name: "Tümü" })).toHaveClass(
      "bg-primary",
    );
  });

  it("keeps the lit chip and the list describing the same query when replies race", async () => {
    // THE RACE. Two window chips pressed in a second are two requests, and the
    // first one can answer last. Held as a bare `results`, that late reply
    // overwrote the newer one: the "Tümü" chip stayed lit above a 7-day list,
    // and the "N sonuç" line counted it.
    const user = userEvent.setup();
    const slow: Array<() => void> = [];
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      const days = new URL(path, "http://test").searchParams.get("days");
      if (days === "7") {
        return new Promise((resolve) => {
          slow.push(() =>
            resolve({ total: 1, items: [{ ...article(), id: "slow", title: "7 günlük sonuç" }] }),
          );
        });
      }
      return Promise.resolve({ total: 1, items: [article()] });
    });

    setUrl("/search?q=yak%C4%B1t&window=7d");
    render(<SearchClient />);

    await user.click(screen.getByRole("button", { name: "Tümü" }));
    expect(await screen.findByText("Yakıt maliyeti düştü")).toBeInTheDocument();

    await act(async () => {
      slow.forEach((resolve) => resolve());
      await Promise.resolve();
    });

    expect(screen.getByText("Yakıt maliyeti düştü")).toBeInTheDocument();
    expect(screen.queryByText("7 günlük sonuç")).not.toBeInTheDocument();
  });

  it("clears the previous list when a search fails, and offers a retry", async () => {
    // A failed search used to leave the last successful list on screen with a
    // grey sentence above it -- so the page showed articles under a filter
    // that had never returned any, which reads as a narrower result set rather
    // than as an outage.
    const user = userEvent.setup();
    serve();
    setUrl("/search?q=yak%C4%B1t");
    render(<SearchClient />);
    await screen.findByText("Yakıt maliyeti düştü");

    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      return Promise.reject(new Error("API request failed: 500"));
    });
    await user.click(screen.getByRole("button", { name: "7 gün" }));

    expect(await screen.findByText("Veri geçici olarak kullanılamıyor.")).toBeInTheDocument();
    expect(screen.queryByText("Yakıt maliyeti düştü")).not.toBeInTheDocument();
    // ...and no count line either: there is no answer to count.
    expect(screen.queryByText(/sonuç$/)).not.toBeInTheDocument();

    serve();
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(await screen.findByText("Yakıt maliyeti düştü")).toBeInTheDocument();
  });

  it("still reports a genuinely empty result set as one", async () => {
    // The negative half: an answer of zero rows keeps reading as a
    // measurement, with the Turkish-stemming note that explains it.
    serve([]);
    setUrl("/search?q=uydurmakelime");
    render(<SearchClient />);

    expect(await screen.findByText("Sonuç bulunamadı")).toBeInTheDocument();
    expect(screen.queryByText("Veri geçici olarak kullanılamıyor.")).not.toBeInTheDocument();
  });
});
