import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AlertCenter } from "./alert-center";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

const campaignAlert = (overrides: Record<string, unknown> = {}) => ({
  id: "c1",
  promotion_id: "p1",
  alert_type: "EXPIRING",
  priority: "MEDIUM",
  title_tr: "TK Avrupa kampanyası bitiyor",
  detail_json: null,
  created_at: hoursAgo(3),
  ...overrides,
});

const riskItem = (overrides: Record<string, unknown> = {}) => ({
  id: "r1",
  headline: "Etna'da kül bulutu uçuşları durdurdu",
  url: "https://example.test",
  source_name: "Reuters",
  published_at: hoursAgo(1),
  risk_type: "volcano",
  risk_family: "natural",
  risk_type_label_tr: "Volkanik aktivite",
  severity: "high",
  country: "İtalya",
  city: "Catania",
  region: "europe",
  is_fresh: true,
  source_count: 2,
  ...overrides,
});

const radar = (items: ReturnType<typeof riskItem>[]) => ({
  days: 14,
  total: items.length,
  countries: [
    {
      country: "İtalya",
      region: "europe",
      count: items.length,
      score: 3 * items.length,
      severity_counts: { high: items.length, medium: 0, low: 0 },
      items,
    },
  ],
  type_counts: {},
  family_counts: {},
});

/** Route each mocked call by path, so the two streams can be failed and
 * emptied independently -- which is the whole point of the component. */
function routes({ alerts, risks }: { alerts?: unknown; risks?: unknown }) {
  apiFetch.mockImplementation((path?: string) => {
    if (path?.startsWith("/campaign-alerts")) {
      return alerts instanceof Error ? Promise.reject(alerts) : Promise.resolve(alerts ?? []);
    }
    if (path?.startsWith("/risks")) {
      return risks instanceof Error ? Promise.reject(risks) : Promise.resolve(risks ?? radar([]));
    }
    // Rejected, never thrown: a synchronous throw out of the fetcher escapes
    // useDataSource's own .catch and surfaces as a React render error instead
    // of the fetch failure the component is designed to handle.
    return Promise.reject(new Error(`unexpected path ${String(path)}`));
  });
}

describe("AlertCenter", () => {
  // Braces, not a concise arrow body: `mockReset()` returns the mock for
  // chaining, and Vitest treats a function returned from beforeEach as a
  // per-test CLEANUP hook -- so `() => apiFetch.mockReset()` quietly registers
  // the mock itself as teardown and calls it with no arguments after every
  // test, which lands in `mockImplementation` as an unroutable `undefined`
  // path.
  beforeEach(() => {
    apiFetch.mockReset();
  });

  /** The section opens CLOSED, so every row assertion has to expand it first. */
  async function expand() {
    await userEvent.click(await screen.findByRole("button", { name: /Genişlet/ }));
  }

  it("starts collapsed, showing counts rather than rows", async () => {
    routes({ alerts: [campaignAlert()], risks: radar([riskItem()]) });
    render(<AlertCenter />);

    expect(await screen.findByText(/1 ORTA/)).toBeInTheDocument();
    expect(await screen.findByText(/1 YÜKSEK/)).toBeInTheDocument();
    // The bottom of the page is not where a reader is scanning; the rows are
    // one click away, the counts are not.
    expect(screen.queryByText("TK Avrupa kampanyası bitiyor")).not.toBeInTheDocument();
  });

  it("merges both streams once expanded", async () => {
    routes({ alerts: [campaignAlert()], risks: radar([riskItem()]) });
    render(<AlertCenter />);
    await expand();

    expect(screen.getByText("TK Avrupa kampanyası bitiyor")).toBeInTheDocument();
    expect(screen.getByText("Etna'da kül bulutu uçuşları durdurdu")).toBeInTheDocument();
  });

  it("orders by priority before recency", async () => {
    routes({
      alerts: [
        campaignAlert({ id: "old", priority: "INFO", title_tr: "Bilgi", created_at: hoursAgo(0.1) }),
        campaignAlert({
          id: "crit",
          priority: "CRITICAL",
          title_tr: "Kritik",
          created_at: hoursAgo(9),
        }),
      ],
      risks: radar([]),
    });
    render(<AlertCenter />);
    await expand();

    const titles = screen.getAllByText(/^(Kritik|Bilgi)$/).map((node) => node.textContent);
    // A CRITICAL from nine hours ago outranks an INFO from six minutes ago.
    expect(titles).toEqual(["Kritik", "Bilgi"]);
  });

  it("caps the open list at three rows", async () => {
    routes({
      alerts: Array.from({ length: 5 }, (_, i) =>
        campaignAlert({ id: `c${i}`, title_tr: `Uyarı ${i}` }),
      ),
      risks: radar([]),
    });
    render(<AlertCenter />);
    await expand();

    expect(screen.getByText("Uyarı 0")).toBeInTheDocument();
    expect(screen.queryByText("Uyarı 3")).not.toBeInTheDocument();
    // ...but the BAND still counts all five. A count computed over the three
    // visible rows would be a number nobody could reconcile with /kampanyalar.
    expect(screen.getByText(/5 ORTA/)).toBeInTheDocument();
  });

  it("only lifts high-severity risk items in, and only as HIGH", async () => {
    routes({
      alerts: [],
      risks: radar([riskItem(), riskItem({ id: "r2", severity: "medium", headline: "Orta önem" })]),
    });
    render(<AlertCenter />);
    await expand();

    expect(screen.getByText("Etna'da kül bulutu uçuşları durdurdu")).toBeInTheDocument();
    expect(screen.queryByText("Orta önem")).not.toBeInTheDocument();
    expect(screen.getByText(/1 YÜKSEK/)).toBeInTheDocument();
  });

  it("still renders one stream when the other fails", async () => {
    routes({ alerts: [campaignAlert()], risks: new Error("API request failed: 500") });
    render(<AlertCenter />);
    await expand();

    expect(screen.getByText("TK Avrupa kampanyası bitiyor")).toBeInTheDocument();
  });

  it("prints its zeroes rather than hiding the section", async () => {
    // A silent section says nothing; "0 KRİTİK" says the streams answered and
    // had nothing to report, which is a different and useful statement.
    routes({ alerts: [], risks: radar([]) });
    render(<AlertCenter />);

    expect(await screen.findByText(/0 KRİTİK/)).toBeInTheDocument();
    expect(screen.getByText(/0 YÜKSEK/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Genişlet/ })).toBeDisabled();
  });
});
