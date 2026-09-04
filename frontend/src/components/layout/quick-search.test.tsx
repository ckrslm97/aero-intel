import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetNavigation } from "@/lib/__fixtures__/next-navigation";
import type { ArticleListOut, ArticleOut } from "@/lib/types";

import { QuickSearch } from "./quick-search";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

function article(id: string, title: string): ArticleOut {
  return {
    id,
    url: `https://example.test/${id}`,
    title,
    author: null,
    published_at: "2026-09-02T09:00:00Z",
    fetched_at: "2026-09-02T09:05:00Z",
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

const list = (items: ArticleOut[]): ArticleListOut => ({ total: items.length, items });

/** The query of each `/search` request the box fired, in order. */
const asked = () =>
  apiFetch.mock.calls.map(
    (call) => new URL(call[0] as string, "http://test").searchParams.get("q") ?? "",
  );

/** Type into the box and let the 250ms debounce elapse. */
async function type(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByRole("textbox"), text);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
}

describe("QuickSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiFetch.mockReset();
    resetNavigation("/");
  });

  it("labels the list with the query it actually answers, whatever order the replies arrive in", async () => {
    // THE RACE. Three keystrokes, three requests, and the SECOND one answers
    // last. Held as a bare `results`, the late reply overwrote the newest one
    // and the dropdown -- headed by the box's current text -- listed another
    // query's articles. A revenue desk reading a competitor's name over the
    // wrong set of stories is worse than reading nothing.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const slow: Array<() => void> = [];
    apiFetch.mockImplementation((path: string) => {
      const q = new URL(path, "http://test").searchParams.get("q");
      if (q === "is") {
        return new Promise<ArticleListOut>((resolve) => {
          slow.push(() => resolve(list([article("old", "ESKİ sorgunun haberi")])));
        });
      }
      return Promise.resolve(list([article("new", "IST haberi")]));
    });

    render(<QuickSearch />);
    await type(user, "is");
    await type(user, "t");

    expect(await screen.findByText("IST haberi")).toBeInTheDocument();

    // The superseded request answers now. It must change nothing.
    await act(async () => {
      slow.forEach((resolve) => resolve());
      await Promise.resolve();
    });

    expect(screen.getByText("IST haberi")).toBeInTheDocument();
    expect(screen.queryByText("ESKİ sorgunun haberi")).not.toBeInTheDocument();
    expect(asked()).toEqual(["is", "ist"]);
  });

  it("says the search could not be read instead of reporting no results", async () => {
    // "…için henüz sonuç yok" is a claim about the archive. It used to be what
    // a 500 printed, because the catch collapsed the failure into `null` --
    // the same value an empty answer produced.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    apiFetch.mockRejectedValue(new Error("API request failed: 500"));

    render(<QuickSearch />);
    await type(user, "ist");

    expect(await screen.findByText("Arama sonuçları okunamadı.")).toBeInTheDocument();
    expect(screen.queryByText(/henüz sonuç yok/)).not.toBeInTheDocument();

    // ...and it can be asked again, in place, without losing the typed query.
    apiFetch.mockResolvedValue(list([article("a1", "IST haberi")]));
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(await screen.findByText("IST haberi")).toBeInTheDocument();
  });

  it("still says 'no results' when the search genuinely found none", async () => {
    // The other half of the same rule: a real empty answer must keep reading
    // as a measurement, not get relabelled as an outage.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    apiFetch.mockResolvedValue(list([]));

    render(<QuickSearch />);
    await type(user, "ist");

    expect(await screen.findByText(/henüz sonuç yok/)).toBeInTheDocument();
    expect(screen.queryByText("Arama sonuçları okunamadı.")).not.toBeInTheDocument();
  });

  it("stops the spinner when the box is emptied", async () => {
    // The spinner used to run forever: `setLoading(true)` fired on every
    // keystroke including the one that emptied the box, and the effect's early
    // return then skipped the `finally` that was the only thing turning it off.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    apiFetch.mockResolvedValue(list([article("a1", "IST haberi")]));

    render(<QuickSearch />);
    await type(user, "ist");
    await screen.findByText("IST haberi");

    await user.clear(screen.getByRole("textbox"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    await waitFor(() =>
      expect(document.querySelector(".animate-spin")).not.toBeInTheDocument(),
    );
    // The dropdown goes with it -- there is no query for it to describe.
    expect(screen.queryByText("IST haberi")).not.toBeInTheDocument();
  });
});
