import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BreakingStrip } from "./breaking-strip";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const open = vi.hoisted(() => vi.fn());
vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open }),
}));

const article = (overrides: Record<string, unknown> = {}) => ({
  id: "a1",
  url: "https://example.com/a",
  title: "Carrier raises fares",
  author: null,
  published_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
  fetched_at: new Date().toISOString(),
  status: "enriched",
  source: {
    id: "s1",
    name: "Reuters",
    url: "https://example.com",
    category: "other",
    trust_weight: 0.9,
    tier: "agency",
  },
  enrichment: {
    headline: "Carrier raises fares",
    headline_tr: "Taşıyıcı ücretleri artırdı",
    summary: "",
    summary_tr: "",
    category: "revenue_management",
    subcategory: null,
    region: null,
    importance_score: 0.8,
    sentiment: "neutral",
    confidence_score: 0.8,
    corroborating_source_count: 2,
    verified_at: null,
    tags: "",
    translated_at: new Date().toISOString(),
    is_translated: true,
    risk_severity: null,
    why_important_tr: null,
  },
  reading_time_minutes: 2,
  airlines: [],
  airports: [],
  ...overrides,
});

const props = {
  category: "revenue_management",
  minImportance: 0.47,
  excludedCategories: ["safety"] as const,
};

describe("BreakingStrip", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    open.mockReset();
  });

  it("asks the API for a six-hour window rather than filtering client-side", async () => {
    // There is no breaking flag in this data and there should not be one: a
    // stored boolean would need a cron to un-set it six hours later.
    apiFetch.mockResolvedValue({ total: 1, items: [article()] });
    render(<BreakingStrip {...props} />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain("hours=6");
    expect(url).toContain("category=revenue_management");
    expect(url).toContain("translated_only=true");
    expect(url).toContain("exclude_categories=safety");
  });

  it("shows the Turkish headline, its age and its source", async () => {
    apiFetch.mockResolvedValue({ total: 1, items: [article()] });
    render(<BreakingStrip {...props} />);

    expect(await screen.findByText("Taşıyıcı ücretleri artırdı")).toBeInTheDocument();
    expect(screen.getByText("2 sa önce")).toBeInTheDocument();
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    expect(screen.getByLabelText("Son dakika")).toBeInTheDocument();
  });

  it("renders nothing at all on a quiet six hours", async () => {
    // A permanent empty box at the top of the paper teaches the reader to
    // scroll past the place breaking news will appear.
    apiFetch.mockResolvedValue({ total: 0, items: [] });
    const { container } = render(<BreakingStrip {...props} />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the request fails", async () => {
    apiFetch.mockRejectedValue(new Error("boom"));
    const { container } = render(<BreakingStrip {...props} />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
