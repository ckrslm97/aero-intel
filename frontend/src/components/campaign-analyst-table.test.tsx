import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";

import { CampaignAnalystTable, CampaignStatusPill, ConfidencePill } from "./campaign-analyst-table";

describe("CampaignStatusPill", () => {
  it("states the status in words, not in colour alone", () => {
    render(<CampaignStatusPill status="ACTIVE_BOOKING" />);
    expect(screen.getByText("Satışta")).toBeInTheDocument();
    expect(screen.getByTitle("Satışta")).toBeInTheDocument();
  });

  it("spells out the long status with its full label on hover", () => {
    render(<CampaignStatusPill status="BOOKING_CLOSED_TRAVEL_ACTIVE" />);
    expect(screen.getByText("Seyahat sürüyor")).toBeInTheDocument();
    expect(screen.getByTitle("Satış kapandı, seyahat sürüyor")).toBeInTheDocument();
  });

  it("degrades an unknown status to Tarihsiz rather than rendering a slug", () => {
    // v2 renamed the UNKNOWN word from "Belirsiz" to "Tarihsiz" so the pill
    // and the page's "Tarih belirtilmemiş" group say the same thing: the
    // uncertainty is about the DATES, not about whether the campaign is real.
    render(<CampaignStatusPill status="A_STATUS_FROM_THE_FUTURE" />);
    expect(screen.getByText("Tarihsiz")).toBeInTheDocument();
  });

  it("never renders an expired campaign as an alarm", () => {
    // EXPIRED does not reach this page in v2, but the word still has to exist:
    // a row whose dates move under us must render a word, not a blank badge.
    render(<CampaignStatusPill status="EXPIRED" />);
    expect(screen.getByText("Sona erdi")).toBeInTheDocument();
  });
});

describe("ConfidencePill", () => {
  it("shows the band and the number behind it", () => {
    render(<ConfidencePill band="high" score={0.912} />);
    expect(screen.getByText("Yüksek")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
  });

  it("says a legacy row was never assessed instead of scoring it", () => {
    render(<ConfidencePill band={null} score={null} />);
    expect(screen.getByText("Değerlendirilmedi")).toBeInTheDocument();
  });
});

describe("CampaignAnalystTable", () => {
  const row = promotion({
    id: "row-1",
    airline_code: "TK",
    title_tr: "Avrupa'ya %40 indirim",
    campaign_type: "FLASH_SALE",
    status: "ACTIVE_BOOKING",
    ond: "IST-CDG",
    sale_range_tr: "1 - 30 Eylül 2026",
    travel_range_tr: "1 Ekim - 31 Aralık 2026",
    discount_pct: 40,
    confidence_band: "high",
    confidence_score: 0.88,
    source_count: 3,
  });

  it("renders one row with every column filled from the campaign", () => {
    render(<CampaignAnalystTable rows={[row]} onSelect={() => {}} />);

    expect(screen.getByRole("columnheader", { name: "Kampanya" })).toBeInTheDocument();
    expect(screen.getByText("Avrupa'ya %40 indirim")).toBeInTheDocument();
    expect(screen.getByText("Flaş İndirim")).toBeInTheDocument();
    expect(screen.getByText("IST-CDG")).toBeInTheDocument();
    expect(screen.getByText("1 - 30 Eylül 2026")).toBeInTheDocument();
    expect(screen.getByText("%40")).toBeInTheDocument();
    expect(screen.getByText("Satışta")).toBeInTheDocument();
    // Three pages agreeing is the corroboration count, and it is worth saying.
    expect(screen.getByText("×3")).toBeInTheDocument();
  });

  it("says an unclassified legacy row is unclassified rather than leaving a blank", () => {
    render(<CampaignAnalystTable rows={[promotion({ discount_pct: null })]} onSelect={() => {}} />);
    expect(screen.getByText("Sınıflandırılmadı")).toBeInTheDocument();
    // An empty cell on a table reads as a rendering bug, not as a missing
    // fact: both the unstated discount and the unknown route say so in a glyph.
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("keeps the sale and travel windows in two separate columns", () => {
    // §11 again, in the densest view on the site: the two windows never share
    // a column and never merge into one range.
    render(<CampaignAnalystTable rows={[row]} onSelect={() => {}} />);
    expect(screen.getByRole("columnheader", { name: "Satış dönemi" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Seyahat dönemi" })).toBeInTheDocument();
    expect(screen.getByText("1 - 30 Eylül 2026")).toBeInTheDocument();
    expect(screen.getByText("1 Ekim - 31 Aralık 2026")).toBeInTheDocument();
  });

  it("marks a campaign the carrier itself is on the record for", () => {
    render(
      <CampaignAnalystTable
        rows={[promotion({ official_source_verified: true })]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByLabelText("Resmî kaynak doğrulandı")).toBeInTheDocument();
  });

  it("flags the two things an analyst must not miss", () => {
    render(
      <CampaignAnalystTable
        rows={[promotion({ review_required: true, conflict_detected: true })]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("İnceleme")).toBeInTheDocument();
    expect(screen.getByText("Çelişki")).toBeInTheDocument();
  });

  it("opens the campaign from the keyboard-reachable control", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<CampaignAnalystTable rows={[row]} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Avrupa'ya %40 indirim" }));
    expect(onSelect).toHaveBeenCalledWith(row);
  });

  it("keeps the source link out of the row's click target", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<CampaignAnalystTable rows={[row]} onSelect={onSelect} />);

    await user.click(screen.getByRole("link"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});
