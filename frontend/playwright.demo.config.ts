import { defineConfig, devices } from "@playwright/test";

/**
 * Demo-profile runner: only e2e/demo-mode.spec.ts.
 *
 * The production build MUST be produced first with the demo environment
 * (for example: NEXT_PUBLIC_DEMO_MODE=1 npm run build), because every
 * NEXT_PUBLIC_* value is inlined into the client bundle at build time.
 * Setting them again at runtime does not change the bundle. This config
 * therefore only starts the already-built server (next start); it never
 * builds and never touches the global setup that calls the backend.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /demo-mode\.spec\.ts/,
  // No globalSetup on purpose: the shared setup resets backend data.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
  webServer: {
    command: "npm run start -- -p 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      NEXT_TELEMETRY_DISABLED: "1",
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});