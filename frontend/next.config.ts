import type { NextConfig } from "next";

const config: NextConfig = {
  // A self-contained server bundle: the runtime image copies .next/standalone
  // and needs no node_modules of its own.
  output: "standalone",
  reactStrictMode: true,
  // The page reads live factory state on every request; nothing here is
  // cacheable, and a stale machine status strip would be worse than none.
  poweredByHeader: false,
};

export default config;
