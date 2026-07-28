import type { NextConfig } from "next";

const apiOrigin = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/api/:path*`,
      },
      {
        source: "/translate",
        destination: `${apiOrigin}/translate`,
      },
      {
        source: "/v2/:path*",
        destination: `${apiOrigin}/v2/:path*`,
      },
    ];
  },
};

export default nextConfig;
