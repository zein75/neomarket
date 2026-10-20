import { defineConfig, devices } from '@playwright/test';

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR ?? 'test-results';
const htmlReportDir = process.env.PLAYWRIGHT_HTML_OUTPUT_DIR ?? 'playwright-report';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  outputDir,
  expect: { timeout: 5_000 },
  reporter: [['list'], ['html', { outputFolder: htmlReportDir, open: 'never' }]],
  use: {
    ...devices['Desktop Chrome'],
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'tablet-chromium',
      use: { ...devices['Galaxy Tab S4'], browserName: 'chromium' },
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 5'], browserName: 'chromium' },
    },
  ],
});
