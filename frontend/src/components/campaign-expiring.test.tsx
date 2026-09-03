import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";

import { CampaignExpiring } from "./campaign-expiring";

const TODAY = "2026-09-03";

const closing = (id: string, saleEnds: string, overrides: Parameters<typeof promotion>[0] = {}) =>
  promotion({
    id,
    airline_code: "TK",
    airline_name: "Turkish Airlines",
    title_tr: `Kampanya ${id}`,
    status: "ACTIVE_BOOKING",
    discount_pct: 20,
    ond: "IST-LHR",
    sale_starts: "2026-08-20",
    sale_ends: saleEnds,
    ...overrides,
  });

describe("CampaignExpiring", () => {
  it("says the whole thing in one line: carrier, route, discount, days left", () => {
    render(
      <CampaignExpiring rows={[closing("a", "2026-09-05")]} today={TODAY} onSelect={vi.fn()} />,
    );

    expect(screen.getByText("TK")).toBeInTheDocument();
    expect(screen.getByText("IST-LHR")).toBeInTheDocument();
    expect(screen.getByText("%20")).toBeInTheDocument();
    expect(screen.getByText("2 gün kaldı")).toBeInTheDocument();
  });

  it("words the last day rather than counting to zero", () => {
    render(
      <CampaignExpiring rows={[closing("a", "2026-09-03")]} today={TODAY} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("Bugün son gün")).toBeInTheDocument();
  });

  it("disappears entirely when nothing is closing", () => {
    // An urgency band that is empty most days trains a reader to stop looking
    // at it.
    const { container } = render(
      <CampaignExpiring rows={[]} today={TODAY} onSelect={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names a campaign with no stated route rather than leaving the cell blank", () => {
    render(
      <CampaignExpiring
        rows={[closing("a", "2026-09-06", { ond: null, route_scope: null })]}
        today={TODAY}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("Rota belirtilmedi")).toBeInTheDocument();
  });

  it("caps the band and says how many it is not showing", () => {
    const rows = Array.from({ length: 9 }, (_, i) => closing(`c${i}`, "2026-09-07"));
    render(<CampaignExpiring rows={rows} today={TODAY} onSelect={vi.fn()} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByText(/3 kampanya daha bu hafta kapanıyor/)).toBeInTheDocument();
    // The heading still states the true total.
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("opens the drawer for the row that was clicked", async () => {
    const onSelect = vi.fn();
    render(
      <CampaignExpiring
        rows={[closing("a", "2026-09-05"), closing("b", "2026-09-06")]}
        today={TODAY}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByText("Kampanya b"));
    expect(onSelect.mock.calls[0][0].id).toBe("b");
  });
});
