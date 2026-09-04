import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalOut, SignalStreamOut } from "@/lib/types";

import { CompetitivePulse, PULSE_STREAMS } from "./competitive-pulse";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const signal = (overrides: Partial<SignalOut> = {}): SignalOut =>
  ({
    id: "m1",
    stream: "momentum",
    kind: "competitor",
    kind_label_tr: "Rakip",
    type_label_tr: "Haber momentumu",
    severity: "low",
    severity_label_tr: "Düşük",
    severity_basis_tr: "Bu akışta şiddet verisi yok.",
    title_tr: "Lufthansa haber hacmi +3 (4→7)",
    detail_tr: null,
    region: null,
    airline_codes: ["LH"],
    detected_at: null,
    confidence_score: null,
    source_label: "AeroIntel haber akışı",
    href: "/sinyaller?kind=competitor",
    ...overrides,
  }) as SignalOut;

const routeSignal = (overrides: Partial<SignalOut> = {}): SignalOut =>
  signal({
    id: "n1",
    stream: "network",
    kind: "market",
    kind_label_tr: "Piyasa & Ağ",
    type_label_tr: "Yeni hat",
    title_tr: "QR DOH–MXP hattını açıyor",
    region: "europe",
    airline_codes: ["QR"],
    href: "/hublar?view=network-signals",
    ...overrides,
  });

const stream = (key: string, count: number, total: number | null): SignalStreamOut => ({
  key,
  label_tr: key,
  kind: key === "network" ? "market" : "competitor",
  count,
  total,
  available: count > 0,
  empty_message: count > 0 ? null : "Bu akışta sinyal yok.",
});

/** Only ONE source is still fetched by this component: the 48-hour promotion
 * count. The momentum and route cells arrive as props, out of the page's one
 * server-side read of `/signals`. */
function serveCount(count?: unknown) {
  apiFetch.mockImplementation((path?: string) => {
    if (path?.startsWith("/promotions/new-count")) {
      return count instanceof Error
        ? Promise.reject(count)
        : Promise.resolve(count ?? { window_hours: 48, count: 0, airline_codes: [] });
    }
    // Rejected, never thrown: a synchronous throw out of the fetcher escapes
    // useDataSource's own .catch and surfaces as a React render error.
    return Promise.reject(new Error(`unexpected path ${String(path)}`));
  });
}

function draw(signals: SignalOut[] = [], streams: SignalStreamOut[] = []) {
  return render(<CompetitivePulse signals={signals} streams={streams} />);
}

describe("CompetitivePulse", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    serveCount();
  });

  it("fetches nothing but the promotion count", async () => {
    // THE MEASURED CHANGE. This row used to open `/insights` and
    // `/hubs/network-signals` of its own -- two more reads of streams the page
    // had already fetched, with their own caps and their own ordering.
    draw([signal(), routeSignal()], [stream("network", 1, 4)]);

    expect(await screen.findByText("0")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch.mock.calls[0][0]).toBe("/promotions/new-count");
  });

  it("does not print a zero when the promotion count failed", async () => {
    // The regression: the cell branched on `loaded` alone, and `useDataSource`
    // sets `loaded` on a FAILED request too. A 500 therefore rendered a
    // confident "0" -- a claim about the world produced by knowing nothing.
    serveCount(new Error("API request failed: 500"));
    draw();

    expect(await screen.findByText("Kaynak okunamadı.")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Yeniden dene/ })).toBeInTheDocument();
  });

  it("still prints a measured zero, because a measured zero is information", async () => {
    serveCount({ window_hours: 48, count: 0, airline_codes: [] });
    draw();

    const zero = await screen.findByText("0");
    // ONCE, and quietly. It used to be a 20px/600 figure -- the same weight as
    // the KPI strip's real numbers -- followed by a sentence saying the same
    // thing in words.
    expect(zero.className).toContain("text-muted-foreground");
    expect(zero.className).not.toContain("text-xl");
    expect(screen.queryByText(/Son 48 saatte yeni kampanya yok/)).not.toBeInTheDocument();
  });

  it("draws the movers the feed published, in the feed's own words", () => {
    draw([
      signal({ id: "a", title_tr: "Lufthansa haber hacmi +3 (4→7)" }),
      signal({ id: "b", title_tr: "Emirates haber hacmi -2 (9→7)", airline_codes: ["EK"] }),
    ]);

    expect(screen.getByText("Lufthansa haber hacmi +3 (4→7)")).toBeInTheDocument();
    expect(screen.getByText("Emirates haber hacmi -2 (9→7)")).toBeInTheDocument();
  });

  it("never ranks TK as its own rival", () => {
    // The home carrier is filtered in the backend, where the reason lives
    // (RIVAL_CODES): `/insights` counts mentions across the whole feed, and in
    // a Turkish-language feed the most-mentioned carrier is always TK. This
    // cell no longer holds a second copy of that filter -- so the assertion is
    // that a feed without TK draws without TK, and nothing here can put it
    // back.
    draw([signal({ id: "a", airline_codes: ["LH"], title_tr: "Lufthansa haber hacmi +3 (4→7)" })]);

    expect(screen.getByText(/Lufthansa/)).toBeInTheDocument();
    expect(screen.queryByText(/Turkish Airlines/)).not.toBeInTheDocument();
  });

  it("says the stream produced nothing, and does not guess why", () => {
    // It used to separate "no measurement", "no rival in the feed" and "rivals
    // measured, none moved" by reading `/insights`' raw list. The signal feed
    // publishes the stream's OUTPUT, not its input, so the three collapse into
    // one -- and the cell says only what it can still see rather than picking
    // whichever of the three sounds right.
    draw([], [stream("momentum", 0, null)]);

    expect(
      screen.getByText("Bu hafta rakip haber momentumu sinyali yok."),
    ).toBeInTheDocument();
  });

  it("prints the stream's worldwide total, not the rows that fit", () => {
    // `count` is what survived the list's display cap; `total` is what the
    // route stream actually measured over the window. Printing the first would
    // have quietly turned "31 sinyal" into "8".
    draw([routeSignal()], [stream("network", 8, 31)]);

    const total = screen.getByText("31").parentElement!;
    expect(total.textContent).toContain("tüm bölgeler");
    // The count is WORLDWIDE and the region belongs to the headline under it.
    // "14 · Avrupa" on one line reads as "fourteen signals in Europe", which
    // it never was.
    expect(total.textContent).not.toContain("Avrupa");
    expect(screen.getByText(/QR DOH–MXP/).textContent).toContain("Avrupa");
  });

  it("omits the total rather than inventing one when the stream has none", () => {
    // `total: null` means "this stream publishes no figure beyond its rows".
    // It is not zero, and it must not be rendered as one.
    draw([routeSignal()], [stream("network", 1, null)]);

    expect(screen.queryByText(/tüm bölgeler/)).not.toBeInTheDocument();
    expect(screen.getByText(/QR DOH–MXP/)).toBeInTheDocument();
  });

  it("says nothing about routes when the stream produced none", () => {
    draw([], [stream("network", 0, 0)]);

    expect(screen.getByText("Yeni rota sinyali yok.")).toBeInTheDocument();
    expect(screen.queryByText(/tüm bölgeler/)).not.toBeInTheDocument();
  });

  /* --- H4: the two drill-downs that pointed at pages without the data ----- */

  it("sends the momentum cell where movers are actually listed", () => {
    // It pointed at /biz, which is the THY desk and has drawn no rival
    // momentum since the signals block moved out of it.
    draw([signal()], []);

    const links = screen.getAllByRole("link");
    expect(links.some((a) => a.getAttribute("href") === "/sinyaller?kind=competitor")).toBe(
      true,
    );
    expect(links.some((a) => a.getAttribute("href") === "/biz")).toBe(false);
  });

  it("sends the route cell to the tab that draws route signals", () => {
    // It pointed at bare /hublar, which lands on the hub map -- no route
    // announcements on it at all. The deep link is the backend's own href.
    draw([routeSignal()], [stream("network", 1, 4)]);

    const links = screen.getAllByRole("link");
    expect(
      links.some((a) => a.getAttribute("href") === "/hublar?view=network-signals"),
    ).toBe(true);
    expect(links.some((a) => a.getAttribute("href") === "/hublar")).toBe(false);
  });

  it("uses the row's own href, so the cell cannot drift from the backend", () => {
    draw(
      [routeSignal({ href: "/hublar?view=network-signals&region=asia" })],
      [stream("network", 1, 4)],
    );

    expect(screen.getByText(/QR DOH–MXP/).closest("a")).toHaveAttribute(
      "href",
      "/hublar?view=network-signals&region=asia",
    );
  });
});

describe("CompetitivePulse: akış okunamadığında", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    serveCount({ window_hours: 48, count: 2, airline_codes: ["EK"] });
  });

  it("says the two feed cells went dark rather than reporting a stillness", async () => {
    // An empty feed is a measurement ("no rival moved this week"); an unread
    // one is not. They arrive here as the same empty array, which is exactly
    // why `unavailable` is a separate flag and not inferred from `length`.
    render(<CompetitivePulse signals={[]} streams={[]} unavailable />);

    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("Kaynak okunamadı.")).toHaveLength(2);
    expect(
      screen.queryByText("Bu hafta rakip haber momentumu sinyali yok."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Yeni rota sinyali yok.")).not.toBeInTheDocument();
  });

  it("leaves the campaign cell alone -- it has its own source", async () => {
    render(<CompetitivePulse signals={[]} streams={[]} unavailable />);

    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(screen.getByText("son 48 saat")).toBeInTheDocument();
  });

  it("offers no second retry button: the page above owns that request", async () => {
    render(<CompetitivePulse signals={[]} streams={[]} unavailable />);

    await screen.findByText("2");
    // The campaign count succeeded here, so nothing on this row should be
    // asking again -- three buttons for one server render is noise.
    expect(screen.queryByRole("button", { name: /Yeniden dene/ })).not.toBeInTheDocument();
  });
});

describe("CompetitivePulse: PULSE_STREAMS ile çizilen hücreler", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    serveCount();
  });

  // signal-routing.test.ts only checks that the three Kokpit sets PARTITION
  // the backend's seven streams. It cannot see whether a set's members are
  // actually drawn, and for this row they were not: the set said
  // {momentum, network} while the cells filtered by two separate literals.
  // Adding a stream to the set alone would have passed that test with this
  // row rendering nothing -- the silent drop it was written to prevent. These
  // two tests close that gap from the rendering side.

  it.each([...PULSE_STREAMS])("draws the %s stream it claims", async (key) => {
    const { container } = draw(
      [signal({ id: `${key}-1`, stream: key, title_tr: `${key} satırı` })],
      [stream(key, 1, null)],
    );

    // Read off the rendered row rather than a single text node: the route cell
    // prefixes its headline with the region, so the title is not an element's
    // whole text. What is being pinned is that the row reached the DOM at all.
    await screen.findByText("son 48 saat");
    expect(container.textContent).toContain(`${key} satırı`);
  });

  it("draws nothing for a stream PULSE_STREAMS does not name", async () => {
    // The negative half: this row is one of three windows onto one list, and
    // a cell that quietly picked up another section's rows would print the
    // same signal twice on one page.
    draw(
      [signal({ id: "risk-1", stream: "risk", title_tr: "Risk satırı" })],
      [stream("risk", 1, null)],
    );

    await screen.findByText("son 48 saat");
    expect(screen.queryByText("Risk satırı")).not.toBeInTheDocument();
    expect(
      screen.getByText("Bu hafta rakip haber momentumu sinyali yok."),
    ).toBeInTheDocument();
    expect(screen.getByText("Yeni rota sinyali yok.")).toBeInTheDocument();
  });
});
