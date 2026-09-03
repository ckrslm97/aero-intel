import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Faz 15: the frontend had zero tests. This is deliberately narrow --
// component/hook/pure-function unit tests only, run against jsdom. No
// Playwright/e2e runner here; the six-page smoke test the plan also asks for
// belongs in a browser-driven check, not this config.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // TZ IS PINNED BY THE `test` SCRIPTS (package.json), not here: Node resolves
    // its zone before vitest can set it, so `env: { TZ }` would come too late.
    //
    // It is pinned at all because several surfaces deliberately format record
    // timestamps in UTC -- the campaign drawer's three stamps, BİZ's "Son
    // toplama", the risk drawer's chronology -- on the rule that a record's
    // timestamp must not shift with who is looking at it. Under an unpinned
    // runner those assertions pass for free on a UTC CI box and stop catching
    // the regression they exist for. Europe/Istanbul is UTC+3, so a stamp that
    // slipped back to the reader's own zone visibly moves.
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    css: false,
    coverage: {
      provider: "v8",
      // Only the surfaces Faz 15 asks for coverage on -- app/lib code with no
      // tests at all (echarts wrappers, the Leaflet map components) would
      // otherwise drag the denominator down without anyone having decided
      // those specifically need unit coverage over a browser smoke test.
      include: [
        "src/components/pagination.tsx",
        "src/components/data-source-error.tsx",
        // The error contract's own two components. `server-source-error.tsx`
        // is data-source-error's server-rendered counterpart -- Kokpit has no
        // per-source `retry()` to call, so the retry there is a
        // `router.refresh()` -- and it is checked by the same kind of suite.
        "src/components/server-source-error.tsx",
        // The two search surfaces. What is asserted in their suites is not
        // pixels but a correctness rule with no other way to catch it: which
        // QUERY the list on screen answers when replies arrive out of the
        // order they were asked in. A lit chip labelling another query's
        // articles is a true list under a false heading, and only a test that
        // holds one response open can pin it down.
        "src/components/search-client.tsx",
        "src/components/layout/quick-search.tsx",
        // Kampanya v2: the page's filtering/ordering/URL rules and every
        // surface built on them. The swimlane that used to be excluded here as
        // "a pixel-geometry surface" is gone entirely -- see
        // components/campaigns-client.tsx for the measurement behind that.
        //
        // campaign-windows.tsx IS in the runner even though it draws bars: the
        // thing being asserted is not where a pixel lands, it is that the sale
        // and travel windows are two labelled tracks with different fills,
        // which is the product's central data distinction (§11) and far too
        // important to leave to a screenshot.
        "src/components/campaign-alert-strip.tsx",
        "src/components/campaign-analyst-table.tsx",
        "src/components/campaign-expiring.tsx",
        "src/components/campaign-feed.tsx",
        "src/components/campaign-filters.tsx",
        "src/components/campaign-summary.tsx",
        "src/components/campaign-windows.tsx",
        "src/components/campaigns-client.tsx",
        // Kokpit V2: the page's own rules (freshness, the forecast split,
        // level styling) plus every surface that carries real mapping,
        // ordering or arithmetic logic, plus the two chart primitives whose
        // whole job is to refuse to draw something untrue. The composition
        // (page.tsx, section-header) and the annual-trend echarts wrapper are
        // checked in a browser instead.
        //
        // cockpit-header.tsx used to be listed here as composition, and it is
        // not: its badge decides, from data, whether the page may claim
        // liveness -- and whether "Veri yok" is a measurement or an outage.
        // Those are exactly the verdicts a unit test can pin and a screenshot
        // cannot.
        //
        // fx-forecast-chart.tsx IS counted, though its pixels are still a
        // browser question: what it is tested for is WHICH SERIES it hands to
        // ECharts. The chart draws measured rates, so drawing the previous
        // pair's line under the newly selected pair's heading is not a stale
        // number but a true number labelled as a different instrument -- the
        // one thing on this screen a unit test can pin down exactly.
        //
        // KEEP THIS LIST IN SYNC WITH THE FILES. The v8 provider does NOT
        // error on an `include` entry that no longer exists -- it silently
        // stops counting it, and coverage drops with no failure anywhere.
        "src/components/kokpit/alert-center.tsx",
        "src/components/kokpit/cockpit-header.tsx",
        "src/components/kokpit/competitive-pulse.tsx",
        "src/components/kokpit/daily-summary.tsx",
        "src/components/kokpit/kpi-strip.tsx",
        "src/components/kokpit/market-pulse-row.tsx",
        "src/components/kokpit/fx-board-table.tsx",
        "src/components/kokpit/fx-forecast-chart.tsx",
        "src/components/kokpit/iata-outlook.tsx",
        "src/components/kokpit/sector-balance.tsx",
        "src/components/kokpit/signal-stream.tsx",
        "src/components/charts/micro-trend.tsx",
        "src/components/charts/year-dots.tsx",
        "src/components/ui/delta.tsx",
        // Risk Radarı'nın yeniden tasarımı: the page's rules (filtering,
        // search folding, the coverage/aviation-link wording, the trend
        // transform) plus the drawer, which is where the honesty labels and
        // the keyboard contract live. The map is deliberately not here -- it
        // is a canvas-geometry surface, checked in a browser.
        "src/components/risk/risk-detail-drawer.tsx",
        "src/hooks/*.ts",
        "src/lib/campaigns.ts",
        "src/lib/cockpit.ts",
        "src/lib/format.ts",
        "src/lib/risk.ts",
      ],
    },
  },
});
