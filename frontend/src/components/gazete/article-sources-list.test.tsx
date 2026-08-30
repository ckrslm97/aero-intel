import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArticleSourcesList } from "./article-sources-list";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const row = (overrides: Record<string, unknown> = {}) => ({
  source_name: "Reuters",
  source_tier: "agency",
  trust_weight: 0.9,
  url: "https://example.com/a",
  published_at: "2026-08-30T09:00:00Z",
  title: "Carrier raises fares",
  is_primary: true,
  ...overrides,
});

describe("ArticleSourcesList", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("fetches the group lazily, per article", async () => {
    apiFetch.mockResolvedValue([row()]);
    render(<ArticleSourcesList articleId="abc-123" />);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/articles/abc-123/sources", {
        cache: "default",
      }),
    );
  });

  it("renders each telling with its outlet, tier and time", async () => {
    apiFetch.mockResolvedValue([
      row(),
      row({
        source_name: "Aviation Week",
        source_tier: "trade",
        url: "https://example.com/b",
        title: "Fare rise confirmed",
        is_primary: false,
      }),
    ]);
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText("Reuters")).toBeInTheDocument();
    expect(screen.getByText("Aviation Week")).toBeInTheDocument();
    // Turkish tier labels, the same words the Risk Radarı prints.
    expect(screen.getByText("Ajans")).toBeInTheDocument();
    expect(screen.getByText("Basın")).toBeInTheDocument();
    // The count is the group size, shown beside the heading.
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("marks the canonical article so the corroboration is distinguishable", async () => {
    apiFetch.mockResolvedValue([row(), row({ url: "https://example.com/b", is_primary: false })]);
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText("asıl")).toBeInTheDocument();
  });

  it("says the list is a publication order, not the event's timeline", async () => {
    // A vertical list of timestamps reads as the event's own chronology
    // unless it says otherwise -- the same caveat the risk drawer carries.
    apiFetch.mockResolvedValue([row()]);
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(
      await screen.findByText(/olayın kendi zaman çizelgesi değildir/i),
    ).toBeInTheDocument();
  });

  it("degrades to a line of text when the request fails", async () => {
    // The article is already on screen; the corroboration is an elaboration
    // on it and must never take the drawer down.
    apiFetch.mockRejectedValue(new Error("boom"));
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText("Kaynak listesi yüklenemedi.")).toBeInTheDocument();
  });

  it("handles a story nothing else picked up", async () => {
    apiFetch.mockResolvedValue([row()]);
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText("Carrier raises fares")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});
