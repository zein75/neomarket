import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3004';
const productId = 'b2a8f451-476a-4d89-a591-6f7e4a2a710e';
const orderId = '8f40be87-cf72-4e78-89ba-9b2fc9ce3f11';

async function captureState(page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, state: string) {
  const evidenceDir = resolve(process.cwd(), process.env.NEOMARKET_SELLER_EVIDENCE_DIR ?? '../../docs/automation/seller_runs/2026-10-18/ui-08-state-truthfulness');
  await mkdir(evidenceDir, { recursive: true });
  await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
  await page.screenshot({ path: resolve(evidenceDir, `${state}-${testInfo.project.name}.png`), fullPage: true });
}

async function useLocalSellerSession(page: import('@playwright/test').Page) {
  // The test server runs with the app's development-only open-access switch.
  // Stub only the browser session read needed to render the shared sign-out UI.
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'ui-state-test', seller_id: '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a', role: 'OWNER' },
  }));
  await page.route('**/api/seller/auth/permissions', (route) => route.fulfill({
    status: 200,
    json: { role: 'OWNER', permissions: ['orders.fulfill'] },
  }));
}

test('product list announces loading, then shows a truthful empty result', async ({ page }, testInfo) => {
  let release!: () => void;
  const responseGate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/api/seller/products?**', async (route) => {
    await responseGate;
    await route.fulfill({ status: 200, json: { items: [], page: { has_more: false } } });
  });
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/products`))?.status()).toBe(200);
  await expect(page.getByRole('status').filter({ hasText: 'Загружаем подтверждённые данные' })).toBeVisible();
  await captureState(page, testInfo, 'products-loading');
  release();
  await expect(page.getByRole('heading', { name: 'Товаров пока нет' })).toBeVisible();
  await expect(page.locator('.seller-app [role="alert"]')).toHaveCount(0);
  await captureState(page, testInfo, 'products-empty');
});

test('orders API failure stays an error with a safe retry, not an empty list', async ({ page }, testInfo) => {
  await page.route('**/api/seller/orders?**', (route) => route.abort('failed'));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/orders`))?.status()).toBe(200);
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toContainText('Не удалось загрузить заказы');
  await expect(alert.getByRole('button', { name: 'Повторить' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Пока нет распределённых заказов' })).toHaveCount(0);
  await expect(alert).not.toContainText('Failed to fetch');
  await captureState(page, testInfo, 'orders-error');
});

test('moderation empty response is distinguished from a failed request', async ({ page }, testInfo) => {
  await page.route('**/api/seller/products?limit=100', (route) => route.fulfill({
    status: 200,
    json: { items: [] },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/moderation`))?.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Совпадений нет' })).toBeVisible();
  await expect(page.locator('.seller-app [role="alert"]')).toHaveCount(0);
  await captureState(page, testInfo, 'moderation-empty');
});

test('product detail failure renders an actionable error instead of stale product content', async ({ page }, testInfo) => {
  await page.route(`**/api/seller/products/${productId}`, (route) => route.fulfill({
    status: 503,
    json: { title: 'Карточка временно недоступна' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/products/${productId}`))?.status()).toBe(200);
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toContainText('Карточка временно недоступна');
  await expect(alert.getByRole('button', { name: 'Reload' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Correct rejected fields' })).toHaveCount(0);
  await captureState(page, testInfo, 'product-detail-error');
});

test('order detail failure does not imply that an allocation was loaded', async ({ page }, testInfo) => {
  await page.route(`**/api/seller/orders/${orderId}`, (route) => route.fulfill({
    status: 503,
    json: { title: 'Заказ временно недоступен' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/orders/${orderId}`))?.status()).toBe(200);
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toContainText('Заказ временно недоступен');
  await expect(alert.getByRole('button', { name: 'Повторить' })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Упаковка' })).toHaveCount(0);
  await captureState(page, testInfo, 'order-detail-error');
});

test('saved shipment renders a localized quantity without claiming delivery or enabling disabled packing', async ({ page }, testInfo) => {
  await page.route(`**/api/seller/orders/${orderId}`, (route) => route.fulfill({
    status: 200,
    json: {
      id: orderId,
      currency: 'RUB',
      status: 'CREATED',
      total_minor: 6000,
      revision: 2,
      allocated_at: '2026-10-18T12:00:00Z',
      seller_accepted_at: '2026-10-18T12:05:00Z',
      items: [{
        id: '34c6b4df-95a6-432c-b480-57afdf4499cf',
        sku_id: 'f61f46ea-8b1c-4773-8706-1faaf91f73e0',
        product_id: '8e9af5f9-f6b7-41a5-8f65-ec5b6480d13a',
        product_title: 'QA product',
        sku_name: 'QA variant',
        quantity: 3,
        unit_price_minor: 2000,
        line_total_minor: 6000,
      }],
      shipments: [{
        id: '12b12f10-6119-4246-88b9-36924c3f8e14',
        status: 'PACKED',
        packed_at: '2026-10-18T12:10:00Z',
        lines: [{ seller_order_item_id: '34c6b4df-95a6-432c-b480-57afdf4499cf', quantity: 1 }],
        carrier_operation: null,
      }],
    },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/orders/${orderId}`))?.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Allocation' })).toBeVisible();
  await expect(page.locator('.seller-orders-table').first()).toContainText('1 шт.');
  await expect(page.getByText('LOCAL TEST')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Упаковать' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Отправить' })).toHaveCount(0);
  await captureState(page, testInfo, 'order-detail-packed');
});

test('dashboard keeps loading visible and reports a metrics failure without showing zero totals', async ({ page }, testInfo) => {
  let release!: () => void;
  const responseGate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/api/seller/products?limit=100&include_skus=true', (route) => route.fulfill({
    status: 200,
    json: { items: [], page: { has_more: false } },
  }));
  await page.route('**/api/seller/dashboard/metrics', async (route) => {
    await responseGate;
    await route.fulfill({ status: 503, json: { title: 'Metrics are temporarily unavailable' } });
  });
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/dashboard`))?.status()).toBe(200);
  await expect(page.locator('.seller-state[role="status"]')).toBeVisible();
  await captureState(page, testInfo, 'dashboard-loading');
  release();
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toContainText('Metrics are temporarily unavailable');
  await expect(alert.getByRole('button')).toBeEnabled();
  await expect(page.locator('.seller-dashboard-metrics')).toHaveCount(0);
  await captureState(page, testInfo, 'dashboard-error');
});

test('inventory empty response is distinct from an API failure', async ({ page }, testInfo) => {
  await page.route('**/api/seller/inventory?**', (route) => route.fulfill({
    status: 200,
    json: { items: [], page: { has_more: false, next_cursor: null } },
  }));
  await page.route('**/api/seller/dashboard/metrics', (route) => route.fulfill({
    status: 200,
    json: { metrics: { sku_count: 0, total_on_hand: 0, reserved_stock: 0, available_stock: 0 }, as_of: '2026-10-18T12:00:00Z' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/inventory`))?.status()).toBe(200);
  await expect(page.locator('.seller-state h2')).toBeVisible();
  await expect(page.locator('.seller-app [role="alert"]')).toHaveCount(0);
  await captureState(page, testInfo, 'inventory-empty');
});

test('SKU request failure stays actionable and does not render the empty state', async ({ page }, testInfo) => {
  await page.route(`**/api/seller/products/${productId}/skus`, (route) => route.fulfill({
    status: 503,
    json: { title: 'SKU data is temporarily unavailable' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/products/${productId}/skus`))?.status()).toBe(200);
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toBeVisible();
  await expect(alert.getByRole('link')).toBeVisible();
  await expect(alert.locator('h2')).toHaveCount(0);
  await captureState(page, testInfo, 'sku-error');
});

test('finance provider gate is explicit and never fabricates zero balances', async ({ page }, testInfo) => {
  await page.route('**/api/seller/finance/overview', (route) => route.fulfill({
    status: 501,
    json: { type: 'about:blank', title: 'Finance provider is not configured', status: 501, code: 'FEATURE_NOT_CONFIGURED' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/finance`))?.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Финансовый провайдер не настроен' })).toBeVisible();
  await expect(page.getByText(/подтверждёнными расчётами/i)).toBeVisible();
  await expect(page.getByText('0 ₽')).toHaveCount(0);
  await captureState(page, testInfo, 'finance-not-configured');
});

test('team failure stays an actionable error and does not render an empty member list', async ({ page }, testInfo) => {
  await page.route('**/api/seller/team/members', (route) => route.fulfill({
    status: 503,
    json: { title: 'Team data is temporarily unavailable' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/team`))?.status()).toBe(200);
  const alert = page.locator('.seller-app [role="alert"]');
  await expect(alert).toContainText('Team data is temporarily unavailable');
  await expect(page.getByText('В команде пока нет участников.')).toHaveCount(0);
  await expect(alert.getByRole('button', { name: 'Обновить' })).toHaveCount(0);
  await captureState(page, testInfo, 'team-error');
});

test('invalid inventory import remains a retryable error without a preview', async ({ page }, testInfo) => {
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'csrf-fixture' } }));
  await page.route('**/api/seller/imports', (route) => route.fulfill({
    status: 503,
    json: { title: 'Import service is temporarily unavailable' },
  }));
  await useLocalSellerSession(page);
  expect((await page.goto(`${seller}/imports`))?.status()).toBe(200);
  await page.locator('input[type="file"]').setInputFiles({ name: 'stock.csv', mimeType: 'text/csv', buffer: Buffer.from('seller_article,on_hand\nSKU-1,4\n') });
  await page.getByRole('button', { name: 'Preview import' }).click();
  await expect(page.locator('.seller-app [role="alert"]')).toContainText('Import service is temporarily unavailable');
  await expect(page.getByRole('heading', { name: 'Dry-run preview' })).toHaveCount(0);
  await captureState(page, testInfo, 'import-error');
});
