import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import type { PromotionOut } from "@/lib/types";

import { CampaignsClient } from "./campaigns-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const replace = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/kampanyalar",
  useSearchParams: () => searchParams.current,
}));

/** What each endpoint answers for one test. */
interface Feed {
  promotions: PromotionOut[];
  expiring?: PromotionOut[];
  newCount?: { window_hours: number; count: number; airline_codes: string[] } | null;
}

function serve({ promotions, expiring = [], newCount = null }: Feed) {
  apiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/promotions/expiring")) return Promise.resolve(expiring);
    if (path.startsWith("/promotions/new-count")) {
      return newCount ? Promise.resolve(newCount) : Promise.reject(new Error("404"));
    }
    if (path.startsWith("/campaign-alerts")) return Promise.reject(new Error("404"));
    if (path.startsWith("/promotions")) return Promise.resolve(promotions);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

const active = (overrides: Parameters<typeof promotion>[0] = {}) =>
  promotion({
    id: "active",
    airline_code: "TK",
    title_tr: "Avrupa fırsat haftası",
    status: "ACTIVE_BOOKING",
    sale_starts: "2026-09-01",
    sale_ends: "2026-09-30",
    sale_range_tr: "01 Eyl – 30 Eyl",
    ...overrides,
  });

const undated = (overrides: Parameters<typeof promotion>[0] = {}) =>
  promotion({ id: "undated", title_tr: "Tarihsiz tespit", status: "UNKNOWN", ...overrides });

/** An expired campaign is a contract violation from the API in v2 -- the
 * point of the tests that use it is that the page does not render one even
 * when handed one. */
const expired = (overrides: Parameters<typeof promotion>[0] = {}) =>
  promotion({
    id: "expired",
    title_tr: "SÜRESİ DOLMUŞ KAMPANYA",
    status: "EXPIRED",
    sale_starts: "2026-01-01",
    sale_ends: "2026-02-01",
    sale_range_tr: "01 Oca – 01 Şub",
    ...overrides,
  });

async function renderPage(feed: Feed, query = "") {
  searchParams.current = new URLSearchParams(query);
  serve(feed);
  const view = render(<CampaignsClient />);
  await screen.findByRole("heading", { name: "Kampanya Takibi" });
  await waitFor(() => expect(apiFetch).toHaveBeenCalled());
  return view;
}

describe("CampaignsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    replace.mockReset();
    searchParams.current = new URLSearchParams();
  });

  it("asks for the publishable set and never for expired rows", async () => {
    await renderPage({ promotions: [active()] });

    const paths = apiFetch.mock.calls.map((call) => call[0] as string);
    expect(paths).toContain("/promotions");
    expect(paths.some((path) => path.includes("include_expired"))).toBe(false);
    // The urgency band has its own endpoint, because the "still on sale" half
    // of the rule cannot be reconstructed from a date comparison.
    expect(paths.some((path) => path.startsWith("/promotions/expiring?days=7"))).toBe(true);
  });

  it("renders no expired campaign in the feed, the undated group or the table", async () => {
    // The v2 regression guard. The API hides these; if one ever slips through,
    // it must not reach a reader wearing a status badge.
    await renderPage({ promotions: [active(), expired()] });

    await screen.findByText("Avrupa fırsat haftası");
    expect(screen.queryByText("SÜRESİ DOLMUŞ KAMPANYA")).not.toBeInTheDocument();
    expect(screen.queryByText("Sona erdi")).not.toBeInTheDocument();

    // ...and it is not hiding behind the undated group either: an EXPIRED row
    // is not UNKNOWN, so the collapsed section must not have absorbed it.
    expect(
      screen.queryByRole("button", { name: /Tarih belirtilmemiş/ }),
    ).not.toBeInTheDocument();
  });

  it("offers no way to ask for expired campaigns", async () => {
    await renderPage({ promotions: [active(), expired()] });
    await userEvent.click(screen.getByRole("button", { name: /Daha fazla filtre/ }));

    expect(screen.queryByRole("button", { name: /Sona erdi/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/arşiv/i)).not.toBeInTheDocument();
  });

  it("keeps undated campaigns out of the main feed and behind a closed group", async () => {
    await renderPage({ promotions: [active(), undated()] });

    const feed = await screen.findByLabelText("Son kampanyalar");
    expect(within(feed).getByText("Avrupa fırsat haftası")).toBeInTheDocument();
    expect(within(feed).queryByText("Tarihsiz tespit")).not.toBeInTheDocument();

    const group = screen.getByLabelText("Tarih belirtilmemiş kampanyalar");
    const toggle = within(group).getByRole("button", { name: /Tarih belirtilmemiş/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Tarihsiz tespit")).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(within(group).getByText("Tarihsiz tespit")).toBeInTheDocument();
  });

  it("never shows a closed-sale campaign in the expiring band", async () => {
    // "Bitmek üzere" printed over a campaign that already stopped selling is
    // not a smaller error than showing an expired one -- it is the same error
    // with a countdown on it. The endpoint gates on ACTIVE_BOOKING; so does
    // the page, because a rule this costly should be false in two places.
    const stillSelling = active({
      id: "sell",
      title_tr: "Hâlâ satılıyor",
      sale_ends: "2026-09-30",
    });
    const bookingClosed = promotion({
      id: "closed",
      title_tr: "Satışı kapandı, seyahat sürüyor",
      status: "BOOKING_CLOSED_TRAVEL_ACTIVE",
      sale_starts: "2026-06-01",
      sale_ends: "2026-06-30",
      travel_starts: "2026-09-01",
      travel_ends: "2026-12-31",
    });

    await renderPage({
      promotions: [stillSelling, bookingClosed],
      expiring: [stillSelling, bookingClosed],
    });

    const band = await screen.findByLabelText("Bitmek üzere olan kampanyalar");
    expect(within(band).getByText("Hâlâ satılıyor")).toBeInTheDocument();
    expect(
      within(band).queryByText("Satışı kapandı, seyahat sürüyor"),
    ).not.toBeInTheDocument();
  });

  it("summarises what is on screen, not what the database holds", async () => {
    await renderPage({
      promotions: [
        active({ id: "a1" }),
        active({ id: "a2", title_tr: "İkinci fırsat" }),
        promotion({ id: "up", title_tr: "Yakında", status: "UPCOMING", sale_starts: "2026-12-01" }),
        undated(),
      ],
    });

    const summary = await screen.findByLabelText("Kampanya özeti");
    const value = (label: string) =>
      within(summary).getByText(label).parentElement?.textContent?.replace(label, "");
    expect(value("Satıştaki kampanya")).toBe("2");
    expect(value("Yakında")).toBe("1");
  });

  it("writes the filter into the URL so the view is a link", async () => {
    await renderPage({ promotions: [active({ airline_code: "TK" })] });

    // The carrier chip is identified by its title: the logo <img> never loads
    // in jsdom, so its alt text is not a stable handle.
    await userEvent.click(await screen.findByTitle("Turkish Airlines"));

    expect(replace).toHaveBeenCalledWith(
      "/kampanyalar?airline=TK",
      expect.objectContaining({ scroll: false }),
    );
  });

  it("reads its filters back out of the URL", async () => {
    await renderPage(
      { promotions: [active({ airline_code: "TK" }), active({ id: "pc", airline_code: "PC", title_tr: "Pegasus kampanyası" })] },
      "airline=PC",
    );

    expect(await screen.findByText("Pegasus kampanyası")).toBeInTheDocument();
    expect(screen.queryByText("Avrupa fırsat haftası")).not.toBeInTheDocument();
  });

  it("says a filter found nothing without sounding like a failure", async () => {
    await renderPage({ promotions: [active({ airline_code: "TK" })] }, "airline=EK");

    expect(await screen.findByText("Bu filtrelerle kampanya yok.")).toBeInTheDocument();
    expect(screen.getByText("Filtreleri gevşetin ya da temizleyin.")).toBeInTheDocument();
  });

  it("says an empty database is empty, not broken", async () => {
    await renderPage({ promotions: [] });
    expect(await screen.findByText("Kayıtlı kampanya yok.")).toBeInTheDocument();
  });

  it("keeps the analyst table one toggle away, with the same rows", async () => {
    await renderPage({ promotions: [active()] }, "view=table");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Avrupa fırsat haftası")).toBeInTheDocument();
    // The two date columns stay separate and adjacent in the table too.
    expect(within(table).getByText("Satış dönemi")).toBeInTheDocument();
    expect(within(table).getByText("Seyahat dönemi")).toBeInTheDocument();
  });

  it("orders the feed by what a desk can still act on", async () => {
    await renderPage({
      promotions: [
        promotion({ id: "closed", title_tr: "Seyahat sürüyor", status: "BOOKING_CLOSED_TRAVEL_ACTIVE", sale_ends: "2026-06-30" }),
        promotion({ id: "up", title_tr: "Yakında açılıyor", status: "UPCOMING", sale_starts: "2026-12-01" }),
        active({ id: "late", title_tr: "Geç kapanan", sale_ends: "2026-09-28" }),
        active({ id: "soon", title_tr: "Yakında kapanıyor", sale_ends: "2026-09-05" }),
      ],
    });

    const feed = await screen.findByLabelText("Son kampanyalar");
    const titles = within(feed)
      .getAllByRole("button")
      .map((node) => node.textContent ?? "");
    const order = ["Yakında kapanıyor", "Geç kapanan", "Yakında açılıyor", "Seyahat sürüyor"];
    const seen = order.map((title) => titles.findIndex((text) => text.includes(title)));
    expect(seen).toEqual([...seen].sort((a, b) => a - b));
    expect(seen.every((index) => index >= 0)).toBe(true);
  });

  it("refuses to print 'Bitmek üzere: 0' when that source did not answer", async () => {
    // THE MOST EXPENSIVE ZERO ON THE PAGE. `/promotions/expiring` is its own
    // request, and its failure used to be caught into `[]` -- so a revenue desk
    // was told nothing closes this week by the one counter whose entire job is
    // urgency, and the band under it disappeared to agree.
    const user = userEvent.setup();
    searchParams.current = new URLSearchParams();
    apiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/promotions/expiring")) {
        return Promise.reject(new Error("API request failed: 500"));
      }
      if (path.startsWith("/promotions/new-count")) return Promise.reject(new Error("404"));
      if (path.startsWith("/campaign-alerts")) return Promise.reject(new Error("404"));
      if (path.startsWith("/promotions")) return Promise.resolve([active()]);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<CampaignsClient />);

    const summary = await screen.findByLabelText("Kampanya özeti");
    await waitFor(() =>
      expect(within(summary).getByText("Bitmek üzere").parentElement).toHaveTextContent(
        "okunamadı",
      ),
    );
    expect(within(summary).getByText("Bitmek üzere").parentElement).not.toHaveTextContent(
      "Bitmek üzere0",
    );
    // ...and the band says so in the reader's own words, with a way to re-ask.
    expect(
      screen.getByText(/Bitmek üzere olan kampanyalar okunamadı/),
    ).toBeInTheDocument();

    apiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/promotions/expiring")) {
        return Promise.resolve([
          active({ id: "soon", title_tr: "Bu hafta kapanıyor", sale_ends: "2026-09-05" }),
        ]);
      }
      if (path.startsWith("/promotions/new-count")) return Promise.reject(new Error("404"));
      if (path.startsWith("/campaign-alerts")) return Promise.reject(new Error("404"));
      if (path.startsWith("/promotions")) return Promise.resolve([active()]);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));

    expect(
      await screen.findByLabelText("Bitmek üzere olan kampanyalar"),
    ).toBeInTheDocument();
  });

  it("still prints a real zero when nothing is actually closing", async () => {
    // The negative half: an answered `/promotions/expiring` with no rows is a
    // measurement, and the counter must keep saying "0" for it. Reading
    // "okunamadı" over a quiet week would be this round's own sin, mirrored.
    await renderPage({ promotions: [active()], expiring: [] });

    const summary = await screen.findByLabelText("Kampanya özeti");
    expect(within(summary).getByText("Bitmek üzere").parentElement).toHaveTextContent(
      "Bitmek üzere0",
    );
    expect(screen.queryByText(/kampanyalar okunamadı/)).not.toBeInTheDocument();
  });
});
