import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KpiDetailOut } from "@/lib/types";

import { KpiDetailClient } from "./kpi-detail-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

// The chart is an echarts instance behind a lazy boundary; this suite is about
// which FIGURES the page prints.
vi.mock("@/components/charts/kpi-detail-chart", () => ({
  KpiDetailChart: () => <div data-testid="kpi-chart" />,
}));

const detail = (overrides: Partial<KpiDetailOut> = {}): KpiDetailOut => ({
  metric_key: "fx_eur_usd",
  label: "EUR/USD",
  value: 1.085,
  unit: "USD",
  delta_pct: 0.42,
  delta_points: null,
  up_is_good: true,
  is_estimate: false,
  as_of: "2026-09-01T12:00:00Z",
  period_label: null,
  comparison_label: "önceki ölçüme göre",
  source: "Yahoo Finance",
  source_url: "https://finance.yahoo.com",
  corroborations: [],
  corroboration_match_pct: 0.5,
  history: [],
  history_is_external: false,
  history_provenance: "own_history",
  history_provenance_tr: "Bu grafik sistemin kendi kayıtlarından üretildi.",
  period: "1m",
  ...overrides,
});

describe("KpiDetailClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("quotes a currency cross the way the rest of the app quotes it", async () => {
    // THE REGRESSION. This page formatted every metric with the dashboard's
    // compact formatter, which quotes to one decimal: EUR/USD read "1,1" here
    // and "1,0850" on Kokpit -- one reading, one product, two numbers.
    apiFetch.mockResolvedValue(detail());
    render(<KpiDetailClient metricKey="fx_eur_usd" />);

    expect(await screen.findByText("1,0850")).toBeInTheDocument();
    expect(screen.queryByText("1,1")).not.toBeInTheDocument();
    // And the delta in the app's own vocabulary -- "%" before the number, a
    // Turkish decimal comma -- rather than this page's private "+0.4%".
    expect(screen.getByText("+%0,4")).toBeInTheDocument();
  });

  it("moves a percentage metric in points, and says which period it describes", async () => {
    // A load factor going 83,0 -> 83,4 rose 0,4 POINTS. The page used to print
    // its percent form and label it "önceki ölçüme göre" even for a full-year
    // forecast compared against last year.
    apiFetch.mockResolvedValue(
      detail({
        metric_key: "load_factor",
        label: "Yolcu doluluk oranı",
        value: 83.4,
        unit: "%",
        delta_pct: null,
        delta_points: 0.4,
        period_label: "2026 · tahmin",
        comparison_label: "2025'e göre",
      }),
    );
    render(<KpiDetailClient metricKey="load_factor" />);

    expect(await screen.findByText("+0,4 puan")).toBeInTheDocument();
    expect(screen.getByText("2026 · tahmin")).toBeInTheDocument();
    expect(screen.getByText("2025'e göre")).toBeInTheDocument();
    expect(screen.queryByText(/önceki ölçüme göre/)).not.toBeInTheDocument();
    // Two decimals, the same precision Market Pulse gives the same figure.
    expect(screen.getByText("83,40")).toBeInTheDocument();
  });

  it("prints no delta at all rather than a wrong one when the payload has neither", async () => {
    // The negative half. `delta_pct` and `delta_points` are mutually exclusive
    // by construction (see KpiOut in lib/types.ts); with neither, there is
    // nothing to say and the row is absent instead of showing "0".
    apiFetch.mockResolvedValue(
      detail({ delta_pct: null, delta_points: null, comparison_label: null }),
    );
    render(<KpiDetailClient metricKey="fx_eur_usd" />);

    expect(await screen.findByText("1,0850")).toBeInTheDocument();
    expect(screen.queryByText(/puan/)).not.toBeInTheDocument();
    expect(screen.queryByText(/%0,0/)).not.toBeInTheDocument();
  });
});
