import { defineConfig } from "@playwright/test";

/** E2E runs against its own backend (:8100, fresh SQLite) and Vite (:5174); `make dev` stays untouched. */
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 5174;
const python =
  process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python.exe" : "../backend/.venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  timeout: 360_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    // the system Chrome is used, so no browser download is needed
    channel: "chrome",
    locale: "ko-KR",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" ../scripts/e2e_backend.py ${BACKEND_PORT}`,
      url: `http://localhost:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}/ops`,
      env: { VITE_BACKEND_URL: `http://localhost:${BACKEND_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
