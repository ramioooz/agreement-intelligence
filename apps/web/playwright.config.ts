import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  outputDir: "test-results",
  use: {
    baseURL:
      process.env.PLAYWRIGHT_BASE_URL ??
      process.env.WEB_PUBLIC_ORIGIN ??
      "http://127.0.0.1:3000",
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "release",
      testMatch: "public-release.spec.ts",
      workers: 1,
      use: {
        ...devices["Desktop Chrome"],
        screenshot: "only-on-failure",
        trace: "retain-on-failure",
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
