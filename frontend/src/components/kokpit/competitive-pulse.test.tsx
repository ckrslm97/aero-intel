import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompetitivePulse } from "./competitive-pulse";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const insights = (momentum: unknown[]) => ({
  generated_at: "2026-09-01T00:00:00Z",
  airline_momentum: momentum,
  top_topics: [],
  sentiment: [],
});

const routeGroup = (overrides: Record<string, unknown> = {}) => ({
  region: "europe",
  count: 5,
  articles: [
    {
      headline: "QR DOH–MXP hattını açıyor",
      url: "https://example.test",
      airlines: ["QR"],
    },
  ],
  ...overrides,
});

/** Route by path so each of the three sources can fail on its own -- which is
 * the whole point of the cells degrading independently. */
function routes({
  count,
  insightsOut,
  routeGroups,
  routesAsBareList = false,
}: {
  count?: unknown;
  insightsOut?: unknown;
  routeGroups?: unknown;
  /** Serve the PRE-envelope body -- what a stale edge can still hand this
   * bundle for up to ~30 minutes after a deploy. */
  routesAsBareList?: boolean;
}) {
  apiFetch.mockImplementation((path?: string) => {
    if (path?.startsWith("/promotions/new-count")) {
      return count instanceof Error
        ? Promise.reject(count)
        : Promise.resolve(count ?? { window_hours: 48, count: 0, airline_codes: [] });
    }
    if (path?.startsWith("/insights")) {
      return insightsOut instanceof Error
        ? Promise.reject(insightsOut)
        : Promise.resolve(insightsOut ?? insights([]));
    }
    if (path?.startsWith("/hubs/network-signals")) {
      // An envelope, not a bare list: the endpoint stamps its own window
      // (backend/app/api/window.py) and the cell reads `regions` out of it.
      if (routeGroups instanceof Error) return Promise.reject(routeGroups);
      if (routesAsBareList) return Promise.resolve(routeGroups ?? []);
      return Promise.resolve({
        generated_at: "2026-09-01T00:00:00Z",
        window: {
          days: 30,
          since: "2026-08-02T00:00:00Z",
          until: "2026-09-01T00:00:00Z",
        },
        regions: routeGroups ?? [],
      });
    }
    return Promise.reject(new Error(`unexpected path ${String(path)}`));
  });
}

describe("CompetitivePulse", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("does not print a zero, or an emptiness, when the source failed", async () => {
    // The regression: every cell branched on `loaded` alone, and
    // `useDataSource` sets `loaded` on a FAILED request too. A 500 therefore
    // rendered a confident "0" plus "Son 48 saatte yeni kampanya yok." -- a
    // claim about the world produced by knowing nothing about it.
    routes({
      count: new Error("API request failed: 500"),
      insightsOut: new Error("API request failed: 500"),
      routeGroups: new Error("API request failed: 500"),
    });
    render(<CompetitivePulse />);

    // `waitFor`, not `findAllByText`: the latter resolves on the FIRST match,
    // so a three-source assertion made off it passes or fails depending on
    // which of the three mocked promises happened to flush first.
    await waitFor(() => expect(screen.getAllByText("Kaynak okunamadı.")).toHaveLength(3));
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText(/Son 48 saatte yeni kampanya yok/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yeni rota sinyali yok/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Yeniden dene/ })).toHaveLength(3);
  });

  it("still prints a measured zero, because a measured zero is information", async () => {
    routes({ count: { window_hours: 48, count: 0, airline_codes: [] } });
    render(<CompetitivePulse />);

    const zero = await screen.findByText("0");
    expect(zero).toBeInTheDocument();
    // ONCE, and quietly. It used to be a 20px/600 figure -- the same weight as
    // the KPI strip's real numbers -- followed by a sentence saying the same
    // thing in words: the section's largest type, spent twice on "nothing
    // happened".
    expect(zero.className).toContain("text-muted-foreground");
    expect(zero.className).not.toContain("text-xl");
    expect(screen.queryByText(/Son 48 saatte yeni kampanya yok/)).not.toBeInTheDocument();
  });

  it("separates 'measured, nothing moved' from 'no measurement'", async () => {
    routes({ insightsOut: insights([{ code: "EK", name: "Emirates", previous: 3, current: 3, delta: 0 }]) });
    render(<CompetitivePulse />);

    expect(await screen.findByText(/Bu hafta belirgin bir hareket yok/)).toBeInTheDocument();
    expect(screen.queryByText(/Momentum verisi yok/)).not.toBeInTheDocument();
  });

  it("never ranks TK as its own rival", async () => {
    // THE REGRESSION. `/insights` counts carrier mentions across the whole
    // feed, and in a Turkish-language feed the most-mentioned carrier is
    // always TK -- so the "Rekabet" cell's top mover was the airline the page
    // is written for. RIVAL_CODES (backend/app/taxonomy.py, via
    // taxonomy.gen.ts) leaves out the home carrier on purpose.
    routes({
      insightsOut: insights([
        { code: "TK", name: "Turkish Airlines", previous: 40, current: 61, delta: 21 },
        { code: "LH", name: "Lufthansa", previous: 4, current: 7, delta: 3 },
      ]),
    });
    render(<CompetitivePulse />);

    expect(await screen.findByText("LH")).toBeInTheDocument();
    expect(screen.queryByText("TK")).not.toBeInTheDocument();
  });

  it("does not report 'nothing moved' when only the home carrier moved", async () => {
    // The other half: dropping TK must not turn its move into a measured
    // stillness. Nothing rival-shaped was in the payload at all, and that is a
    // third state -- not "we have no data", not "rivals were flat".
    routes({
      insightsOut: insights([
        { code: "TK", name: "Turkish Airlines", previous: 40, current: 61, delta: 21 },
      ]),
    });
    render(<CompetitivePulse />);

    expect(await screen.findByText(/rakip taşıyıcı ölçülmedi/)).toBeInTheDocument();
    expect(screen.queryByText(/Momentum verisi yok/)).not.toBeInTheDocument();
    expect(screen.queryByText(/belirgin bir hareket yok/)).not.toBeInTheDocument();
  });

  it("says so when the momentum stream returned nothing at all", async () => {
    routes({ insightsOut: insights([]) });
    render(<CompetitivePulse />);

    expect(await screen.findByText(/Momentum verisi yok/)).toBeInTheDocument();
  });

  it("never puts a worldwide count and a single region on one line", async () => {
    // "14 · Avrupa" reads as "fourteen new route signals in Europe". It never
    // was: the count is every region added up, and Europe is merely the first
    // group that happened to carry an article.
    routes({
      routeGroups: [
        routeGroup(),
        routeGroup({ region: "middle-east", count: 9, articles: [] }),
      ],
    });
    render(<CompetitivePulse />);

    const total = (await screen.findByText("14")).parentElement!;
    expect(total.textContent).toContain("tüm bölgeler");
    expect(total.textContent).not.toContain("Avrupa");
    // The region stays attached to the headline it actually belongs to.
    expect(screen.getByText(/QR DOH–MXP/).textContent).toContain("Avrupa");
  });

  it("still counts the signals when a stale edge serves the pre-envelope list", async () => {
    // /hubs/network-signals went from a bare list to an envelope so the tab
    // could stamp a real "son güncelleme". The switch is not atomic: the
    // response is edge-cached for 300s and served stale for 1500 more, so this
    // bundle can be handed the OLD body. Reading `.regions` only, `routeGroups`
    // would be undefined and this cell would print "0 · sinyal yok" over a
    // payload that has five -- data present, nothing shown, no error.
    routes({ routeGroups: [routeGroup()], routesAsBareList: true });
    render(<CompetitivePulse />);

    expect((await screen.findByText("5")).parentElement!.textContent).toContain(
      "tüm bölgeler",
    );
  });

  it("draws the same thing from the envelope", async () => {
    routes({ routeGroups: [routeGroup()] });
    render(<CompetitivePulse />);

    expect((await screen.findByText("5")).parentElement!.textContent).toContain(
      "tüm bölgeler",
    );
  });
});
