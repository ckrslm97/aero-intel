import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the production Docker image (see Dockerfile) -- a
  // self-contained server bundle for `node server.js`. Vercel builds through its
  // own output pipeline and does NOT serve a standalone bundle, so setting it
  // there makes every route 404. Vercel sets VERCEL=1 at build time; opt out then.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
};

export default nextConfig;
