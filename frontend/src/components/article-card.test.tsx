import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ArticleOut } from "@/lib/types";

import { ArticleCard } from "./article-card";

// The card opens the shared analysis drawer, which lives on a provider in the
// app shell. These tests are about what the card PRINTS, so the provider is
// stubbed rather than mounted.
vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open: vi.fn() }),
}));

const SOURCE_NAME = "Reuters";

function article(overrides: Partial<ArticleOut> = {}): ArticleOut {
  return {
    id: "a1",
    url: "https://example.com/story",
    title: "Rival cuts transatlantic fares",
    author: null,
    published_at: "2026-08-28T14:32:00Z",
    fetched_at: "2026-08-28T15:00:00Z",
    status: "published",
    source: {
      id: "s1",
      name: SOURCE_NAME,
      url: "https://reuters.com",
      category: "agency",
      trust_weight: 0.9,
      tier: "agency",
    },
    enrichment: {
      headline: "Rival cuts transatlantic fares",
      summary: "The carrier dropped fares on nine routes.",
      category: "revenue_management",
      subcategory: "pricing",
      region: "europe",
      importance_score: 0.48,
      intelligence_score: 0.71,
      rm_impact: 0.8,
      demand_impact: null,
      capacity_impact: null,
      score_detail: null,
      sentiment: "neutral",
      confidence_score: 0.76,
      corroborating_source_count: 3,
      verified_at: "2026-08-28T15:00:00Z",
      tags: "airline,country",
      headline_tr: "Rakip Atlantik ötesi ücretleri düşürdü",
      summary_tr: "Taşıyıcı dokuz hatta ücretleri indirdi.",
      translated_at: "2026-08-28T15:05:00Z",
      is_translated: true,
      risk_severity: null,
      why_important_tr: null,
    },
    reading_time_minutes: 3,
    airlines: [],
    airports: [],
    ...overrides,
  };
}

describe("ArticleCard, grid variant (the Gazete tile)", () => {
  it("never prints the outlet's name or its tier", () => {
    // The product owner's rule, and the reason this test exists at all: the
    // paper's cards carry the story, not the newsroom that filed it.
    // Provenance lives in the analysis drawer, one click in.
    render(<ArticleCard article={article()} variant="grid" />);

    expect(screen.queryByText(SOURCE_NAME)).not.toBeInTheDocument();
    expect(screen.queryByText("Ajans")).not.toBeInTheDocument();
    // "+2 kaynak" was corroboration, which is provenance too -- the drawer's
    // "Doğrulayan N kaynak" is the copy of it that can be opened and checked.
    expect(screen.queryByText(/kaynak/i)).not.toBeInTheDocument();
  });

  it("prints the four things it is supposed to: headline, summary, beat, date", () => {
    render(<ArticleCard article={article()} variant="grid" />);

    expect(screen.getByText("Rakip Atlantik ötesi ücretleri düşürdü")).toBeInTheDocument();
    expect(screen.getByText("Taşıyıcı dokuz hatta ücretleri indirdi.")).toBeInTheDocument();
    expect(screen.getByText("Gelir Yönetimi")).toBeInTheDocument();
    // The subcategory, which the tile did not carry before -- "Fiyatlandırma"
    // is the difference between a fare move and a load-factor report.
    expect(screen.getByText("Fiyatlandırma")).toBeInTheDocument();
    // A day AND a time. The list used to be grouped under sticky per-day
    // headers that carried the date; it is grouped by section now, so a tile
    // saying only "14:32" would not say which day.
    expect(screen.getByText(/28 Ağu/)).toBeInTheDocument();
  });

  it("draws no subcategory line when the classifier assigned none", () => {
    const item = article();
    render(
      <ArticleCard
        article={{ ...item, enrichment: { ...item.enrichment!, subcategory: null } }}
        variant="grid"
      />,
    );

    expect(screen.getByText("Gelir Yönetimi")).toBeInTheDocument();
    expect(screen.queryByText("Fiyatlandırma")).not.toBeInTheDocument();
  });
});

describe("ArticleCard, shared variants", () => {
  it("still badges the outlet on the compact variant", () => {
    // Guarding the OTHER direction. `compact`/`top` are used by the archive,
    // BİZ, hub, search and per-date-edition pages -- source-browsing surfaces
    // where the outlet is the point. Removing the badge from the Gazete's
    // tile must not quietly remove it from all five.
    render(<ArticleCard article={article()} variant="compact" />);

    expect(screen.getByText(SOURCE_NAME)).toBeInTheDocument();
  });

  it("still badges the outlet on the top variant", () => {
    render(<ArticleCard article={article()} variant="top" />);

    expect(screen.getByText(SOURCE_NAME)).toBeInTheDocument();
  });
});
