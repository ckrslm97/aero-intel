import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";
import type { HubDetailOut, HubOverviewOut } from "@/lib/types";

import { HubsClient } from "./hubs-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// The world map is a canvas-geometry surface checked in a browser, not here.
vi.mock("@/components/hub-map", () => ({
  HubMap: () => <div data-testid="hub-map" />,
}));
// The Ağ Sinyalleri tab has its own source and its own tests; this file is
// about which tab the URL selects, so it is stubbed to something nameable.
vi.mock("@/components/hub-network-signals", () => ({
  HubNetworkSignals: () => <div>Ağ sinyalleri paneli</div>,
}));

vi.mock("@/components/article-drawer-context", () => ({
  useArticleDrawer: () => ({ open: vi.fn() }),
}));

const hub = (code: string, article_count = 5) => ({
  code,
  name: `${code} Havalimanı`,
  city: code,
  country: "Türkiye",
  region: "europe",
  lat: 41,
  lon: 29,
  carriers: ["TK"],
  note_tr: "Not.",
  article_count,
});

const overview: HubOverviewOut = {
  generated_at: "2026-09-02T09:00:00Z",
  window: { days: 90, since: "2026-06-04T09:00:00Z", until: "2026-09-02T09:00:00Z" },
  days: 90,
  hubs: [hub("IST", 12), hub("DXB", 7)],
  routes: [],
};

const detail = (code: string, days: number): HubDetailOut => ({
  ...hub(code),
  days,
  categories: [{ slug: "revenue_management", count: 4 }],
  carriers_seen: [{ code: "TK", name: "Turkish Airlines", article_count: 3 }],
});

/** Every path the client asked for, in order. */
const requested: string[] = [];

function serve() {
  apiFetch.mockImplementation((path: string) => {
    requested.push(path);
    if (path.startsWith("/hubs/")) {
      const [, code] = path.match(/^\/hubs\/([A-Z]{3})/) ?? [];
      const days = Number(new URL(path, "http://test").searchParams.get("days"));
      if (!overview.hubs.some((entry) => entry.code === code)) {
        return Promise.reject(new Error("API request failed: 404"));
      }
      return Promise.resolve(detail(code!, days));
    }
    if (path.startsWith("/hubs")) return Promise.resolve(overview);
    if (path.startsWith("/taxonomy/countries")) {
      return Promise.resolve([{ name: "Türkiye", article_count: 9, region: "europe" }]);
    }
    if (path.startsWith("/articles")) return Promise.resolve({ total: 0, items: [] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

const articlePaths = () => requested.filter((path) => path.startsWith("/articles"));

describe("HubsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    requested.length = 0;
    resetNavigation("/hublar");
    serve();
  });

  it("opens on IST and the overview tab when the URL says nothing", async () => {
    render(<HubsClient />);

    expect(await screen.findByRole("heading", { name: "IST Havalimanı" })).toBeInTheDocument();
    expect(requested).toContain("/hubs?days=90");
    expect(requested).toContain("/hubs/IST?days=90");
    expect(screen.queryByText("Ağ sinyalleri paneli")).not.toBeInTheDocument();
  });

  it("restores the whole view from a deep link", async () => {
    // Five decisions in one address: which hub, which window, which country,
    // which beat. This is the link an analyst pastes into a message, and every
    // one of them has to survive the paste.
    setUrl("/hublar?hub=DXB&days=365&country=T%C3%BCrkiye&category=revenue_management");
    render(<HubsClient />);

    expect(await screen.findByRole("heading", { name: "DXB Havalimanı" })).toBeInTheDocument();
    expect(requested).toContain("/hubs?days=365");
    expect(requested).toContain("/hubs/DXB?days=365");
    await waitFor(() =>
      expect(articlePaths()).toContain(
        "/articles?limit=12&airport=DXB&country=T%C3%BCrkiye&category=revenue_management",
      ),
    );
    expect(screen.getByRole("button", { name: "Son 365 gün" })).toHaveClass(
      "text-primary",
    );
  });

  it("deep-links straight to the Ağ Sinyalleri tab", async () => {
    // The link İçgörüler now points at, since new routes are counted there
    // and nowhere else.
    setUrl("/hublar?view=network-signals");
    render(<HubsClient />);

    expect(await screen.findByText("Ağ sinyalleri paneli")).toBeInTheDocument();
    expect(screen.queryByTestId("hub-map")).not.toBeInTheDocument();
  });

  it("writes the tab, the window and the hub into the URL as they change", async () => {
    const user = userEvent.setup();
    render(<HubsClient />);
    await screen.findByRole("heading", { name: "IST Havalimanı" });

    // The default view carries no keys at all -- one URL for "untouched".
    expect(currentParams().toString()).toBe("");

    await user.click(screen.getByRole("button", { name: "Son 365 gün" }));
    await waitFor(() => expect(currentParams().get("days")).toBe("365"));

    await user.click(screen.getByRole("button", { name: /^DXB/ }));
    await waitFor(() => expect(currentParams().get("hub")).toBe("DXB"));

    await user.click(screen.getByRole("button", { name: "Ağ Sinyalleri" }));
    await waitFor(() => expect(currentParams().get("view")).toBe("network-signals"));
    // ...without losing the rest of the view, so switching tabs and switching
    // back is not a reset.
    expect(currentParams().get("days")).toBe("365");
    expect(currentParams().get("hub")).toBe("DXB");
  });

  it("says so out loud when a link names a hub we do not track", async () => {
    // Passed straight through, `?hub=XYZ` would 404 into "Haberler
    // yüklenemedi" -- the server blamed for a bad link.
    setUrl("/hublar?hub=XYZ");
    render(<HubsClient />);

    expect(
      await screen.findByText(/izlenen hub'lar arasında değil/),
    ).toBeInTheDocument();
    expect(requested.some((path) => path.startsWith("/hubs/XYZ"))).toBe(false);
    // ...and the story list is not labelled with a code it is not narrowed by.
    expect(screen.getByRole("heading", { name: "Haberler" })).toBeInTheDocument();
    await waitFor(() => expect(articlePaths()).toContain("/articles?limit=12"));
  });

  it("says so out loud for a malformed hub too, instead of quietly showing IST", async () => {
    // The two ways a link can be wrong used to be answered with opposite
    // honesty: `?hub=XYZ` got the note, `?hub=istanbul` failed the shape check,
    // was read as "no opinion" and replaced with IST -- so the reader saw IST's
    // panel under an address bar still saying istanbul, with nothing on screen
    // to tell them which hub they were reading.
    setUrl("/hublar?hub=istanbul");
    render(<HubsClient />);

    expect(
      await screen.findByText(/izlenen hub'lar arasında değil/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "IST Havalimanı" }),
    ).not.toBeInTheDocument();
    expect(requested.some((path) => path.startsWith("/hubs/ISTANBUL"))).toBe(false);
  });

  it("fetches only what Ağ Sinyalleri draws when the deep link lands there", async () => {
    // İçgörüler links straight to this URL, so it is a landing address and not
    // a state reached after Genel Bakış had already loaded. The tab renders
    // none of the overview's state, so none of the overview's requests should
    // be paid for on first paint.
    setUrl("/hublar?view=network-signals");
    render(<HubsClient />);

    expect(await screen.findByText("Ağ sinyalleri paneli")).toBeInTheDocument();
    expect(requested).toEqual([]);
  });

  it("fetches the overview when the reader switches back to Genel Bakış", async () => {
    // The other direction: gating the effects must not strand the tab that
    // needs them.
    const user = userEvent.setup();
    setUrl("/hublar?view=network-signals");
    render(<HubsClient />);
    await screen.findByText("Ağ sinyalleri paneli");

    await user.click(screen.getByRole("button", { name: "Genel Bakış" }));

    expect(await screen.findByRole("heading", { name: "IST Havalimanı" })).toBeInTheDocument();
    expect(requested.some((path) => path.startsWith("/hubs?days="))).toBe(true);
  });

  it("records a deliberately empty hub selection rather than re-defaulting", async () => {
    const user = userEvent.setup();
    render(<HubsClient />);
    await screen.findByRole("heading", { name: "IST Havalimanı" });

    // Deselecting must not produce the default page's URL -- sending that link
    // would silently put IST back for whoever opened it.
    await user.click(screen.getByRole("button", { name: /^IST/ }));
    await waitFor(() => expect(currentParams().get("hub")).toBe("none"));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "IST Havalimanı" })).not.toBeInTheDocument(),
    );
  });

  it("never shows one hub's evidence under another hub's heading", async () => {
    // IST -> CDG. The panel and the story list used to keep the OLD hub's rows
    // until the new requests landed, so for a round trip the page showed DXB's
    // heading over IST's carriers -- true numbers, wrong instrument, which is
    // the failure the whole error-contract round exists to close.
    const user = userEvent.setup();
    const held: Array<() => void> = [];
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/hubs/DXB")) {
        return new Promise((resolve) => held.push(() => resolve(detail("DXB", 90))));
      }
      if (path.startsWith("/hubs/IST")) return Promise.resolve(detail("IST", 90));
      if (path.startsWith("/hubs")) return Promise.resolve(overview);
      if (path.startsWith("/taxonomy/countries")) return Promise.resolve([]);
      if (path.startsWith("/articles")) return Promise.resolve({ total: 0, items: [] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HubsClient />);
    await screen.findByRole("heading", { name: "IST Havalimanı" });

    await user.click(screen.getByRole("button", { name: /^DXB/ }));

    // While DXB is in flight, IST's panel is GONE -- not left behind under a
    // heading that has already moved.
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "IST Havalimanı" })).not.toBeInTheDocument(),
    );

    held.forEach((resolve) => resolve());
    expect(await screen.findByRole("heading", { name: "DXB Havalimanı" })).toBeInTheDocument();
  });

  it("says the map could not be read instead of shimmering forever", async () => {
    // A failed overview left `overview` null with nothing on the way, so the
    // 380px skeleton animated indefinitely: the page's most prominent element
    // promising a load that was never coming.
    const user = userEvent.setup();
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/taxonomy/countries")) return Promise.resolve([]);
      if (path.startsWith("/articles")) return Promise.resolve({ total: 0, items: [] });
      if (path.startsWith("/hubs")) return Promise.reject(new Error("API request failed: 500"));
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HubsClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("hub-map")).not.toBeInTheDocument();

    serve();
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(await screen.findByTestId("hub-map")).toBeInTheDocument();
  });

  it("keeps 'bu seçim için haber yok' for a selection that genuinely has none", async () => {
    // The negative half. An answered `/articles` with no rows is a measurement
    // about the archive and keeps its own sentence; only a failed request gets
    // the error block.
    render(<HubsClient />);

    expect(
      await screen.findByText(/Bu seçim için haber yok/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Veri geçici olarak kullanılamıyor."),
    ).not.toBeInTheDocument();
  });

  it("blames the story list, not the whole page, when only it fails", async () => {
    apiFetch.mockImplementation((path: string) => {
      requested.push(path);
      if (path.startsWith("/articles")) {
        return Promise.reject(new Error("API request failed: 500"));
      }
      if (path.startsWith("/hubs/IST")) return Promise.resolve(detail("IST", 90));
      if (path.startsWith("/hubs")) return Promise.resolve(overview);
      if (path.startsWith("/taxonomy/countries")) return Promise.resolve([]);
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HubsClient />);

    expect(
      await screen.findByText("Veri geçici olarak kullanılamıyor."),
    ).toBeInTheDocument();
    // The hub panel and the map are untouched: one source down thins the page.
    // Awaited, because the list's failure lands before the panel's success --
    // which is the point: the two sources settle independently now.
    expect(
      await screen.findByRole("heading", { name: "IST Havalimanı" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("hub-map")).toBeInTheDocument();
    expect(screen.queryByText(/Bu seçim için haber yok/)).not.toBeInTheDocument();
  });
});
