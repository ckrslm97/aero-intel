import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FxForecastOut, KpiDetailOut } from "@/lib/types";

import { FxForecastChart } from "./fx-forecast-chart";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

/** Every option this chart ever hands to ECharts, in order.
 *
 * The assertion this file exists for is about FRAMES, not about the final
 * state: "the previous pair's line is gone once the new one loads" would pass
 * even if the wrong series was drawn under the new heading for half a second
 * in between. So the stub records each render and the tests read the whole
 * log. */
const drawn = vi.hoisted(() => ({ options: [] as { series: { name: string; data: unknown }[] }[] }));

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { series: { name: string; data: unknown }[] } }) => {
    drawn.options.push(option);
    const line = option.series.find((series) => series.name === "Gerçekleşen kur");
    return <div data-testid="fx-chart" data-history={JSON.stringify(line?.data ?? [])} />;
  },
}));

const detail = (metricKey: string, points: [string, number][]): KpiDetailOut => ({
  metric_key: metricKey,
  label: metricKey,
  value: points.at(-1)?.[1] ?? 0,
  unit: "TRY",
  delta_pct: null,
  delta_points: null,
  up_is_good: false,
  is_estimate: false,
  as_of: "2026-09-01T00:00:00Z",
  period_label: null,
  comparison_label: null,
  source: "Yahoo Finance",
  source_url: null,
  corroborations: [],
  corroboration_match_pct: null,
  history: points.map(([as_of, value]) => ({ as_of, value })),
  history_is_external: false,
  history_provenance: "own_history",
  history_provenance_tr: null,
  period: "1y",
});

const forecast = (pair: string, value: number): FxForecastOut => ({
  institution: "JPMorgan",
  currency_pair: pair,
  horizon_label: "Q4 2026",
  horizon_months: 3,
  value,
  publication_date: "2026-06-01",
  source_url: "https://example.test",
  note_tr: null,
  target_date: "2026-11-15",
  target_date_basis_tr: "Çeyrek ortası",
});

/** The two pairs' MEASURED closes, far enough apart that one drawn under the
 * other's name is unmistakable in an assertion. */
const USD_TRY = detail("fx_usd_try", [
  ["2026-08-01T00:00:00Z", 41.2],
  ["2026-09-01T00:00:00Z", 42.3],
]);
const EUR_TRY = detail("fx_eur_try", [
  ["2026-08-01T00:00:00Z", 47.5],
  ["2026-09-01T00:00:00Z", 48.1],
]);

const historyOf = () => screen.getByTestId("fx-chart").getAttribute("data-history") ?? "";

beforeEach(() => {
  drawn.options.length = 0;
  apiFetch.mockReset();
});

describe("FxForecastChart", () => {
  it("never draws one pair's realised rate under another pair's name", async () => {
    // EUR/TRY is held open on purpose: the frame under test is the one after
    // the reader clicks the second row and before its history answers.
    let answerEur: (detail: KpiDetailOut) => void = () => {};
    apiFetch.mockImplementation((path: string) =>
      path.includes("fx_usd_try")
        ? Promise.resolve(USD_TRY)
        : new Promise<KpiDetailOut>((resolve) => {
            answerEur = resolve;
          }),
    );

    const { rerender } = render(
      <FxForecastChart pair="USD/TRY" rows={[forecast("USD/TRY", 43.0)]} />,
    );
    expect(await screen.findByTestId("fx-chart")).toBeInTheDocument();
    expect(historyOf()).toContain("42.3");

    drawn.options.length = 0;
    rerender(<FxForecastChart pair="EUR/TRY" rows={[forecast("EUR/TRY", 49.0)]} />);

    // The heading beside this chart already says EUR/TRY (fx-board-table.tsx
    // renders it from the same `chartPair`). So there is no chart at all yet,
    // and ECharts was handed nothing in the meantime -- not one frame of
    // USD/TRY's closes under EUR/TRY's name, on a y axis scaled to lira-per-
    // dollar.
    expect(screen.queryByTestId("fx-chart")).not.toBeInTheDocument();
    expect(drawn.options).toHaveLength(0);

    await act(async () => answerEur(EUR_TRY));

    expect(historyOf()).toContain("48.1");
    expect(historyOf()).not.toContain("42.3");
    expect(JSON.stringify(drawn.options)).not.toContain("42.3");
  });

  it("keeps the line drawn when the pair has not changed", async () => {
    // The other half: the reset is bound to the SELECTION, not to renders. A
    // parent re-render that leaves the pair alone must not blink the chart out
    // and re-fetch a year of closes.
    apiFetch.mockResolvedValue(USD_TRY);

    const { rerender } = render(
      <FxForecastChart pair="USD/TRY" rows={[forecast("USD/TRY", 43.0)]} />,
    );
    expect(await screen.findByTestId("fx-chart")).toBeInTheDocument();

    rerender(
      <FxForecastChart pair="USD/TRY" rows={[forecast("USD/TRY", 43.0), forecast("USD/TRY", 44.0)]} />,
    );

    expect(screen.getByTestId("fx-chart")).toBeInTheDocument();
    expect(historyOf()).toContain("42.3");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("draws no line at all when the payload measures a different metric", async () => {
    // Belt and braces, at the point the series is handed to ECharts: if a
    // response for another key ever reaches this component -- a cached body, a
    // redirected key -- the forecast markers still render and the realised
    // line is simply absent. An empty line is a missing measurement; a wrong
    // line is a false one.
    apiFetch.mockResolvedValue(EUR_TRY);

    render(<FxForecastChart pair="USD/TRY" rows={[forecast("USD/TRY", 43.0)]} />);

    expect(await screen.findByTestId("fx-chart")).toBeInTheDocument();
    expect(historyOf()).toBe("[]");
    expect(JSON.stringify(drawn.options)).toContain("43");
  });

  it("says the history was not read rather than that the pair has none", async () => {
    // THE REGRESSION THIS BRANCH EXISTS FOR. `/kpis/fx_usd_try` answering 500
    // leaves `detail` null and `closes` empty; with no datable forecast either,
    // the panel printed "USD/TRY için ne kur geçmişi ne de tarihlendirilebilir
    // bir kurum tahmini var." -- a checkable claim about the archive assembled
    // out of an HTTP failure, on the top screen of the product.
    apiFetch.mockRejectedValue(new Error("500"));

    render(<FxForecastChart pair="USD/TRY" rows={[]} />);

    expect(await screen.findByText(/kur geçmişi okunamadı/)).toBeInTheDocument();
    expect(
      screen.queryByText(/ne kur geçmişi ne de tarihlendirilebilir bir kurum tahmini var/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Yeniden dene/ })).toBeInTheDocument();
  });

  it("still says 'yok' when the request answered and answered with nothing", async () => {
    // The negative half. If the unread branch swallowed the empty one too, the
    // product would lose its ability to report a real measurement -- an
    // answered request that found no closes and no datable forecast.
    apiFetch.mockResolvedValue(detail("fx_usd_try", []));

    render(<FxForecastChart pair="USD/TRY" rows={[]} />);

    expect(
      await screen.findByText(/ne kur geçmişi ne de tarihlendirilebilir bir kurum tahmini var/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/okunamadı/)).not.toBeInTheDocument();
  });

  it("does not answer a question it never asked, for a pair with no metric key", async () => {
    // TRY/JPY is not in PAIR_METRIC_KEYS, so no history request is ever made
    // for it. "Kur geçmişi yok" would be a verdict on a question this component
    // never put to the server, and "okunamadı" would name a failure that never
    // happened.
    render(<FxForecastChart pair="TRY/JPY" rows={[]} />);

    expect(await screen.findByText(/bu sistemde kaydedilmiyor/)).toBeInTheDocument();
    expect(screen.queryByText(/okunamadı/)).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("names the unread history even when the forecast markers still draw", async () => {
    // The markers come from `rows`, which the parent already holds, so a dead
    // history endpoint yields a chart with points and no realised line -- and
    // an absent line on a chart whose legend promises one is the same claim
    // ("this pair has no measured history") in a quieter voice.
    apiFetch.mockRejectedValue(new Error("500"));

    render(<FxForecastChart pair="USD/TRY" rows={[forecast("USD/TRY", 43.0)]} />);

    expect(await screen.findByTestId("fx-chart")).toBeInTheDocument();
    expect(historyOf()).toBe("[]");
    expect(screen.getByText(/kur geçmişi okunamadı/)).toBeInTheDocument();
  });
});
