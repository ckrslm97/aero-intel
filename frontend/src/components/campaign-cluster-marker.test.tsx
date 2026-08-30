import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";

import { CampaignClusterMarker } from "./campaign-cluster-marker";

/** The Singapore Airlines day that caused this component to exist, shrunk to
 * three rows -- the count is the thing under test, not the number 23. */
const items = [
  promotion({
    id: "sq-1",
    airline_code: "SQ",
    airline_name: "Singapore Airlines",
    title_tr: "Singapur'a özel ücret",
    sale_starts: null,
    discount_pct: 25,
    detected_at: "2026-08-29T09:00:00Z",
  }),
  promotion({
    id: "sq-2",
    airline_code: "SQ",
    airline_name: "Singapore Airlines",
    title_tr: "Bali'ye özel ücret",
    sale_starts: null,
    discount_pct: null,
    attrs_json: { price_floor: 899, currency: "USD" },
    detected_at: "2026-08-29T09:05:00Z",
  }),
  promotion({
    id: "sq-3",
    airline_code: "SQ",
    airline_name: "Singapore Airlines",
    title_tr: "Sidney'e özel ücret",
    sale_starts: null,
    discount_pct: null,
    detected_at: "2026-08-29T09:10:00Z",
  }),
];

function renderMarker(overrides: Partial<Parameters<typeof CampaignClusterMarker>[0]> = {}) {
  const onSelect = vi.fn();
  render(
    <CampaignClusterMarker
      items={items}
      day="2026-08-29"
      airlineCode="SQ"
      airlineName="Singapore Airlines"
      color="#f5a623"
      gridColumn="12 / 13"
      isNew={() => false}
      onSelect={onSelect}
      {...overrides}
    />,
  );
  return { onSelect };
}

describe("CampaignClusterMarker", () => {
  it("draws one mark carrying the count, not one mark per campaign", () => {
    renderMarker();
    // One button on the grid, and the number on it is how many it stands for.
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("says in words what the count chip says in a number", () => {
    renderMarker();
    expect(
      screen.getByRole("button", {
        name: /Singapore Airlines, 3 kampanya, satış tarihi açıklanmadı, 29 Ağustos/,
      }),
    ).toBeInTheDocument();
  });

  it("flags the whole cluster once when any of its campaigns is new", () => {
    // Twenty-three identical badges was half the regression; one is the fact.
    renderMarker({ isNew: (promo) => promo.id === "sq-2" });
    expect(screen.getAllByText("Yeni")).toHaveLength(1);
  });

  it("lists every clustered campaign when the mark is clicked", async () => {
    const user = userEvent.setup();
    renderMarker();

    await user.click(screen.getByRole("button"));

    const panel = screen.getByRole("dialog", { name: "Singapore Airlines, 3 tarihsiz kampanya" });
    expect(panel).toBeInTheDocument();
    expect(screen.getByText("Singapur'a özel ücret")).toBeInTheDocument();
    expect(screen.getByText("Bali'ye özel ücret")).toBeInTheDocument();
    expect(screen.getByText("Sidney'e özel ücret")).toBeInTheDocument();
    // The one number each row has room for: a rate, or a starting price.
    expect(screen.getByText("%25")).toBeInTheDocument();
    expect(screen.getByText("899 USD")).toBeInTheDocument();
  });

  it("opens the drawer for the campaign whose row was clicked", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderMarker();

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button", { name: /Bali'ye özel ücret/ }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(items[1]);
    // The list gets out of the drawer's way rather than stacking on top of it.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    renderMarker();

    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes from the keyboard-reachable close button and hands focus back", async () => {
    const user = userEvent.setup();
    renderMarker();

    const marker = screen.getByRole("button", { name: /listeyi aç/ });
    await user.click(marker);
    await user.click(screen.getByRole("button", { name: "Listeyi kapat" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(marker).toHaveFocus();
  });

  it("tells assistive tech that the mark opens a list, and whether it is open", async () => {
    const user = userEvent.setup();
    renderMarker();

    const marker = screen.getByRole("button", { name: /listeyi aç/ });
    expect(marker).toHaveAttribute("aria-haspopup", "dialog");
    expect(marker).toHaveAttribute("aria-expanded", "false");

    await user.click(marker);
    expect(marker).toHaveAttribute("aria-expanded", "true");
  });
});
