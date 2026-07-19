import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the production Docker image (see Dockerfile) -- a
  // self-contained server bundle for `node server.js`. Vercel builds through its
  // own output pipeline and does NOT serve a standalone bundle, so setting it
  // there makes every route 404. Vercel sets VERCEL=1 at build time; opt out then.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),

  // lucide-react resolves ~1,500 modules per cold route compile without this;
  // it costs dev-server time on every route change.
  experimental: {
    optimizePackageImports: ["lucide-react", "echarts-for-react"],
  },

  async headers() {
    return [
      {
        // The world outline is a static asset that only changes when we
        // regenerate it, and it is fetched the moment the map opens.
        source: "/geo/:file*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
    ];
  },
};

export default nextConfig;
