/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const apiBase = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${apiBase}/api/:path*` }];
  }
};
module.exports = nextConfig;
