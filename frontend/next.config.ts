import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the production Docker image (see Dockerfile).
  output: "standalone",
};

export default nextConfig;
