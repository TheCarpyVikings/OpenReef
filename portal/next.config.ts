import type { NextConfig } from "next";

const config: NextConfig = {
  // No CORS configuration here on purpose: the tester-facing API is called by
  // the Home Assistant *backend* (aiohttp, server to server), never by a
  // browser, so there is no preflight to satisfy. Auth is the bearer token.
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/(.*)",
      headers: [
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
  // /agreement and /privacy read content/*.md with fs at request time; make
  // sure the tracer bundles those files into the serverless output.
  outputFileTracingIncludes: {
    "/agreement": ["./content/**"],
    "/privacy": ["./content/**"],
    "/welcome": ["./content/**"],
  },
};

export default config;
