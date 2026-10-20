import { expect, test, type Page } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const categoriesFallback = '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438.';

async function login(page: Page, next: string) {
  await page.goto(`${seller}/login?next=${encodeURIComponent(next)}`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.locator('#login-form button[type="submit"]').click();
  await expect(page).toHaveURL(`${seller}${next}`);
}

test('inventory network failures show a retryable message, not a browser exception', async ({ page }) => {
  await page.route('**/api/seller/inventory**', (route) => route.abort('failed'));
  await login(page, '/inventory');
  const alert = page.locator('.seller-state.seller-error[role="alert"]');
  await expect(alert).toContainText('Unable to load inventory');
  await expect(alert).not.toContainText('Failed to fetch');
  await expect(alert.getByRole('button', { name: 'Повторить' })).toBeEnabled();
});

test('category network failures show a localized message and disable draft creation', async ({ page }) => {
  await page.route('**/api/seller/categories', (route) => route.abort('failed'));
  await login(page, '/products/new');
  const alert = page.locator('.seller-state.seller-error[role="alert"]');
  await expect(alert).toContainText(categoriesFallback);
  await expect(alert).not.toContainText('Failed to fetch');
  await expect(alert.getByRole('button', { name: 'Повторить' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Сохранить черновик' })).toBeDisabled();
});
