import type { NextConfig } from "next";

const config: NextConfig = {
  // No CORS configuration here on purpose: the tester-facing API is called by
  // the Home Assistant *backend* (aiohttp, server to server), never by a
  // browser, so there is no preflight to satisfy. Auth is the bearer token.
  poweredByHeader: false,
};

export default config;
