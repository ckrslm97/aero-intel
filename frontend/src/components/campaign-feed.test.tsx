import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";

import { CampaignFeed, CampaignUndatedSection } from "./campaign-feed";

const never = () => false;

const dated = (overrides: Parameters<typeof promotion>[0] = {}) =>
  promotion({
    id: "dated",
    airline_code: "TK",
    airline_name: "Turkish Airlines",
    title_tr: "Avrupa'da %30 indirim",
    status: "ACTIVE_BOOKING",
    discount_pct: 30,
    ond: "IST-LHR",
    sale_starts: "2026-09-01",
    sale_ends: "2026-09-15",
    sale_range_tr: "01 Eyl – 15 Eyl",
    travel_starts: "2026-10-01",
    travel_ends: "2026-12-31",
    travel_range_tr: "01 Eki – 31 Ara",
    ...overrides,
  });

describe("CampaignFeed", () => {
  it("puts the essentials of a campaign in one row", () => {
    render(<CampaignFeed rows={[dated()]} isNew={never} onSelect={vi.fn()} />);

    expect(screen.getByText("Avrupa'da %30 indirim")).toBeInTheDocument();
    expect(screen.getByText("TK")).toBeInTheDocument();
    expect(screen.getByText("IST-LHR")).toBeInTheDocument();
    expect(screen.getByText("%30")).toBeInTheDocument();
    expect(screen.getByText("Satışta")).toBeInTheDocument();
    // Both windows, separately labelled -- the page's central distinction.
    expect(screen.getByText("Satış")).toBeInTheDocument();
    expect(screen.getByText("Seyahat")).toBeInTheDocument();
    expect(screen.getByText("01 Eyl – 15 Eyl")).toBeInTheDocument();
    expect(screen.getByText("01 Eki – 31 Ara")).toBeInTheDocument();
  });

  it("opens the drawer for the row that was clicked", async () => {
    const onSelect = vi.fn();
    const rows = [dated(), dated({ id: "second", title_tr: "Uzak Doğu fırsatı" })];
    render(<CampaignFeed rows={rows} isNew={never} onSelect={onSelect} />);

    await userEvent.click(screen.getByText("Uzak Doğu fırsatı"));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe("second");
  });

  it("marks a freshly seen campaign once, and only that one", () => {
    const rows = [dated(), dated({ id: "old", title_tr: "Eski kayıt" })];
    render(
      <CampaignFeed
        rows={rows}
        isNew={(promo) => promo.id === "dated"}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getAllByText("Yeni")).toHaveLength(1);
  });

  it("marks an officially sourced campaign and leaves the rest unmarked", () => {
    // Only the positive case in the feed: a "no official source" mark on two
    // rows out of three is noise, not information.
    const rows = [
      dated({ official_source_verified: true }),
      dated({ id: "second", title_tr: "İkincil kaynak", official_source_verified: false }),
    ];
    render(<CampaignFeed rows={rows} isNew={never} onSelect={vi.fn()} />);
    expect(screen.getAllByLabelText("Resmî kaynak doğrulandı")).toHaveLength(1);
  });
});

describe("CampaignUndatedSection", () => {
  const undated = (id: string, title: string) =>
    promotion({ id, title_tr: title, status: "UNKNOWN" });

  const rows = [undated("u1", "Tarihsiz kampanya bir"), undated("u2", "Tarihsiz kampanya iki")];

  it("names itself and its count, and opens closed", async () => {
    // The owner's call: nothing is dropped, but the analyst's eye reaches the
    // verified window first.
    render(<CampaignUndatedSection rows={rows} isNew={never} onSelect={vi.fn()} />);

    const toggle = screen.getByRole("button", { name: /Tarih belirtilmemiş/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("Tarihsiz kampanya bir")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Tarihsiz kampanya bir")).toBeInTheDocument();
    expect(screen.getByText("Tarihsiz kampanya iki")).toBeInTheDocument();
  });

  it("is its own labelled section, not part of the feed", () => {
    render(<CampaignUndatedSection rows={rows} isNew={never} onSelect={vi.fn()} />);
    expect(screen.getByLabelText("Tarih belirtilmemiş kampanyalar")).toBeInTheDocument();
  });

  it("draws no window bars, because there are no windows", async () => {
    const { container } = render(
      <CampaignUndatedSection rows={rows} isNew={never} onSelect={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Tarih belirtilmemiş/ }));
    expect(container.querySelectorAll("[data-track]")).toHaveLength(0);
  });

  it("still opens the drawer for a row inside it", async () => {
    const onSelect = vi.fn();
    render(<CampaignUndatedSection rows={rows} isNew={never} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: /Tarih belirtilmemiş/ }));
    await userEvent.click(screen.getByText("Tarihsiz kampanya iki"));
    expect(onSelect.mock.calls[0][0].id).toBe("u2");
  });

  it("renders nothing at all when every campaign is dated", () => {
    const { container } = render(
      <CampaignUndatedSection rows={[]} isNew={never} onSelect={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
