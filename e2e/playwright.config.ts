import { defineConfig } from "@playwright/test";

const port = process.env.E2E_PORT || "3000";
const baseURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${port}`;
const noWebServer = process.env.E2E_NO_WEBSERVER === "1";
const basicUser = process.env.E2E_BASIC_AUTH_USER || "";
const basicPassword = process.env.E2E_BASIC_AUTH_PASSWORD || "";

export default defineConfig({
  testDir: "./journeys",
  timeout: 180_000,
  workers: 1,
  retries: 0,
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "on",
    video: "on",
    trace: "retain-on-failure",
    ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL as "chromium" | "chrome" | "msedge" }
      : {}),
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.PLAYWRIGHT_NO_SANDBOX === "1"
      ? {
          launchOptions: {
            ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
              ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
              : {}),
            ...(process.env.PLAYWRIGHT_NO_SANDBOX === "1"
              ? { args: ["--no-sandbox", "--disable-dev-shm-usage"] }
              : {}),
          },
        }
      : {}),
    ...(basicUser
      ? { httpCredentials: { username: basicUser, password: basicPassword } }
      : {}),
  },
  ...(noWebServer
    ? {}
    : {
        webServer: {
          command: `npm run start -- --port ${port} --hostname 127.0.0.1`,
          cwd: "../frontend",
          url: `${baseURL}/login`,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      }),
});
