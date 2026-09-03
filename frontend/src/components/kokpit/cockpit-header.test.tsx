import { render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { KokpitFxBoardOut, KokpitFxPairOut } from "@/lib/types";

import { CockpitHeader } from "./cockpit-header";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const pair = (currency_pair: string, as_of: string): KokpitFxPairOut => ({
  currency_pair,
  value: 48.25,
  unit: "TRY",
  day_delta_pct: 0.1,
  week_delta_pct: 1.2,
  month_delta_pct: 3.4,
  sparkline: [48.1, 48.25],
  as_of,
  source: "Yahoo Finance",
  source_url: null,
  frequency_label: "~15 dakikada bir",
});

const board = (pairs: KokpitFxPairOut[]): KokpitFxBoardOut => ({
  pairs,
  // The peg carries no `as_of` and takes no part in the header's verdict; it is
  // here only because the payload always has one.
  peg: {
    currency_pair: "USD/SAR",
    value: 3.75,
    label: "Sabit · 3,75 (SAMA)",
    source: "Saudi Central Bank (SAMA)",
    source_url: "https://www.sama.gov.sa",
  },
});

describe("CockpitHeader", () => {
  it("makes no liveness claim in the pre-rendered HTML", () => {
    // MEASURED IN PRODUCTION: this page is served with `revalidate: 60`, and
    // markup built from an 18:03 UTC reading was still being handed out at
    // 18:41 with "Canlı" in it -- a claim that was true when it was computed
    // and false for most of the time it was read. The server-rendered markup
    // now carries the STAMP, which is a fact about the data and stays true in
    // a cache, and no word about whether that stamp is recent.
    const markup = renderToStaticMarkup(
      <CockpitHeader board={board([pair("USD/TRY", minutesAgo(1))])} />,
    );
    expect(markup).not.toContain("Canlı");
    expect(markup).toContain("Veri");
  });

  it("says Canlı in the browser once its own clock says so", () => {
    render(<CockpitHeader board={board([pair("USD/TRY", minutesAgo(5))])} />);
    expect(screen.getByText(/Canlı/)).toBeInTheDocument();
  });

  it("describes the OLDEST reading on the board, not the freshest", () => {
    // Six pairs updating while one pair's cron fails is the normal shape of
    // this outage. Stamping the band with the board's FRESHEST reading let the
    // six vouch for the seventh: a green "Canlı" sitting directly above a
    // three-hour-old row, with nothing on screen able to tell them apart.
    render(
      <CockpitHeader
        board={board([pair("USD/TRY", minutesAgo(2)), pair("EUR/TRY", minutesAgo(180))])}
      />,
    );
    expect(screen.queryByText(/Canlı/)).not.toBeInTheDocument();
    expect(screen.getByText(/3 sa gecikmeli/)).toBeInTheDocument();
  });

  it("says Veri yok rather than dating a board it does not have", () => {
    render(<CockpitHeader board={null} />);
    expect(screen.getByText("Veri yok")).toBeInTheDocument();
  });
});
