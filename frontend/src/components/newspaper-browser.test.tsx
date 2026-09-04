import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { currentParams, resetNavigation } from "@/lib/__fixtures__/next-navigation";

import { NewspaperBrowser } from "./newspaper-browser";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));
vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// The paper's five content blocks fetch and render their own lists; this file
// is about the FILTER BAR above them, so they are stubbed to keep the test
// about the thing it names.
vi.mock("@/components/gazete/today-intelligence", () => ({
  TodayIntelligence: () => <div data-testid="today" />,
}));
vi.mock("@/components/gazete/event-radar-strip", () => ({
  EventRadarStrip: () => <div data-testid="radar" />,
}));
vi.mock("@/components/gazete/event-timeline", () => ({
  EventTimeline: () => <div data-testid="timeline" />,
}));
vi.mock("@/components/gazete/news-section", () => ({
  NewsSection: () => <div data-testid="section" />,
}));
vi.mock("@/components/gazete/event-detail-drawer", () => ({
  EventDetailDrawer: () => null,
}));

beforeEach(() => {
  resetNavigation("/");
  apiFetch.mockReset();
  apiFetch.mockResolvedValue([]);
});

async function openFilters() {
  const user = userEvent.setup();
  render(<NewspaperBrowser />);
  await user.click(screen.getByRole("button", { name: /Filtreler/ }));
  return user;
}

/** THE DEFECT. This page kept a local `Chip` and `FilterRow` -- the eighth copy
 * of the app's filter chip, and the one on its busiest filter surface. Five
 * chip rows, none of them announcing `aria-pressed`, none of them inside a
 * `role="group"` naming the axis, none with a visible focus ring:
 * `grep -c aria-pressed` over this file returned 0. A screen reader read the
 * whole panel as an undifferentiated list of nouns, and a keyboard reader
 * could not see where they were in it. */
describe("gazete filtre çubuğu", () => {
  it("her satırı adıyla bir gruba bağlar", async () => {
    await openFilters();
    // "Dönem" is the row above the panel, whose name is `sr-only` because a
    // drawn label pushes the Filtreler toggle onto a second line -- the name
    // still has to EXIST, which is the half that was missing.
    for (const axis of ["Dönem", "Bölge", "Havayolu"]) {
      expect(screen.getByRole("group", { name: axis })).toBeInTheDocument();
    }
  });

  it("hangi chip'in süzdüğünü duyurur", async () => {
    const user = await openFilters();
    const region = screen.getByRole("group", { name: "Bölge" });

    // Every control in the row says what kind of control it is -- the negative
    // half of the rule, since one silent button in a row of eleven is exactly
    // what this panel used to be made of. The row holds one disclosure (the
    // "Harita" toggle), which states `aria-expanded` instead; nothing may
    // state neither.
    const buttons = within(region).getAllByRole("button");
    expect(buttons.length).toBeGreaterThan(3);
    for (const button of buttons) {
      expect(
        button.hasAttribute("aria-pressed") || button.hasAttribute("aria-expanded"),
      ).toBe(true);
    }

    const all = within(region).getByRole("button", { name: "Tüm bölgeler" });
    const europe = within(region).getByRole("button", { name: "Avrupa" });
    expect(all).toHaveAttribute("aria-pressed", "true");
    expect(europe).toHaveAttribute("aria-pressed", "false");

    await user.click(europe);
    expect(currentParams().get("region")).toBe("europe");
    expect(
      within(screen.getByRole("group", { name: "Bölge" })).getByRole("button", {
        name: "Avrupa",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(screen.getByRole("group", { name: "Bölge" })).getByRole("button", {
        name: "Tüm bölgeler",
      }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("dönem düğmeleri de chip'tir, çıplak düğme değil", async () => {
    const user = await openFilters();
    const period = screen.getByRole("group", { name: "Dönem" });
    const chips = within(period).getAllByRole("button");
    for (const chip of chips) {
      // `type="button"` was missing outright here: inside a form these would
      // have submitted it.
      expect(chip).toHaveAttribute("type", "button");
      expect(chip).toHaveAttribute("aria-pressed");
      // A visible focus ring, on the surface a keyboard reader navigates
      // entirely through chip rows.
      expect(chip.className).toContain("focus-visible:outline-ring");
    }
    const pressed = chips.filter((c) => c.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);

    const other = chips.find((c) => c.getAttribute("aria-pressed") === "false")!;
    await user.click(other);
    expect(currentParams().get("window")).toBeTruthy();
  });
});
