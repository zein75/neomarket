import { test, expect } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';

test('seller uploads a verified image and attaches it to a product draft', async ({ page }) => {
  test.setTimeout(120_000);
  await page.route('**/api/seller/categories', async (route) => {
    const response = await route.fetch();
    const payload = await response.json() as { items: Array<Record<string, unknown>> };
    if (payload.items[0]) payload.items[0].attribute_schema = [];
    await route.fulfill({ response, json: payload });
  });
  await page.goto(`${seller}/login?next=%2Fproducts%2Fnew`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.getByRole('button', { name: /Seller Hub/ }).click();
  await expect(page).toHaveURL(/\/products\/new$/);
  const category = page.locator('[name="categoryId"]');
  await expect(category).toBeEnabled();
  await category.selectOption({ index: 1 });
  const tag = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  await page.locator('[name="title"]').fill(`Media integration ${tag}`);
  await page.locator('[name="description"]').fill('Seller media upload and approval integration fixture.');
  await page.locator('[name="media"]').setInputFiles({
    name: 'pixel.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGMUqTjBwMDAxAAGAA9mAViiDh2pAAAAAElFTkSuQmCC', 'base64'),
  });
  const variant = page.locator('.seller-section fieldset').first();
  await variant.locator('input').nth(0).fill(`MEDIA-${tag}`);
  await variant.locator('input').nth(1).fill('Media fixture variant');
  await variant.locator('input').nth(2).fill('125.50');
  await variant.locator('input').nth(3).fill('4');
  const draftRequest = page.waitForRequest((request) => request.url().endsWith('/api/seller/v1/products/drafts') && request.method() === 'POST');
  const draftResponse = page.waitForResponse((response) => response.url().endsWith('/api/seller/v1/products/drafts') && response.request().method() === 'POST');
  await page.locator('.seller-form button[type="submit"]').click();
  const [request, response] = await Promise.all([draftRequest, draftResponse]);
  expect(response.status()).toBe(201);
  const payload = request.postDataJSON() as { media_ids: string[] };
  expect(payload.media_ids).toHaveLength(1);
  expect(payload.media_ids[0]).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(page.getByRole('status').filter({ hasText: 'File verified' })).toBeVisible();
});

test('seller sees a failed security scan and does not create a draft', async ({ page }) => {
  test.setTimeout(120_000);
  await page.route('**/api/seller/categories', async (route) => {
    const response = await route.fetch();
    const payload = await response.json() as { items: Array<Record<string, unknown>> };
    if (payload.items[0]) payload.items[0].attribute_schema = [];
    await route.fulfill({ response, json: payload });
  });
  const uploadId = '8d3f8751-bb99-4abd-9fa7-d5a8c8670a1f';
  await page.route('**/api/seller/media/uploads', (route) => route.fulfill({
    status: 201,
    json: { id: uploadId, upload_url: `${seller}/__seller-media-upload`, state: 'UPLOAD_PENDING' },
  }));
  await page.route('**/__seller-media-upload', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 400));
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/seller/media/uploads/${uploadId}/complete`, (route) => route.fulfill({
    status: 202,
    json: { id: uploadId, state: 'SCANNING', error_code: null, content_type: 'image/png', width: null, height: null },
  }));
  await page.route(`**/api/seller/media/uploads/${uploadId}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 200));
    await route.fulfill({ status: 200, json: { id: uploadId, state: 'REJECTED', error_code: 'MALWARE_DETECTED', content_type: null, width: null, height: null } });
  });
  let draftCreated = false;
  await page.route('**/api/seller/v1/products/drafts', (route) => {
    draftCreated = true;
    return route.fulfill({ status: 201, json: { id: 'unexpected', status: 'DRAFT', variants: [] } });
  });

  await page.goto(`${seller}/login?next=%2Fproducts%2Fnew`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.getByRole('button', { name: /Seller Hub/ }).click();
  await expect(page).toHaveURL(/\/products\/new$/);
  await page.locator('[name="categoryId"]').selectOption({ index: 1 });
  await page.locator('[name="title"]').fill(`Rejected media ${Date.now()}`);
  await page.locator('[name="description"]').fill('A rejected upload must not create a product draft.');
  await page.locator('[name="media"]').setInputFiles({
    name: 'rejected.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGMUqTjBwMDAxAAGAA9mAViiDh2pAAAAAElFTkSuQmCC', 'base64'),
  });
  const variant = page.locator('.seller-section fieldset').first();
  await variant.locator('input').nth(0).fill(`REJECT-${Date.now()}`);
  await variant.locator('input').nth(1).fill('Rejected media fixture');
  await variant.locator('input').nth(2).fill('125.50');
  await variant.locator('input').nth(3).fill('4');
  await page.locator('.seller-form button[type="submit"]').click();
  await expect(page.getByRole('progressbar', { name: 'Upload progress for rejected.png' })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Security scan rejected this file' })).toBeVisible();
  await expect(page.locator('.seller-error[role="alert"]')).toContainText('MALWARE_DETECTED');
  expect(draftCreated).toBe(false);
});
