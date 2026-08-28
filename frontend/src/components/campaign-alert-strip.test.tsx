import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignAlertStrip } from "./campaign-alert-strip";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const alert = (overrides: Record<string, unknown> = {}) => ({
  id: "a1",
  promotion_id: "p1",
  alert_type: "EXPIRING",
  priority: "CRITICAL",
  title_tr: "TK Avrupa kampanyası 2 gün içinde bitiyor",
  detail_json: null,
  created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
  ...overrides,
});

describe("CampaignAlertStrip", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("renders each alert with its type, title and age", async () => {
    apiFetch.mockResolvedValue([alert()]);
    render(<CampaignAlertStrip />);

    expect(
      await screen.findByText("TK Avrupa kampanyası 2 gün içinde bitiyor"),
    ).toBeInTheDocument();
    expect(screen.getByText("Bitmek üzere")).toBeInTheDocument();
    expect(screen.getByText("3 sa önce")).toBeInTheDocument();
    expect(screen.getByLabelText("Kampanya radarı")).toBeInTheDocument();
  });

  it("renders nothing at all when the endpoint is missing", async () => {
    // PR6 ships the endpoint; until then a 404 must not put an error box at
    // the top of a working page. This is the one surface where swallowing the
    // failure is the correct behaviour.
    apiFetch.mockRejectedValue(new Error("API request failed: 404"));
    const { container } = render(<CampaignAlertStrip />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing when there is simply nothing unacknowledged", async () => {
    apiFetch.mockResolvedValue([]);
    const { container } = render(<CampaignAlertStrip />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("asks the endpoint for the unacknowledged head of the queue", async () => {
    apiFetch.mockResolvedValue([]);
    render(<CampaignAlertStrip limit={5} />);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/campaign-alerts?limit=5",
        expect.objectContaining({ cache: "default" }),
      ),
    );
  });
});
