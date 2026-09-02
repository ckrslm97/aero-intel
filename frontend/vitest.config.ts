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
        // PR7: the campaign page's filtering/labelling rules and the two
        // components built on top of them. The swimlane is deliberately not
        // here -- it is a pixel-geometry surface, checked in a browser.
        "src/components/campaign-alert-strip.tsx",
        "src/components/campaign-analyst-table.tsx",
        // The swimlane's clustered marker: geometry stays out of the runner,
        // but the count, the list it opens and its keyboard exits do not.
        "src/components/campaign-cluster-marker.tsx",
        // Kokpit V2: the page's own rules (freshness, the forecast split,
        // level styling) plus every surface that carries real mapping,
        // ordering or arithmetic logic, plus the two chart primitives whose
        // whole job is to refuse to draw something untrue. The composition
        // (page.tsx, section-header, cockpit-header) and the two echarts
        // wrappers are checked in a browser instead.
        //
        // KEEP THIS LIST IN SYNC WITH THE FILES. The v8 provider does NOT
        // error on an `include` entry that no longer exists -- it silently
        // stops counting it, and coverage drops with no failure anywhere.
        "src/components/kokpit/alert-center.tsx",
        "src/components/kokpit/competitive-pulse.tsx",
        "src/components/kokpit/daily-summary.tsx",
        "src/components/kokpit/kpi-strip.tsx",
        "src/components/kokpit/market-pulse-row.tsx",
        "src/components/kokpit/fx-board-table.tsx",
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
