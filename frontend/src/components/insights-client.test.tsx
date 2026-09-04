import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InsightsClient } from "./insights-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const digest = {
  date: "2026-09-02",
  body: "europe (1 duyuru) tarafında hareket var.",
  provider: "heuristic",
};

/** The payload as the API actually publishes it now -- no `new_route_signals`
 * key and no `windows.new_route_signals`. */
const insights = (overrides: Record<string, unknown> = {}) => ({
  generated_at: "2026-09-02T09:00:00Z",
  windows: {
    airline_momentum: {
      days: 7,
      since: "2026-08-26T09:00:00Z",
      until: "2026-09-02T09:00:00Z",
    },
    sentiment_by_category: {
      days: 30,
      since: "2026-08-03T09:00:00Z",
      until: "2026-09-02T09:00:00Z",
    },
  },
  airline_momentum: [],
  sentiment_by_category: [],
  digest,
  ...overrides,
});

describe("InsightsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("prints the digest and points at the Hub tab that owns new routes", async () => {
    apiFetch.mockResolvedValue(insights());

    render(<InsightsClient />);

    expect(await screen.findByText(digest.body)).toBeInTheDocument();
    // A deep link, not just a route: HubsClient owns ?view, so this lands on
    // the Ağ Sinyalleri tab itself.
    expect(screen.getByRole("link", { name: /Yeni hat sinyalleri/ })).toHaveAttribute(
      "href",
      "/hublar?view=network-signals",
    );
  });

  it("counts no new routes of its own, even when handed a stale payload", async () => {
    // THE REGRESSION THIS PAGE EXISTS NOT TO HAVE. /insights used to publish a
    // per-article `new_route_signals` block while /hubs/network-signals
    // published a per-event count of the same announcements, so the two
    // screens printed two different sizes for one piece of competitor
    // activity. A cached edge can still serve the old body to this bundle;
    // when it does, the page must draw exactly nothing from it rather than
    // resurrect the second tally.
    apiFetch.mockResolvedValue(
      insights({
        windows: {
          airline_momentum: {
            days: 7,
            since: "2026-08-26T09:00:00Z",
            until: "2026-09-02T09:00:00Z",
          },
          new_route_signals: {
            days: 30,
            since: "2026-08-03T09:00:00Z",
            until: "2026-09-02T09:00:00Z",
          },
          sentiment_by_category: {
            days: 30,
            since: "2026-08-03T09:00:00Z",
            until: "2026-09-02T09:00:00Z",
          },
        },
        new_route_signals: [
          {
            region: "europe",
            count: 3,
            articles: [
              {
                id: "a1",
                headline: "QR DOH–MXP hattını açıyor",
                url: "https://example.test/qr",
                source_name: "Reuters",
                published_at: "2026-09-01T08:00:00Z",
                airlines: ["QR"],
                airports: [],
              },
            ],
          },
        ],
      }),
    );

    render(<InsightsClient />);
    await screen.findByText(digest.body);

    expect(screen.queryByText("QR DOH–MXP hattını açıyor")).not.toBeInTheDocument();
    expect(screen.queryByText("Toplam sinyal")).not.toBeInTheDocument();
    expect(screen.queryByText("Çözümlenemedi")).not.toBeInTheDocument();
    expect(screen.queryByText("3")).not.toBeInTheDocument();
    // Only /insights is asked for -- the ledger is not quietly re-pointed at
    // the v2 endpoint, which would put one instrument on two pages.
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch.mock.calls[0][0]).toBe("/insights");
  });

  it("says the digest has not been assembled rather than showing a gap", async () => {
    apiFetch.mockResolvedValue(insights({ digest: null }));

    render(<InsightsClient />);

    expect(
      await screen.findByText("Günün örüntü özeti henüz derlenmedi."),
    ).toBeInTheDocument();
  });

  it("surfaces a failed load instead of an empty page, and offers a way back", async () => {
    // The failure branch used to be a sentence and nothing else: a reader who
    // hit a five-second outage could only reload the route. It is now the
    // house error block, whose retry re-runs the same fetch -- so a second
    // attempt is one click, and a page that comes back stays on this tab.
    apiFetch.mockRejectedValueOnce(new Error("API request failed: 500"));

    render(<InsightsClient />);

    await waitFor(() =>
      expect(screen.getByText("Veri geçici olarak kullanılamıyor.")).toBeInTheDocument(),
    );
    // No digest sentence, no signpost, no gap pretending to be an answer.
    expect(screen.queryByText(digest.body)).not.toBeInTheDocument();
    expect(screen.queryByText("Günün örüntü özeti henüz derlenmedi.")).not.toBeInTheDocument();

    apiFetch.mockResolvedValue(insights());
    await userEvent.click(screen.getByRole("button", { name: /Yeniden dene/ }));

    expect(await screen.findByText(digest.body)).toBeInTheDocument();
  });
});
