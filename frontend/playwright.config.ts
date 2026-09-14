import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the running stack — the real backend, the real
 * database and the local model, through the real interface.
 *
 * They are slow by nature: on CPU every answered question is two model calls,
 * tens of seconds each. So they run one at a time, with timeouts sized to the
 * model rather than to a web page, and they are a separate command
 * (`make web-e2e`) rather than part of `npm test`.
 *
 *   E2E_BASE_URL   the web interface   (default http://localhost:3000)
 *   E2E_API_URL    the backend, for ground truth (default http://localhost:8000)
 *   E2E_CHROME     a Chrome/Chromium binary to use instead of Playwright's own
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 10 * 60_000,
  // Page assertions are quick; waiting for a model run is the helpers' job.
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
        launchOptions: process.env.E2E_CHROME ? { executablePath: process.env.E2E_CHROME } : {},
      },
    },
  ],
});
