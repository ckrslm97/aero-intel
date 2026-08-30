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
        "src/hooks/*.ts",
        "src/lib/campaigns.ts",
        "src/lib/format.ts",
      ],
    },
  },
});
