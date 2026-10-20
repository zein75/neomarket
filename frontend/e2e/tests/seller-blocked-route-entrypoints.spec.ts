import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3004';

const blockedRoutes = [
  ['onboarding', 'identity'],
  ['analytics', 'агрегаты'],
  ['settings', 'MFA'],
  ['support', 'support'],
  ['returns', 'refund'],
] as const;

async function useLocalSellerSession(page: import('@playwright/test').Page) {
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'blocked-route-test', seller_id: '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a', role: 'OWNER' },
  }));
  await page.route('**/api/seller/auth/permissions', (route) => route.fulfill({
    status: 200,
    json: { role: 'OWNER', permissions: [] },
  }));
}

test('blocked Seller route entrypoints explain unavailable contracts without fabricated data', async ({ page }) => {
  await useLocalSellerSession(page);
  for (const [section, marker] of blockedRoutes) {
    const response = await page.goto(`${seller}/${section}`);
    expect(response?.status(), `/${section} should be a real entrypoint`).toBe(200);
    await expect(page.locator('main.seller-app h1')).toHaveText(section);
    const blocked = page.locator('.seller-blocked');
    await expect(blocked).toBeVisible();
    await expect(blocked.locator('h2')).toHaveText('Данные пока не подключены');
    await expect(blocked).toContainText(marker);
    await expect(blocked.locator('.status-badge')).toHaveText('API CONTRACT PENDING');
    await expect(page.locator('.seller-dashboard-metrics, .seller-table, .seller-card-grid')).toHaveCount(0);
  }
});
