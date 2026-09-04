import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";
import { riskCountry, riskItem } from "@/lib/__fixtures__/risk";
import type { RiskRadarOut } from "@/lib/types";

import { RiskRadarClient } from "./risk-radar-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// Canvas-geometry surfaces, checked in a browser rather than here.
vi.mock("@/components/risk-map", () => ({ RiskMap: () => <div data-testid="risk-map" /> }));
vi.mock("@/components/risk/risk-trend-chart-lazy", () => ({
  RiskTrendChart: () => <div data-testid="risk-trend" />,
}));

const item = riskItem({
  id: "r1",
  headline: "Etna'da kül bulutu",
  country: "Yunanistan",
  region: "europe",
});

const radar: RiskRadarOut = {
  days: 5,
  total: 1,
  suppressed_low_confidence: 0,
  countries: [riskCountry("Yunanistan", [item])],
  type_counts: {},
  family_counts: {},
  generated_at: "2026-09-02T09:00:00Z",
};

function serve() {
  apiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/risks/trend")) {
      return Promise.resolve({ days: 30, points: [], note: "Yayın hacmi." });
    }
    if (path.startsWith("/risks")) return Promise.resolve(radar);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

const verificationLink = () =>
  screen.getByRole("link", { name: "Veri doğrulama" }).getAttribute("href");

describe("RiskRadarClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    resetNavigation("/risk-radari");
    serve();
  });

  it("links to the audit view bare while the page is on its own defaults", async () => {
    render(<RiskRadarClient />);
    await screen.findByRole("heading", { name: "Risk Radarı" });

    // Nothing to carry, so nothing is carried: the audit's default window IS
    // this page's default window.
    expect(verificationLink()).toBe("/risk-radari/dogrulama");
  });

  it("hands the audit view the window and country it is showing", async () => {
    // The bug this closes: the link used to be bare, so a reader on a 30-day
    // radar clicked "Veri doğrulama" and audited five days. Two screens, two
    // sets of days, one question.
    setUrl("/risk-radari?days=30&country=Yunanistan");
    render(<RiskRadarClient />);
    await screen.findByRole("heading", { name: "Risk Radarı" });

    expect(verificationLink()).toBe("/risk-radari/dogrulama?days=30&country=Yunanistan");
  });

  it("keeps the link in step when the window is changed on the page", async () => {
    const user = userEvent.setup();
    render(<RiskRadarClient />);
    await screen.findByRole("heading", { name: "Risk Radarı" });

    // "14g" is what the chip PRINTS; "Son 14 gün" is what it is called. The
    // two-character label is a space constraint on the densest filter panel in
    // the app, not the control's name.
    await user.click(screen.getByRole("button", { name: "Son 14 gün" }));

    await waitFor(() => expect(currentParams().get("days")).toBe("14"));
    expect(verificationLink()).toBe("/risk-radari/dogrulama?days=14");
  });
});
