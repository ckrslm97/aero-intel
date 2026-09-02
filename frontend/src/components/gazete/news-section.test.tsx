import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_FILTERS, MIN_INTELLIGENCE } from "@/lib/gazete";
import type { ArticleOut } from "@/lib/types";

import { NewsSection } from "./news-section";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));
vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open: vi.fn() }),
}));

function article(id: string, headline: string): ArticleOut {
  return {
    id,
    url: "https://example.com/story",
    title: headline,
    author: null,
    published_at: "2026-08-28T14:32:00Z",
    fetched_at: "2026-08-28T15:00:00Z",
    status: "published",
    source: {
      id: "s1",
      name: "Reuters",
      url: "https://reuters.com",
      category: "agency",
      trust_weight: 0.9,
      tier: "agency",
    },
    enrichment: {
      headline,
      summary: "",
      category: "revenue_management",
      subcategory: "pricing",
      region: "europe",
      importance_score: 0.48,
      intelligence_score: 0.71,
      rm_impact: null,
      demand_impact: null,
      capacity_impact: null,
      score_detail: null,
      sentiment: "neutral",
      confidence_score: 0.76,
      corroborating_source_count: 1,
      verified_at: null,
      tags: "",
      headline_tr: headline,
      summary_tr: "Özet.",
      translated_at: "2026-08-28T15:05:00Z",
      is_translated: true,
      risk_severity: null,
      why_important_tr: null,
    },
    reading_time_minutes: 3,
    airlines: [],
    airports: [],
  };
}

describe("NewsSection", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("queries exactly one category, translated and judged", async () => {
    // The paper used to make ONE query under a tab row, which is why it needed
    // `exclude_categories` to keep the other eight beats out. Per-section
    // queries make that exclusion structural.
    apiFetch.mockResolvedValue({ total: 0, items: [] });
    render(<NewsSection categorySlug="airport" filters={DEFAULT_FILTERS} />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = new URL(apiFetch.mock.calls[0][0], "http://test");
    expect(url.searchParams.get("category")).toBe("airport");
    expect(url.searchParams.get("translated_only")).toBe("true");
    expect(url.searchParams.get("min_intelligence")).toBe(String(MIN_INTELLIGENCE));
    expect(url.searchParams.getAll("exclude_categories")).toEqual([]);
    // The default window is three days, sent as `days`, never alongside `hours`.
    expect(url.searchParams.get("days")).toBe("3");
    expect(url.searchParams.get("hours")).toBeNull();
  });

  it("captions the section with the SERVER's total, not the cards on screen", async () => {
    // The two differ exactly when the cap fires, and a caption that quietly
    // said "2" for a section holding 40 would be the heading lying about its
    // own list.
    apiFetch.mockResolvedValue({
      total: 40,
      items: [article("a1", "Slot tavanı"), article("a2", "Terminal kapasitesi")],
    });
    render(<NewsSection categorySlug="airport" filters={DEFAULT_FILTERS} />);

    expect(await screen.findByText(/40 kritik gelişme/)).toBeInTheDocument();
    expect(screen.getByText("Slot tavanı")).toBeInTheDocument();
  });

  it("keeps its heading and says so when the wire was quiet", async () => {
    // A news section does NOT hide itself. The two beats are the paper's
    // masthead promise, and a section that vanishes on a quiet day teaches the
    // reader that the page is unreliable rather than that the wire was quiet.
    apiFetch.mockResolvedValue({ total: 0, items: [] });
    render(<NewsSection categorySlug="airport" filters={DEFAULT_FILTERS} />);

    expect(await screen.findByText(/0 kritik gelişme/)).toBeInTheDocument();
    expect(screen.getByText("Havalimanı")).toBeInTheDocument();
    expect(screen.getByText(/Seçili dönemde \(son 3 gün\)/)).toBeInTheDocument();
  });

  it("names the window in force in the empty state, not a hard-coded one", async () => {
    apiFetch.mockResolvedValue({ total: 0, items: [] });
    render(
      <NewsSection
        categorySlug="revenue_management"
        filters={{ ...DEFAULT_FILTERS, window: "all" }}
      />,
    );

    expect(await screen.findByText(/Arşivde bu filtrelerle/)).toBeInTheDocument();
  });

  it("forwards the narrowing filters it was given", async () => {
    apiFetch.mockResolvedValue({ total: 0, items: [] });
    render(
      <NewsSection
        categorySlug="revenue_management"
        filters={{
          ...DEFAULT_FILTERS,
          subcategory: "pricing",
          region: "europe",
          country: "Germany",
          airline: "RIVALS",
        }}
      />,
    );

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = new URL(apiFetch.mock.calls[0][0], "http://test");
    expect(url.searchParams.get("subcategory")).toBe("pricing");
    expect(url.searchParams.get("region")).toBe("europe");
    expect(url.searchParams.get("country")).toBe("Germany");
    expect(url.searchParams.get("airline")).toBe("RIVALS");
  });

  it("says the section failed rather than showing it as empty", async () => {
    // "Nothing happened" and "we could not ask" are different statements, and
    // a down backend must not be reported as a quiet news day.
    apiFetch.mockRejectedValue(new Error("boom"));
    render(<NewsSection categorySlug="airport" filters={DEFAULT_FILTERS} />);

    expect(await screen.findByText(/yüklenemedi/)).toBeInTheDocument();
  });
});
