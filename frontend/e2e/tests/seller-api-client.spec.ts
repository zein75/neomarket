import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3004';

async function useLocalSellerSession(page: import('@playwright/test').Page) {
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'seller-api-client-test', seller_id: '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a', role: 'OWNER' },
  }));
}

test('typed Seller API client retries only the transient read and keeps one request ID', async ({ page }) => {
  const requestIds: string[] = [];
  let attempts = 0;
  await page.route('**/api/seller/products?**', async (route) => {
    requestIds.push(route.request().headers()['x-request-id'] ?? '');
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/problem+json',
        body: JSON.stringify({ type: 'about:blank', title: 'Seller service is unavailable', status: 503, code: 'DEPENDENCY_UNAVAILABLE' }),
      });
      return;
    }
    await route.fulfill({ status: 200, json: { items: [], page: { has_more: false } } });
  });
  await useLocalSellerSession(page);
  await page.goto(`${seller}/products`);

  await expect(page.getByRole('heading', { name: 'Товаров пока нет' })).toBeVisible();
  expect(attempts).toBe(2);
  expect(requestIds).toHaveLength(2);
  expect(requestIds[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(requestIds[1]).toBe(requestIds[0]);
});

test('typed Seller API client rejects a successful response that violates its runtime schema', async ({ page }) => {
  await page.route('**/api/seller/products?**', (route) => route.fulfill({
    status: 200,
    json: { items: { unexpected: true }, page: { has_more: false } },
  }));
  await useLocalSellerSession(page);
  await page.goto(`${seller}/products`);

  await expect(page.locator('.seller-app [role="alert"]')).toContainText('Seller API вернул данные неверного формата');
  await expect(page.getByRole('heading', { name: 'Товаров пока нет' })).toHaveCount(0);
});

test('dashboard decodes the current B2B product page and server metrics', async ({ page }) => {
  await page.route('**/api/seller/products?limit=100&include_skus=true', (route) => route.fulfill({
    status: 200,
    json: {
      items: [{
        id: '5dd6739d-5829-4aa7-a681-2a035a98586b', title: 'Складской товар', category: null, images: [], status: 'APPROVED',
        is_active: true, deleted: false, skus_count: 1, total_active_quantity: 7,
        skus: [{
          id: 'a39b9fc2-e7bf-4b9e-b16a-20f8d13a36af', product_id: '5dd6739d-5829-4aa7-a681-2a035a98586b', name: 'Стандартный',
          article: null, images: [], stock_quantity: 9, active_quantity: 7, reserved_quantity: 2, is_active: true,
        }],
      }],
      total_count: 101,
      limit: 100,
      offset: 0,
    },
  }));
  await page.route('**/api/seller/dashboard/metrics', (route) => route.fulfill({
    status: 200,
    json: { as_of: '2026-10-19T08:00:00Z', metrics: { live_products: 99, sku_count: 150, total_on_hand: 300, available_stock: 250, pending_moderation: 3, reserved_stock: 50 }, definitions: {} },
  }));
  await useLocalSellerSession(page);
  await page.goto(`${seller}/dashboard`);

  await expect(page.getByRole('rowheader').getByText('Складской товар', { exact: true })).toBeVisible();
  await expect(page.getByText('Обзор показывает первые 100 товаров.')).toBeVisible();
  await expect(page.locator('.seller-dashboard-metrics').getByText('250', { exact: true })).toBeVisible();
});

test('inventory list and summary decode their typed response shapes', async ({ page }) => {
  await page.route('**/api/seller/inventory?**', (route) => route.fulfill({
    status: 200,
    json: {
      items: [{ sku_id: 'a39b9fc2-e7bf-4b9e-b16a-20f8d13a36af', product_id: '5dd6739d-5829-4aa7-a681-2a035a98586b', product_title: 'Складской товар', sku_name: 'Стандартный', seller_article: null, stock_quantity: 9, reserved_quantity: 2, active_quantity: 7, is_active: true, revision: 4 }],
      page: { has_more: false, next_cursor: null },
    },
  }));
  await page.route('**/api/seller/dashboard/metrics', (route) => route.fulfill({
    status: 200,
    json: { as_of: '2026-10-19T08:00:00Z', metrics: { sku_count: 1, total_on_hand: 9, reserved_stock: 2, available_stock: 7 }, definitions: {} },
  }));
  await useLocalSellerSession(page);
  await page.goto(`${seller}/inventory`);

  await expect(page.getByRole('heading', { name: 'Стандартный' })).toBeVisible();
  await expect(page.getByText('На складе').first()).toBeVisible();
  await expect(page.getByText('9', { exact: true }).first()).toBeVisible();
});

test('product creation decodes seller context and submits one correlated draft mutation', async ({ page }) => {
  const organizationId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const categoryId = 'e2e3e554-b222-4cad-a8a7-9f2586c35a7e';
  const draftId = 'd8e96f56-13f9-4d69-9015-7bd25495df1e';
  const mediaId = 'bdf271a2-a755-4c5f-aa49-924e0488de19';
  const mutationRequests: Array<{ requestId: string; idempotencyKey: string }> = [];
  let uploadRequestId = '';
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({
    status: 200,
    json: [{ id: organizationId, company_name: 'Local seller', role: 'OWNER', current: true }],
  }));
  await page.route('**/api/seller/categories', (route) => route.fulfill({
    status: 200,
    json: { items: [{ id: categoryId, name: 'Local category', slug: 'local-category', parent_id: null, is_active: true, attribute_schema: [], revision: 1 }] },
  }));
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-csrf-token' } }));
  await page.route('**/api/seller/media/uploads', (route) => route.fulfill({
    status: 201,
    json: { id: mediaId, upload_url: `${seller}/__seller-media-upload`, expires_at: '2026-10-19T12:00:00Z', state: 'UPLOAD_PENDING' },
  }));
  await page.route('**/__seller-media-upload', async (route) => {
    uploadRequestId = route.request().headers()['x-request-id'] ?? '';
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/seller/media/uploads/${mediaId}/complete`, (route) => route.fulfill({
    status: 202,
    json: { id: mediaId, state: 'SCANNING', error_code: null, content_type: 'image/png', width: 2, height: 2 },
  }));
  await page.route(`**/api/seller/media/uploads/${mediaId}`, (route) => route.fulfill({
    status: 200,
    json: { id: mediaId, state: 'READY', error_code: null, content_type: 'image/png', width: 2, height: 2 },
  }));
  await page.route('**/api/seller/v1/products/drafts', async (route) => {
    const headers = route.request().headers();
    mutationRequests.push({ requestId: headers['x-request-id'] ?? '', idempotencyKey: headers['idempotency-key'] ?? '' });
    expect((route.request().postDataJSON() as { media_ids: string[] }).media_ids).toEqual([mediaId]);
    await route.fulfill({ status: 201, json: { id: draftId, revision: 1, status: 'DRAFT', operation_id: '4f3662ad-fbf6-4ed0-878a-cf8acb116809', variants: [{ id: 'afea35ca-4f5e-4fc6-938c-bd1a66164c52', seller_article: 'E2E-1', name: 'Local SKU', price_minor: 12550, currency: 'RUB', on_hand: 4, options: {} }] } });
  });
  await useLocalSellerSession(page);
  await page.goto(`${seller}/products/new`);
  await expect(page.locator('select[name="categoryId"]')).toBeEnabled();
  await page.locator('select[name="categoryId"]').selectOption(categoryId);
  await page.locator('input[name="title"]').fill('Typed product draft');
  await page.locator('textarea[name="description"]').fill('Created through the typed Seller API client.');
  await page.locator('input[name="media"]').setInputFiles({ name: 'product.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGMUqTjBwMDAxAAGAA9mAViiDh2pAAAAAElFTkSuQmCC', 'base64') });
  const variant = page.locator('.seller-section fieldset').first();
  await variant.locator('input').nth(0).fill('E2E-1');
  await variant.locator('input').nth(1).fill('Local SKU');
  await variant.locator('input').nth(2).fill('125.50');
  await variant.locator('input').nth(3).fill('4');
  await page.locator('form button[type="submit"]').click();

  await expect(page.locator(`a[href="/products/${draftId}"]`)).toBeVisible();
  expect(mutationRequests).toHaveLength(1);
  expect(mutationRequests[0]?.requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(mutationRequests[0]?.idempotencyKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(uploadRequestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test('inventory import validates preview and commit responses and preserves mutation keys', async ({ page }) => {
  const jobId = 'c905439a-0fe7-42f0-bbbb-967ebc7efab7';
  const mutationRequests: Array<{ method: string; requestId: string; idempotencyKey: string }> = [];
  const row = (state: 'VALID' | 'APPLIED') => ({ row_number: 0, seller_article: 'IMPORT-1', target_on_hand: 7, before_on_hand: 4, delta: 3, state, error_code: null, error_message: null, result_on_hand: state === 'APPLIED' ? 7 : null });
  const job = (state: 'PREVIEWED' | 'COMMITTED') => ({ id: jobId, mode: 'COUNT', source_sha256: 'a'.repeat(64), state, total_rows: 1, valid_rows: 1, error_rows: 0, applied_rows: state === 'COMMITTED' ? 1 : 0, committed_at: state === 'COMMITTED' ? '2026-10-19T07:00:00Z' : null, rows: [row(state === 'COMMITTED' ? 'APPLIED' : 'VALID')] });
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-csrf-token' } }));
  await page.route('**/api/seller/imports', async (route) => {
    const headers = route.request().headers();
    mutationRequests.push({ method: route.request().method(), requestId: headers['x-request-id'] ?? '', idempotencyKey: headers['idempotency-key'] ?? '' });
    await route.fulfill({ status: 201, json: job('PREVIEWED') });
  });
  await page.route(`**/api/seller/imports/${jobId}`, async (route) => {
    const headers = route.request().headers();
    mutationRequests.push({ method: route.request().method(), requestId: headers['x-request-id'] ?? '', idempotencyKey: headers['idempotency-key'] ?? '' });
    await route.fulfill({ status: 200, json: job('COMMITTED') });
  });
  await useLocalSellerSession(page);
  await page.goto(`${seller}/imports`);
  await page.locator('input[type="file"]').setInputFiles({ name: 'count.csv', mimeType: 'text/csv', buffer: Buffer.from('seller_article,on_hand\nIMPORT-1,7\n') });
  await page.getByRole('button', { name: 'Preview import' }).click();
  await expect(page.getByRole('heading', { name: 'Dry-run preview' })).toBeVisible();
  await page.getByRole('button', { name: 'Commit valid rows' }).click();
  await expect(page.getByRole('heading', { name: 'Import result' })).toBeVisible();
  expect(mutationRequests).toHaveLength(2);
  for (const request of mutationRequests) {
    expect(request.requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(request.idempotencyKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  }
  expect(mutationRequests[0]?.method).toBe('POST');
  expect(mutationRequests[1]?.method).toBe('POST');
});

test('tenant switch validates organization and session responses and reloads into the new tenant', async ({ page }) => {
  const organizationA = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const organizationB = 'c905439a-0fe7-42f0-bbbb-967ebc7efab7';
  let currentOrganization = organizationA;
  const switchRequestIds: string[] = [];
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({
    status: 200,
    json: [
      { id: organizationA, company_name: 'Organization A', role: 'SUPPORT', current: currentOrganization === organizationA },
      { id: organizationB, company_name: 'Organization B', role: 'FINANCE', current: currentOrganization === organizationB },
    ],
  }));
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-csrf-token' } }));
  await page.route('**/api/seller/auth/switch-tenant', async (route) => {
    switchRequestIds.push(route.request().headers()['x-request-id'] ?? '');
    currentOrganization = (route.request().postDataJSON() as { seller_id: string }).seller_id;
    await route.fulfill({ status: 200, json: { ok: true } });
  });
  await page.route('**/api/seller/products?**', (route) => route.fulfill({ status: 200, json: { items: [], page: { has_more: false } } }));
  await page.route('**/api/seller/dashboard/metrics', (route) => route.fulfill({ status: 200, json: { as_of: '2026-10-19T07:00:00Z', metrics: { live_products: 0, sku_count: 0, total_on_hand: 0, available_stock: 0, pending_moderation: 0, reserved_stock: 0 }, definitions: {} } }));
  await useLocalSellerSession(page);
  await page.goto(`${seller}/dashboard`);
  await expect(page.locator('#seller-tenant-select')).toHaveValue(organizationA);
  await page.locator('#seller-tenant-select').selectOption(organizationB);
  await page.locator('.seller-tenant-switcher button').click();
  await expect.poll(() => page.locator('#seller-tenant-select').inputValue()).toBe(organizationB);
  expect(switchRequestIds).toHaveLength(1);
  expect(switchRequestIds[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test('product detail validates moderation data and handles revision update plus accepted archive', async ({ page }) => {
  const productId = 'd8e96f56-13f9-4d69-9015-7bd25495df1e';
  const sellerId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const requestIds: Array<{ method: string; requestId: string; ifMatch: string | null }> = [];
  const product = (status: 'BLOCKED' | 'ON_MODERATION', revision: number) => ({
    id: productId, seller_id: sellerId, title: 'Reviewable product', description: 'Server approved description', category_id: null, brand_id: null,
    slug: 'reviewable-product', images: [], characteristics: [{ name: 'material', value: 'steel' }], status, blocking_reason_id: null,
    moderator_comment: null, created_at: '2026-10-18T12:00:00Z', updated_at: '2026-10-19T07:00:00Z', revision, deleted: false,
    skus: [], blocked: status === 'BLOCKED', blocking_reason: null,
    field_reports: status === 'BLOCKED' ? [{ field_name: 'description', field_path: '/description', reason_code: 'DESCRIPTION_MISMATCH', sku_id: null, comment: 'Clarify the product description.' }] : [],
  });
  await page.route(`**/api/seller/products/${productId}`, async (route) => {
    const method = route.request().method();
    const headers = route.request().headers();
    if (method === 'GET') {
      await route.fulfill({ status: 200, json: product('BLOCKED', 4) });
      return;
    }
    requestIds.push({ method, requestId: headers['x-request-id'] ?? '', ifMatch: headers['if-match'] ?? null });
    if (method === 'PUT') {
      await route.fulfill({ status: 200, json: product('ON_MODERATION', 5) });
      return;
    }
    await route.fulfill({ status: 202, contentType: 'application/json', body: 'null' });
  });
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-csrf-token' } }));
  await useLocalSellerSession(page);
  await page.goto(`${seller}/products/${productId}`);
  await expect(page.getByText('Clarify the product description.')).toBeVisible();
  await page.getByRole('button', { name: 'Submit corrections for review' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Corrections saved. The new revision was sent for moderation.' })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Archive product' }).click();
  await page.waitForURL('**/products?archived=1');
  expect(requestIds).toHaveLength(2);
  expect(requestIds.map(({ method }) => method)).toEqual(['PUT', 'DELETE']);
  expect(requestIds[0]?.ifMatch).toBe('"4"');
  for (const request of requestIds) expect(request.requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});
