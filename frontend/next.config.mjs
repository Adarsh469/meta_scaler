/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for the standalone Docker image (copies only the minimum needed files)
  output: "standalone",

  // Proxy /api/* → backend so the browser never needs to know the backend URL.
  // In Docker the frontend container speaks to http://backend:7860 internally,
  // while the browser just calls the same host it loaded the page from.
  async rewrites() {
    const backendUrl =
      process.env.BACKEND_URL ||          // Server-side env (Docker internal)
      process.env.NEXT_PUBLIC_API_URL ||  // Fallback for local dev
      "http://localhost:7860";

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
