import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The contract package ships TypeScript source; let Next compile it.
  transpilePackages: ["@echr/contract"],
};

export default nextConfig;
