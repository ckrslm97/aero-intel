import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourceFilterRow } from "./source-filter-row";
import { windowOption } from "@/lib/gazete";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const EXCLUDED = ["safety"] as const;

function facets(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    name: `Outlet ${index + 1}`,
    tier: "trade",
    count: count - index,
  }));
}

function renderRow(props: Partial<React.ComponentProps<typeof SourceFilterRow>> = {}) {
  return render(
    <SourceFilterRow
      window={windowOption("30d")}
      category="revenue_management"
      minImportance={0.47}
      excludedCategories={EXCLUDED}
      value={null}
      onChange={() => {}}
      {...props}
    />,
  );
}

describe("SourceFilterRow", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("asks the facet endpoint for the same window and quality filters the list uses", async () => {
    // A chip promising rows the filtered list would never render is a chip
    // that lies -- so the facets have to be counted under the list's own
    // predicate, not over the whole archive.
    apiFetch.mockResolvedValue(facets(3));
    renderRow();

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain("/articles/source-facets");
    expect(url).toContain("days=30");
    expect(url).toContain("category=revenue_management");
    expect(url).toContain("translated_only=true");
    expect(url).toContain("min_importance=0.47");
    expect(url).toContain("exclude_categories=safety");
  });

  it("sends no time param at all on the Hepsi window", async () => {
    apiFetch.mockResolvedValue(facets(3));
    renderRow({ window: windowOption("all") });

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).not.toContain("days=");
    expect(url).not.toContain("hours=");
  });

  it("names each outlet with its count", async () => {
    apiFetch.mockResolvedValue(facets(2));
    renderRow();

    expect(await screen.findByRole("button", { name: "Outlet 1, 2 haber" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hepsi" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("reports the outlet by its exact name, which is what the filter matches on", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    apiFetch.mockResolvedValue(facets(2));
    renderRow({ onChange });

    await user.click(await screen.findByRole("button", { name: "Outlet 1, 2 haber" }));

    expect(onChange).toHaveBeenCalledWith("Outlet 1");
  });

  it("clears the filter when the active chip is pressed again", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    apiFetch.mockResolvedValue(facets(2));
    renderRow({ value: "Outlet 1", onChange });

    await user.click(await screen.findByRole("button", { name: "Outlet 1, 2 haber" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("keeps the row compact, revealing the tail behind an expander", async () => {
    const user = userEvent.setup();
    apiFetch.mockResolvedValue(facets(13));
    renderRow();

    await screen.findByRole("button", { name: "Outlet 1, 13 haber" });
    expect(screen.queryByRole("button", { name: "Outlet 11, 3 haber" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "+3 kaynak daha" }));

    expect(await screen.findByRole("button", { name: "Outlet 11, 3 haber" })).toBeInTheDocument();
  });

  it("renders nothing when the window has only one outlet in it", async () => {
    // "Hepsi | Reuters" over a list that is entirely Reuters is a control with
    // no choice in it.
    apiFetch.mockResolvedValue(facets(1));
    const { container } = renderRow();

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the facet request fails", async () => {
    apiFetch.mockRejectedValue(new Error("boom"));
    const { container } = renderRow();

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
