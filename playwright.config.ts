import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir: "tests", testMatch: "*.spec.ts", timeout: 30000,
  workers: 1, fullyParallel: false,
  use: {baseURL: "http://127.0.0.1:8765", viewport: {width: 1440, height: 960},
    channel: process.env.STUDY_BROWSER_CHANNEL || "chrome", trace: "retain-on-failure", screenshot: "only-on-failure"},
  reporter: [["list"], ["json", {outputFile: "artifacts/browser-results.json"}]],
  webServer: {command: ".venv/bin/python tests/e2e_server.py", url: "http://127.0.0.1:8765/api/health", reuseExistingServer: false, timeout: 20000},
});
