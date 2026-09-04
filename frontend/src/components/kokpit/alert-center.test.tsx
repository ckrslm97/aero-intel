import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SignalOut } from "@/lib/types";

import { ALERT_STREAMS, AlertCenter } from "./alert-center";

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

const signal = (overrides: Partial<SignalOut> = {}): SignalOut =>
  ({
    id: "c1",
    stream: "campaign_alerts",
    kind: "competitor",
    kind_label_tr: "Rakip",
    type_label_tr: "Bitmek üzere",
    severity: "medium",
    severity_label_tr: "Orta",
    severity_basis_tr: "Kampanya uyarı önceliği.",
    title_tr: "TK Avrupa kampanyası bitiyor",
    detail_tr: null,
    region: null,
    airline_codes: [],
    detected_at: hoursAgo(3),
    confidence_score: null,
    source_label: "AeroIntel kampanya tespiti",
    href: "/kampanyalar",
    ...overrides,
  }) as SignalOut;

const riskSignal = (overrides: Partial<SignalOut> = {}): SignalOut =>
  signal({
    id: "r1",
    stream: "risk",
    kind: "risk",
    kind_label_tr: "Risk",
    type_label_tr: "Volkanik aktivite",
    severity: "high",
    severity_label_tr: "Yüksek",
    title_tr: "Etna'da kül bulutu uçuşları durdurdu",
    detected_at: hoursAgo(1),
    source_label: "Reuters",
    href: "/risk-radari",
    ...overrides,
  });

/** The section opens CLOSED, so every row assertion has to expand it first. */
async function expand() {
  const button = await screen.findByRole("button", { name: /Genişlet/ });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
}

describe("AlertCenter", () => {
  it("counts exactly the two alert streams and no others", () => {
    // Too wide and this band reprints the signal board two sections above it;
    // too narrow and an alert stream silently stops being counted.
    expect([...ALERT_STREAMS].sort()).toEqual(["campaign_alerts", "risk"]);
  });

  it("ignores the five streams that are drawn elsewhere on the page", async () => {
    render(
      <AlertCenter
        signals={[
          signal(),
          riskSignal(),
          signal({ id: "x1", stream: "rival_events", title_tr: "Rakip olayı" }),
          signal({ id: "x2", stream: "network", title_tr: "Yeni hat" }),
          signal({ id: "x3", stream: "kokpit", title_tr: "Kur riski" }),
        ]}
      />,
    );
    await expand();

    expect(screen.getByText("TK Avrupa kampanyası bitiyor")).toBeInTheDocument();
    expect(screen.getByText("Etna'da kül bulutu uçuşları durdurdu")).toBeInTheDocument();
    expect(screen.queryByText("Rakip olayı")).not.toBeInTheDocument();
    expect(screen.queryByText("Yeni hat")).not.toBeInTheDocument();
    expect(screen.queryByText("Kur riski")).not.toBeInTheDocument();
  });

  it("starts collapsed, showing counts rather than rows", () => {
    render(<AlertCenter signals={[signal(), riskSignal()]} />);

    expect(screen.getByText(/1 ORTA/)).toBeInTheDocument();
    expect(screen.getByText(/1 YÜKSEK/)).toBeInTheDocument();
    // The bottom of the page is not where a reader is scanning; the rows are
    // one click away, the counts are not.
    expect(screen.queryByText("TK Avrupa kampanyası bitiyor")).not.toBeInTheDocument();
  });

  /** THE REGRESSION THIS ROUND CLOSED.
   *
   * This band used to merge two of its own fetches and RE-SORT them under a
   * priority ladder written here, while /sinyaller sorted the same rows with
   * the backend's. One set of facts, two "most important" orders. The list
   * arrives sorted now and this component may not touch it. */
  it("never re-sorts: the rows keep the order the feed handed them", async () => {
    render(
      <AlertCenter
        signals={[
          riskSignal({ id: "a", severity: "critical", title_tr: "Bir" }),
          signal({ id: "b", severity: "high", title_tr: "İki" }),
          signal({ id: "c", severity: "low", title_tr: "Üç" }),
        ]}
      />,
    );
    await expand();

    const titles = screen.getAllByText(/^(Bir|İki|Üç)$/).map((node) => node.textContent);
    expect(titles).toEqual(["Bir", "İki", "Üç"]);
  });

  it("does not reorder even when the feed's order looks wrong to it", async () => {
    // The negative half. A component that quietly "fixed" this would be the
    // second opinion the whole change exists to remove -- if the backend ever
    // ships a bad order, that is a backend bug, visible here rather than
    // papered over.
    render(
      <AlertCenter
        signals={[
          signal({ id: "a", severity: "low", title_tr: "Düşük" }),
          signal({ id: "b", severity: "critical", title_tr: "Kritik" }),
        ]}
      />,
    );
    await expand();

    const titles = screen.getAllByText(/^(Düşük|Kritik)$/).map((node) => node.textContent);
    expect(titles).toEqual(["Düşük", "Kritik"]);
  });

  it("caps the open list at three rows but counts them all", async () => {
    render(
      <AlertCenter
        signals={Array.from({ length: 5 }, (_, i) =>
          signal({ id: `c${i}`, title_tr: `Uyarı ${i}` }),
        )}
      />,
    );
    await expand();

    expect(screen.getByText("Uyarı 0")).toBeInTheDocument();
    expect(screen.queryByText("Uyarı 3")).not.toBeInTheDocument();
    // ...the BAND still counts all five. A count computed over the three
    // visible rows would be a number nobody could reconcile with /sinyaller.
    expect(screen.getByText(/5 ORTA/)).toBeInTheDocument();
  });

  it("prints its zeroes rather than hiding the section", () => {
    // A silent section says nothing; "0 KRİTİK" says the feed answered and had
    // nothing to report, which is a different and useful statement. The page
    // only renders this section when the feed WAS read -- an unread feed gets
    // the failure line instead, so these zeroes can never stand in for one.
    render(<AlertCenter signals={[]} />);

    expect(screen.getByText(/0 KRİTİK/)).toBeInTheDocument();
    expect(screen.getByText(/0 YÜKSEK/)).toBeInTheDocument();
    expect(screen.getByText(/0 ORTA/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Genişlet/ })).toBeDisabled();
  });

  it("takes each row's drill-down from the row, not from a table of its own", async () => {
    render(<AlertCenter signals={[riskSignal(), signal()]} />);
    await expand();

    expect(
      screen.getByRole("link", { name: /Etna'da kül bulutu/ }),
    ).toHaveAttribute("href", "/risk-radari");
    expect(
      screen.getByRole("link", { name: /TK Avrupa kampanyası/ }),
    ).toHaveAttribute("href", "/kampanyalar");
  });

  it("renders a row with no drill-down as text rather than a dead link", async () => {
    render(<AlertCenter signals={[signal({ href: null, title_tr: "Hedefsiz" })]} />);
    await expand();

    expect(screen.getByText("Hedefsiz")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Hedefsiz/ })).not.toBeInTheDocument();
  });

  it("offers the full list first", () => {
    render(<AlertCenter signals={[signal()]} />);

    expect(screen.getByRole("link", { name: /Sinyaller/ })).toHaveAttribute(
      "href",
      "/sinyaller",
    );
  });
});

describe("AlertCenter: risk taraması tavana çarptığında", () => {
  // /risks caps how many articles one rollup clusters (RISK_SCAN_CAP). Kokpit
  // never calls /risks -- it counts risk rows out of the /signals envelope --
  // so the flag rides along on that response. Without these two tests the cap
  // would be published with no reader, which is the same thing as capping
  // silently.

  it("says the counts are a floor, and names how many articles were read", async () => {
    render(
      <AlertCenter
        signals={[riskSignal(), signal()]}
        riskTruncated
        riskScannedArticles={400}
      />,
    );

    const note = await screen.findByText(/Risk taraması/);
    expect(note).toHaveTextContent("en yeni 400 haberinde durdu");
    expect(note).toHaveTextContent("hepsi bu kadar değil");
  });

  it("drops the figure rather than inventing one when the count is missing", async () => {
    render(<AlertCenter signals={[riskSignal()]} riskTruncated riskScannedArticles={null} />);

    const note = await screen.findByText(/Risk taraması/);
    expect(note).toHaveTextContent("pencerenin tamamına ulaşamadı");
    expect(note).not.toHaveTextContent("0 haber");
  });

  it("stays quiet when the rollup read its whole window", () => {
    // The negative half: an always-on warning is furniture, and the band's
    // counts really are complete on an ordinary day.
    render(<AlertCenter signals={[riskSignal(), signal()]} />);

    expect(screen.queryByText(/Risk taraması/)).not.toBeInTheDocument();
  });
});
