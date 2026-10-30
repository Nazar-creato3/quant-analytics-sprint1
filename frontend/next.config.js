/** @type {import('next').NextConfig} */
const apiOrigin = (
  process.env.LANE3_API_PROXY_TARGET ||
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.CI_E2E_HOST_NEXT === "1" ? "http://127.0.0.1:8150" : "http://127.0.0.1:8000")
).replace(/\/$/, "");

const nextConfig = {
  // Host e2e on local-pc: skip standalone copy (OOM / silent next build).
  ...(process.env.CI_E2E_HOST_NEXT === "1" ? {} : { output: "standalone" }),
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts"],
    ...(process.env.CI_E2E_HOST_NEXT === "1" ? { cpus: 1, workerThreads: false } : {}),
  },
  async rewrites() {
    if (process.env.CI_E2E_HOST_NEXT === "1") {
      return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
    }
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-XSS-Protection", value: "1; mode=block" },
        ],
      },
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "public, max-age=0, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      {
        source: "/manifest.json",
        headers: [{ key: "Cache-Control", value: "public, max-age=86400" }],
      },
    ];
  },
};

module.exports = nextConfig;
