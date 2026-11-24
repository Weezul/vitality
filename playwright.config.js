import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/frontend",
  use: {
    browserName: "chromium",
    launchOptions: process.env.VITALITY_BROWSER
      ? { executablePath: process.env.VITALITY_BROWSER } : {},
  },
});
