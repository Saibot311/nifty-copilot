import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This folder is the app's root. Without it Next looks upward for a
  // lockfile, finds an unrelated one in the home folder and warns on every
  // request that it was ignored.
  turbopack: { root: path.join(__dirname) },
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
