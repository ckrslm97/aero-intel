import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { riskItem } from "@/lib/__fixtures__/risk";

import { RiskDetailDrawer } from "./risk-detail-drawer";

const item = riskItem({
  id: "etna",
  headline: "Etna patlaması Catania Havalimanı'nı kapattı",
  risk_type: "volcano",
  risk_type_label_tr: "Volkanik",
  severity: "high",
  country: "Italy",
  city: "Catania",
  summary_tr: "Kül bulutu nedeniyle 700 uçuş iptal edildi.",
  confidence_score: 0.81,
  corroborating_source_count: 3,
  source_count: 3,
  first_reported_at: "2026-08-26T06:00:00Z",
  last_reported_at: "2026-08-29T18:00:00Z",
  is_updated: true,
  aviation_link: "direct",
  airports: [{ code: "CTA", name: "Catania Fontanarossa" }],
  members: [
    {
      title: "Etna patlaması Catania Havalimanı'nı kapattı",
      url: "https://aviation24.be/etna",
      source_name: "Aviation24",
      source_tier: "trade",
      published_at: "2026-08-26T06:00:00Z",
    },
    {
      title: "Sicilya genelinde 700 uçuş iptal edildi",
      url: "https://aerotime.aero/etna",
      source_name: "AeroTime",
      source_tier: "agency",
      published_at: "2026-08-29T18:00:00Z",
    },
  ],
});

describe("RiskDetailDrawer", () => {
  it("renders nothing at all when no signal is selected", () => {
    render(<RiskDetailDrawer item={null} onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens with the signal's headline, badges and summary", () => {
    render(<RiskDetailDrawer item={item} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "Risk sinyali ayrıntısı" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Etna patlaması Catania Havalimanı'nı kapattı" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Volkanik")).toBeInTheDocument();
    expect(screen.getByText("Güncellendi")).toBeInTheDocument();
    expect(screen.getByText("Kül bulutu nedeniyle 700 uçuş iptal edildi.")).toBeInTheDocument();

    // Severity and confidence both read "Yüksek" -- they are different
    // statements ("this event is severe" vs "we are sure of this reading") and
    // the drawer keeps them in different places, so scope each one.
    const header = screen.getByRole("dialog").querySelector("header");
    expect(within(header as HTMLElement).getByText("Yüksek")).toBeInTheDocument();
    // The band never appears without its number: a band alone is an opinion.
    expect(screen.getByText("0.81")).toBeInTheDocument();
    expect(screen.getByText("3 bağımsız kaynak")).toBeInTheDocument();
  });

  it("labels the airport section as named, never as affected", () => {
    // The single most important wording rule on this page: the gazetteer found
    // the airport's name in the article, which is not a claim about impact.
    render(<RiskDetailDrawer item={item} onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Anılan havalimanları" })).toBeInTheDocument();
    expect(screen.getByText("CTA")).toBeInTheDocument();
    expect(screen.getByText(/Etkilendikleri anlamına\s+gelmez/)).toBeInTheDocument();
  });

  it("hides the airport section entirely when nothing was named", () => {
    render(<RiskDetailDrawer item={riskItem({ airports: [] })} onClose={vi.fn()} />);
    expect(screen.queryByRole("heading", { name: "Anılan havalimanları" })).not.toBeInTheDocument();
  });

  it("draws the members as a publication chronology and says that is what it is", () => {
    render(<RiskDetailDrawer item={item} onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: /Yayın kronolojisi/ })).toBeInTheDocument();
    // A vertical timeline over a disaster reads as the event's own chronology
    // unless it says otherwise -- and this data has no such thing.
    expect(
      screen.getByText(/olayın kendi zaman çizelgesi değildir/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sicilya genelinde 700 uçuş/ })).toHaveAttribute(
      "href",
      "https://aerotime.aero/etna",
    );
    // The tier badge, in the article vocabulary rather than the campaign one.
    expect(screen.getByText("Ajans")).toBeInTheDocument();
  });

  it("hangs the source-language original off a translated headline", async () => {
    // The Turkish is a machine's paraphrase. A paraphrase whose original is
    // nowhere on the page cannot be checked against anything, and the drawer
    // is precisely where a reader goes to check a signal.
    render(
      <RiskDetailDrawer
        item={riskItem({
          headline: "Rodos'ta orman yangını: tahliye sürüyor",
          headline_original: "Wildfires force evacuation of Rhodes",
          is_translated: true,
        })}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Rodos'ta orman yangını: tahliye sürüyor" }),
    ).toHaveAttribute("title", "Wildfires force evacuation of Rhodes");
    expect(screen.queryByText("otomatik çeviri yok")).not.toBeInTheDocument();
  });

  it("says an untranslated headline is untranslated rather than letting it pass", () => {
    render(
      <RiskDetailDrawer
        item={riskItem({
          headline: "Wildfires force evacuation of Rhodes",
          is_translated: false,
        })}
        onClose={vi.fn()}
      />,
    );

    // The app's existing wording, reused verbatim -- a reader who learned it on
    // the archive drawer must not have to learn a second phrase here.
    expect(screen.getByText("otomatik çeviri yok")).toBeInTheDocument();
    // ...and nothing to reveal on hover: the text shown IS the original.
    expect(
      screen.getByRole("heading", { name: "Wildfires force evacuation of Rhodes" }),
    ).not.toHaveAttribute("title");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<RiskDetailDrawer item={item} onClose={onClose} />);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from the close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<RiskDetailDrawer item={item} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Ayrıntıyı kapat" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("takes focus on open and hands it back to the opener on close", () => {
    // Without the hand-back, a keyboard reader who opened a card halfway down
    // the list is returned to the top of the document and has to find their
    // place again.
    const { rerender } = render(<RiskDetailDrawer item={null} onClose={vi.fn()} />);

    // Stands in for the card button that opened the drawer, focused the way a
    // click leaves it.
    const opener = document.createElement("button");
    opener.textContent = "Sinyali aç";
    document.body.appendChild(opener);
    opener.focus();
    expect(opener).toHaveFocus();

    rerender(<RiskDetailDrawer item={item} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Ayrıntıyı kapat" })).toHaveFocus();

    rerender(<RiskDetailDrawer item={null} onClose={vi.fn()} />);
    expect(opener).toHaveFocus();

    opener.remove();
  });
});
