import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";

import { RecommendationsClient } from "./recommendations-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

/** Every `/recommendations` path asked for, in order. The filters are a server
 * round trip, so the query string is where their correctness is observable. */
const requested: string[] = [];

function serve() {
  apiFetch.mockImplementation((path: string) => {
    requested.push(path);
    return Promise.resolve({
      generated_at: "2026-09-02T09:00:00Z",
      windows: {},
      days: 7,
      count: 1,
      items: [
        {
          id: "r1",
          title: "Avrupa'da fiyat baskısı artıyor",
          rationale: "Üç rakip aynı hafta indirim açtı.",
          severity: "high",
          category: "revenue_management",
          region: "europe",
          airline_code: null,
          evidence: [],
          metric: null,
        },
      ],
    });
  });
}

/** The query of the most recent request, parsed. */
const lastQuery = () => new URL(requested.at(-1)!, "http://test").searchParams;

describe("RecommendationsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    requested.length = 0;
    resetNavigation("/insights");
    serve();
  });

  it("opens on the pinned beat and the 7-day window, with a clean URL", async () => {
    render(<RecommendationsClient />);

    await screen.findByText("Avrupa'da fiyat baskısı artıyor");
    expect(lastQuery().get("days")).toBe("7");
    expect(lastQuery().getAll("category")).toEqual(["revenue_management"]);
    // The defaults write no keys, so "untouched" has exactly one spelling.
    expect(currentParams().toString()).toBe("");
  });

  it("restores every axis from a deep link, multi-select included", async () => {
    setUrl(
      "/insights?tab=oneriler&days=30&category=fleet&region=europe&region=middle-east&airline=TK",
    );
    render(<RecommendationsClient />);

    await screen.findByText("Avrupa'da fiyat baskısı artıyor");
    expect(lastQuery().get("days")).toBe("30");
    expect(lastQuery().getAll("category")).toEqual(["fleet"]);
    expect(lastQuery().getAll("region")).toEqual(["europe", "middle-east"]);
    expect(lastQuery().getAll("airline")).toEqual(["TK"]);
  });

  it("writes each pressed chip into the URL without disturbing the tab", async () => {
    const user = userEvent.setup();
    setUrl("/insights?tab=oneriler");
    render(<RecommendationsClient />);
    await screen.findByText("Avrupa'da fiyat baskısı artıyor");

    await user.click(screen.getByRole("button", { name: "Son 30 gün" }));
    await waitFor(() => expect(currentParams().get("days")).toBe("30"));

    await user.click(screen.getByRole("button", { name: "Avrupa" }));
    await waitFor(() => expect(currentParams().getAll("region")).toEqual(["europe"]));

    // The tab that put the reader here survives every write -- it is the half
    // of the link that decides which screen the recipient even lands on.
    expect(currentParams().get("tab")).toBe("oneriler");
  });

  it("says 'every category' explicitly rather than by omission", async () => {
    const user = userEvent.setup();
    render(<RecommendationsClient />);
    await screen.findByText("Avrupa'da fiyat baskısı artıyor");

    await user.click(
      screen.getAllByRole("button", { name: "Tümü" })[0],
    );

    // `category=all`, not an absent key: absent already means "open on Gelir
    // Yönetimi", so an empty URL would re-narrow the page for whoever the link
    // was sent to -- the sender's "show me everything" reversed in transit.
    await waitFor(() => expect(currentParams().getAll("category")).toEqual(["all"]));
    // ...and the sentinel is a statement about the URL, never a request: there
    // is no category named "all" to ask the API for.
    await waitFor(() => expect(lastQuery().getAll("category")).toEqual([]));
  });

  it("falls back to the default beat when the link names an unknown slug", async () => {
    // A typo must not silently widen the page past what the link asked for.
    setUrl("/insights?tab=oneriler&category=uydurma");
    render(<RecommendationsClient />);

    await screen.findByText("Avrupa'da fiyat baskısı artıyor");
    expect(lastQuery().getAll("category")).toEqual(["revenue_management"]);
  });

  it("offers a retry when the recommendations cannot be read, and prints no empty-state claim", async () => {
    // "Bu filtrelerle öne çıkan bir örüntü yok" is a statement about the
    // selected filters. The failure branch used to be a grey sentence with no
    // way to ask again, one keystroke away from being read as that claim.
    const user = userEvent.setup();
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      return Promise.reject(new Error("API request failed: 500"));
    });

    render(<RecommendationsClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Bu filtrelerle öne çıkan bir örüntü yok"),
    ).not.toBeInTheDocument();

    serve();
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(
      await screen.findByText("Avrupa'da fiyat baskısı artıyor"),
    ).toBeInTheDocument();
  });

  it("keeps the empty-state claim for a filter set that genuinely matches nothing", async () => {
    // The negative half: an answered request with no items is a measurement
    // about these filters and keeps its own sentence.
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      return Promise.resolve({
        generated_at: "2026-09-02T09:00:00Z",
        windows: {},
        days: 7,
        count: 0,
        items: [],
      });
    });

    render(<RecommendationsClient />);

    expect(
      await screen.findByText("Bu filtrelerle öne çıkan bir örüntü yok"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Veri geçici olarak kullanılamıyor."),
    ).not.toBeInTheDocument();
  });

  it("never shows the previous filter set's cards under the new chips", async () => {
    // The window a slow request opens. `useDataSource` is keyed on the query
    // string, so the moment a chip moves the cards for the old question are
    // gone -- an argument an analyst pastes into a message must not be built
    // out of a different filter's evidence.
    const user = userEvent.setup();
    const held: Array<() => void> = [];
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.includes("days=30")) {
        return new Promise((resolve) =>
          held.push(() =>
            resolve({
              generated_at: "2026-09-02T09:00:00Z",
              windows: {},
              days: 30,
              count: 0,
              items: [],
            }),
          ),
        );
      }
      return Promise.resolve({
        generated_at: "2026-09-02T09:00:00Z",
        windows: {},
        days: 7,
        count: 1,
        items: [
          {
            id: "r1",
            title: "Avrupa'da fiyat baskısı artıyor",
            rationale: "Üç rakip aynı hafta indirim açtı.",
            severity: "high",
            category: "revenue_management",
            region: "europe",
            airline_code: null,
            evidence: [],
            metric: null,
          },
        ],
      });
    });

    render(<RecommendationsClient />);
    await screen.findByText("Avrupa'da fiyat baskısı artıyor");

    await user.click(screen.getByRole("button", { name: "Son 30 gün" }));

    await waitFor(() =>
      expect(screen.queryByText("Avrupa'da fiyat baskısı artıyor")).not.toBeInTheDocument(),
    );
    // ...and no premature "nothing matches" either: nothing has answered yet.
    expect(
      screen.queryByText("Bu filtrelerle öne çıkan bir örüntü yok"),
    ).not.toBeInTheDocument();

    held.forEach((resolve) => resolve());
    expect(
      await screen.findByText("Bu filtrelerle öne çıkan bir örüntü yok"),
    ).toBeInTheDocument();
  });
});
