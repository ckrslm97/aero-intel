import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";

import { CampaignWindows } from "./campaign-windows";

const dated = () =>
  promotion({
    sale_starts: "2026-09-01",
    sale_ends: "2026-09-15",
    sale_range_tr: "01 Eyl – 15 Eyl",
    travel_starts: "2026-10-01",
    travel_ends: "2026-12-31",
    travel_range_tr: "01 Eki – 31 Ara",
  });

describe("CampaignWindows", () => {
  it("names the two windows separately and never merges them into one range", () => {
    // §11: "when it can be bought" and "when it can be flown" are different
    // facts about different dates. A desk that reads one as the other prices
    // against a window that closed two months ago.
    const { container } = render(<CampaignWindows promo={dated()} />);

    expect(screen.getByText("Satış")).toBeInTheDocument();
    expect(screen.getByText("Seyahat")).toBeInTheDocument();
    expect(screen.getByText("01 Eyl – 15 Eyl")).toBeInTheDocument();
    expect(screen.getByText("01 Eki – 31 Ara")).toBeInTheDocument();

    expect(container.querySelectorAll('[data-window="sale"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-window="travel"]')).toHaveLength(1);
  });

  it("draws the two windows as two tracks with different fills", () => {
    const { container } = render(<CampaignWindows promo={dated()} />);

    const sale = container.querySelector('[data-track="sale"]') as HTMLElement;
    const travel = container.querySelector('[data-track="travel"]') as HTMLElement;
    expect(sale).toBeTruthy();
    expect(travel).toBeTruthy();

    // Colour alone would not survive greyscale or a reader who cannot
    // separate the hues, so the travel bar is hatched and the sale bar is
    // solid. The two must not render identically.
    expect(sale.className).toContain("bg-foreground");
    expect(travel.className).not.toContain("bg-foreground");
    expect(travel.style.backgroundImage).toContain("repeating-linear-gradient");
    expect(sale.style.backgroundImage).toBe("");
  });

  it("places each window on its own part of the shared scale", () => {
    const { container } = render(<CampaignWindows promo={dated()} />);
    const sale = container.querySelector('[data-track="sale"]') as HTMLElement;
    const travel = container.querySelector('[data-track="travel"]') as HTMLElement;

    // Selling runs first, flying runs later: the offset between them is the
    // thing a row exists to show.
    expect(parseFloat(sale.style.marginLeft)).toBe(0);
    expect(parseFloat(travel.style.marginLeft)).toBeGreaterThan(0);
    expect(sale.style.width).not.toBe(travel.style.width);
  });

  it("draws no bar at all for a window nobody published", () => {
    // An unstated window is not a zero-length one, and a hairline at the left
    // edge would read as "starts today".
    const { container } = render(
      <CampaignWindows
        promo={promotion({
          sale_starts: "2026-09-01",
          sale_ends: "2026-09-15",
          sale_range_tr: "01 Eyl – 15 Eyl",
          travel_starts: null,
          travel_ends: null,
          travel_range_tr: "Belirtilmedi",
        })}
      />,
    );

    expect(container.querySelector('[data-track="sale"]')).toBeTruthy();
    expect(container.querySelector('[data-track="travel"]')).toBeNull();
    // The window is still NAMED. Hiding the row would make a half-known
    // campaign look fully known.
    expect(screen.getByText("Seyahat")).toBeInTheDocument();
    expect(screen.getByText("Belirtilmedi")).toBeInTheDocument();
  });

  it("dissolves the edge of an open-ended window instead of drawing one", () => {
    const { container } = render(
      <CampaignWindows
        promo={promotion({
          sale_starts: "2026-09-01",
          sale_ends: null,
          sale_range_tr: "01 Eyl – bitiş belirtilmedi",
          travel_starts: "2026-09-05",
          travel_ends: "2026-10-05",
          travel_range_tr: "05 Eyl – 05 Eki",
        })}
      />,
    );
    const sale = container.querySelector('[data-track="sale"]') as HTMLElement;
    expect(sale.style.maskImage).toContain("transparent");
  });

  it("survives a campaign with no dates anywhere", () => {
    const { container } = render(<CampaignWindows promo={promotion()} />);
    expect(container.querySelectorAll("[data-track]")).toHaveLength(0);
    expect(screen.getAllByText("Belirtilmedi")).toHaveLength(2);
  });
});
