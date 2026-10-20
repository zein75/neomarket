import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const xssPayload = '<img src=x onerror="window.__sellerXss=true"><script>window.__sellerXss=true</script>';

test('seller product list renders hostile product text as text, not executable markup', async ({ page }) => {
  await page.route('**/api/seller/products?*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        id: '00000000-0000-4000-8000-000000000001',
        title: xssPayload,
        status: 'ON_MODERATION',
        category: xssPayload,
        deleted: false,
        skus_count: 0,
        total_active_quantity: 0,
        updated_at: '2026-10-17T00:00:00Z',
      }],
      page: { has_more: false, next_cursor: null },
    }),
  }));

  await page.goto(`${seller}/login?next=%2Fproducts`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.locator('#login-form button[type="submit"]').click();
  await expect(page).toHaveURL(`${seller}/products`);
  await expect(page.getByRole('link', { name: xssPayload, exact: true })).toBeVisible();
  await expect(page.locator('tbody img, tbody script')).toHaveCount(0);
  expect(await page.evaluate(() => (window as Window & { __sellerXss?: boolean }).__sellerXss)).toBeUndefined();
});
