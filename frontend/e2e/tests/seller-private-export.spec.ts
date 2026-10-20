import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';

test('anonymous clients cannot read the Seller data used to generate private exports', async ({ page }) => {
  const privateDataPaths = [
    '/api/seller/dashboard/metrics',
    '/api/seller/products?limit=20',
    '/api/seller/inventory?limit=20',
  ];

  for (const path of privateDataPaths) {
    const response = await page.request.get(`${seller}${path}`);
    expect(response.status(), `${path} must reject anonymous reads`).toBe(401);
    expect(response.headers()['cache-control']).toContain('no-store');
  }

  await page.goto(`${seller}/dashboard`);
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.locator('body')).not.toContainText(/Export CSV|Экспорт CSV/);
});
