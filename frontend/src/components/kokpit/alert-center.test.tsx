import { render, screen, waitFor } from "@testing-library/react";
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

  it("merges both streams and labels which one each row came from", async () => {
    routes({ alerts: [campaignAlert()], risks: radar([riskItem()]) });
    render(<AlertCenter />);

    expect(await screen.findByText("TK Avrupa kampanyası bitiyor")).toBeInTheDocument();
    expect(screen.getByText("Etna'da kül bulutu uçuşları durdurdu")).toBeInTheDocument();
    expect(screen.getByText("Kampanya")).toBeInTheDocument();
    expect(screen.getByText("Risk")).toBeInTheDocument();
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

    await screen.findByText("Kritik");
    const titles = screen.getAllByText(/^(Kritik|Bilgi)$/).map((node) => node.textContent);
    // A CRITICAL from nine hours ago outranks an INFO from six minutes ago.
    expect(titles).toEqual(["Kritik", "Bilgi"]);
  });

  it("only lifts high-severity risk items in, and only as HIGH", async () => {
    routes({
      alerts: [],
      risks: radar([riskItem(), riskItem({ id: "r2", severity: "medium", headline: "Orta" })]),
    });
    render(<AlertCenter />);

    await screen.findByText("Etna'da kül bulutu uçuşları durdurdu");
    expect(screen.queryByText("Orta")).not.toBeInTheDocument();
    expect(screen.getByText(/Yüksek 1/)).toBeInTheDocument();
  });

  it("still renders one stream when the other fails", async () => {
    routes({ alerts: [campaignAlert()], risks: new Error("API request failed: 500") });
    render(<AlertCenter />);

    expect(await screen.findByText("TK Avrupa kampanyası bitiyor")).toBeInTheDocument();
  });

  it("is honestly empty rather than hopeful when both are quiet", async () => {
    routes({ alerts: [], risks: radar([]) });
    render(<AlertCenter />);

    await waitFor(() => expect(screen.getByText("Aktif uyarı yok.")).toBeInTheDocument());
  });
});
