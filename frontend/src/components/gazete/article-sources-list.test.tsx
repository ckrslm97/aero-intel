import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("fetches the group lazily, per article, and abortably", async () => {
    apiFetch.mockResolvedValue([row()]);
    render(<ArticleSourcesList articleId="abc-123" />);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/articles/abc-123/sources", {
        cache: "default",
        // The signal arrived with `useDataSource`: opening three stories in a
        // row no longer leaves two abandoned requests queued ahead of the one
        // the reader is waiting for.
        signal: expect.any(AbortSignal),
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
    // on it and must never take the drawer down. The line says the list was
    // not READ -- "yüklenemedi" over an empty section reads as "no other
    // outlet carried this", which is a claim about the press, not about us.
    apiFetch.mockRejectedValue(new Error("boom"));
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText(/Kaynak listesi okunamadı/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Yeniden dene/ })).toBeInTheDocument();
  });

  it("does not hide one article's sources behind another article's failure", async () => {
    // THE UNKEYED FLAG. `failed` was a bare boolean, set on any rejection and
    // never cleared, while `rows` was keyed by article id. So after one story's
    // sources failed, every story the reader opened next showed the error --
    // its own rows fetched, parsed and held in state, sitting behind a verdict
    // that belonged to a different question.
    apiFetch.mockRejectedValue(new Error("boom"));
    const { rerender } = render(<ArticleSourcesList articleId="abc-123" />);
    expect(await screen.findByText(/Kaynak listesi okunamadı/)).toBeInTheDocument();

    apiFetch.mockResolvedValue([row()]);
    rerender(<ArticleSourcesList articleId="def-456" />);

    expect(await screen.findByText("Reuters")).toBeInTheDocument();
    expect(screen.queryByText(/okunamadı/)).not.toBeInTheDocument();
  });

  it("re-asks for the same article, and says so while it is asking", async () => {
    const user = userEvent.setup();
    apiFetch.mockRejectedValue(new Error("boom"));
    render(<ArticleSourcesList articleId="abc-123" />);
    const retry = await screen.findByRole("button", { name: /Yeniden dene/ });

    let answer: (rows: unknown[]) => void = () => {};
    apiFetch.mockImplementation(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    await user.click(retry);

    expect(await screen.findByRole("button", { name: /Deneniyor…/ })).toBeDisabled();

    answer([row()]);
    expect(await screen.findByText("Reuters")).toBeInTheDocument();
    // The retry asked the SAME question, not the first one again by accident.
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/articles/abc-123/sources",
      expect.objectContaining({ cache: "default" }),
    );
  });

  it("handles a story nothing else picked up", async () => {
    apiFetch.mockResolvedValue([row()]);
    render(<ArticleSourcesList articleId="abc-123" />);

    expect(await screen.findByText("Carrier raises fares")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});
