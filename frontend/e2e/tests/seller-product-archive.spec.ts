import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3010';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';

test('seller archives a product from its detail page', async ({ page }) => {
  const tag = randomUUID().slice(0, 8);
  await page.goto(`${seller}/login?next=%2Fproducts%2Fnew`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.locator('#login-form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/products\/new$/);

  await page.locator('[name="categoryId"]').selectOption({ index: 1 });
  await page.locator('[name="title"]').fill(`Archive fixture ${tag}`);
  await page.locator('[name="description"]').fill('Disposable product used to verify seller archive flow.');
  const variant = page.locator('.seller-section fieldset').first();
  await variant.locator('input').nth(0).fill(`ARCH-${tag}`);
  await variant.locator('input').nth(1).fill(`Archive SKU ${tag}`);
  await variant.locator('input').nth(2).fill('12.99');
  await variant.locator('input').nth(3).fill('2');
  const draftResponse = page.waitForResponse((response) => response.url().endsWith('/api/seller/v1/products/drafts') && response.request().method() === 'POST');
  await page.locator('.seller-form button[type="submit"]').click();
  const created = await draftResponse;
  expect(created.status()).toBe(201);
  const productId = (await created.json() as { id: string }).id;
  await page.getByRole('link', { name: 'Открыть карточку' }).click();
  await expect(page).toHaveURL(new RegExp(`/products/${productId}$`));

  page.once('dialog', (dialog) => dialog.accept());
  const archive = page.waitForResponse((response) => response.url().endsWith(`/api/seller/products/${productId}`) && response.request().method() === 'DELETE');
  await page.getByRole('button', { name: 'Archive product' }).click();
  expect((await archive).status()).toBe(202);
  await expect(page).toHaveURL(/\/products\?archived=1$/);
});
