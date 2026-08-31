import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CockpitSignal } from "@/lib/types";

const apiFetch = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetch(...args) };
});

import { TodaysIntelligence } from "./todays-intelligence";

const signal = (overrides: Partial<CockpitSignal> = {}): CockpitSignal => ({
  key: "fx",
  label_tr: "Kur Riski",
  level: "warning",
  level_label_tr: "Dikkat",
  value_label: "+%3,4",
  reason_tr: "USD/TRY 41,72 · 30 günde +%3,4.",
  method_tr: "Mutlak 30 günlük değişim bantlanır.",
  source: "Yahoo Finance",
  source_url: "https://finance.yahoo.com",
  href: "/kpi/fx_usd_try",
  as_of: "2026-08-30T11:00:00Z",
  ...overrides,
});

const INSIGHTS = {
  airline_momentum: [],
  new_route_signals: [],
  sentiment_by_category: [
    { category: "network", positive: 3, neutral: 5, negative: 1 },
    { category: "fleet", positive: 2, neutral: 4, negative: 6 },
  ],
  digest: { date: "2026-08-30", body: "Günün özeti gövdesi.", provider: "heuristic" },
};

const ARTICLES = {
  total: 2,
  items: [
    {
      id: "low",
      url: "https://example.test/low",
      title: "Low",
      author: null,
      published_at: "2026-08-30T09:00:00Z",
      fetched_at: "2026-08-30T09:05:00Z",
      status: "published",
      source: { id: "s", name: "Reuters", url: "u", category: "wire", trust_weight: 1 },
      enrichment: {
        headline: "Low importance story",
        summary: "s",
        category: "network",
        subcategory: null,
        region: "europe",
        importance_score: 0.51,
        sentiment: "neutral",
        confidence_score: 0.7,
        corroborating_source_count: 1,
        verified_at: null,
        tags: "",
        headline_tr: "Düşük önemli haber",
        summary_tr: null,
        translated_at: "2026-08-30T09:06:00Z",
        is_translated: true,
        risk_severity: null,
      },
      reading_time_minutes: 2,
      airlines: [],
      airports: [],
    },
    {
      id: "high",
      url: "https://example.test/high",
      title: "High",
      author: null,
      published_at: "2026-08-29T09:00:00Z",
      fetched_at: "2026-08-29T09:05:00Z",
      status: "published",
      source: { id: "s", name: "Reuters", url: "u", category: "wire", trust_weight: 1 },
      enrichment: {
        headline: "High importance story",
        summary: "s",
        category: "fleet",
        subcategory: null,
        region: "europe",
        importance_score: 0.95,
        sentiment: "negative",
        confidence_score: 0.9,
        corroborating_source_count: 6,
        verified_at: null,
        tags: "",
        headline_tr: "Yüksek önemli haber",
        summary_tr: null,
        translated_at: "2026-08-29T09:06:00Z",
        is_translated: true,
        risk_severity: "high",
      },
      reading_time_minutes: 2,
      airlines: [],
      airports: [],
    },
  ],
};

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/insights")) return Promise.resolve(INSIGHTS);
    if (path.startsWith("/articles")) return Promise.resolve(ARTICLES);
    // The two prose cards inside the expander fetch on mount.
    if (path.startsWith("/kokpit/pulse")) {
      return Promise.resolve({
        summary_tr: "Market Pulse gövdesi.",
        citations: [],
        generated_at: "2026-08-30T06:00:00Z",
      });
    }
    return Promise.reject(new Error(`unexpected fetch: ${path}`));
  });
});

describe("TodaysIntelligence", () => {
  it("shows the glanceable half first: signal chips, sentiment counts and the top three", async () => {
    render(<TodaysIntelligence signals={[signal()]} />);

    expect(screen.getByText("Kur Riski")).toBeInTheDocument();
    expect(screen.getByText("+%3,4")).toBeInTheDocument();

    // 5 positive + 9 neutral + 7 negative across the two categories.
    await waitFor(() => expect(screen.getByText("5")).toBeInTheDocument());
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText(/21 sınıflandırılmış haber/)).toBeInTheDocument();
  });

  it("ranks the top three by importance, not by recency", async () => {
    render(<TodaysIntelligence signals={[]} />);

    // The 0.95 story is the OLDER of the two; ordering by publication time
    // (which is what GET /articles does) would put it second.
    await waitFor(() => expect(screen.getByText("Yüksek önemli haber")).toBeInTheDocument());
    const headlines = screen.getAllByText(/önemli haber/).map((node) => node.textContent);
    expect(headlines).toEqual(["Yüksek önemli haber", "Düşük önemli haber"]);
  });

  it("keeps the AI prose collapsed by default, one click away", async () => {
    const user = userEvent.setup();
    render(<TodaysIntelligence signals={[]} />);

    const toggle = screen.getByRole("button", { name: /Detayı gör/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Market Pulse gövdesi.")).not.toBeInTheDocument();
    expect(screen.queryByText("Günün özeti gövdesi.")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // Both paragraphs appear, and the provider label rides along with the
    // digest -- hiding the prose must not quietly drop its attribution.
    await waitFor(() => expect(screen.getByText("Günün özeti gövdesi.")).toBeInTheDocument());
    expect(screen.getByText("Market Pulse gövdesi.")).toBeInTheDocument();
    expect(screen.getByText("Kural tabanlı")).toBeInTheDocument();
  });

  it("collapses again on a second click", async () => {
    const user = userEvent.setup();
    render(<TodaysIntelligence signals={[]} />);

    const toggle = screen.getByRole("button", { name: /Detayı gör/ });
    await user.click(toggle);
    await waitFor(() => expect(screen.getByText("Günün özeti gövdesi.")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Detayı gizle/ }));
    await waitFor(() =>
      expect(screen.queryByText("Günün özeti gövdesi.")).not.toBeInTheDocument(),
    );
  });

  it("says there is nothing classified rather than splitting zero three ways", async () => {
    apiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/insights")) {
        return Promise.resolve({ ...INSIGHTS, sentiment_by_category: [] });
      }
      if (path.startsWith("/articles")) return Promise.resolve({ total: 0, items: [] });
      return Promise.reject(new Error("unexpected"));
    });

    render(<TodaysIntelligence signals={[]} />);

    await waitFor(() =>
      expect(screen.getByText("Henüz sınıflandırılmış haber yok.")).toBeInTheDocument(),
    );
  });
});
