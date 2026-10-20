import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const adjustmentPath = '**/api/seller/skus/*/stock-adjustments';

test('seller recovers a committed stock change after its response is lost without submitting twice', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  let committed = false;
  let idempotencyKey = '';
  let skuId = '';
  let originalOnHand = 0;
  let firstPostCount = 0;

  await page.route(adjustmentPath, async (route) => {
    firstPostCount += 1;
    idempotencyKey = route.request().headers()['idempotency-key'] ?? '';
    const response = await route.fetch();
    if (response.status() === 200) {
      const result = await response.json() as { stock_quantity?: number };
      committed = result.stock_quantity === originalOnHand + 1;
    }
    await route.fulfill({ status: 503, json: { title: 'Acknowledgement was lost after commit' } });
  });

  try {
    await page.goto(`${seller}/login?next=%2Finventory`);
    await page.locator('#seller-email').fill(email);
    await page.locator('#seller-password').fill(password);
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/inventory$/);

    const card = page.locator('.inventory-card').first();
    await expect(card).toBeVisible();
    const inventoryItem = await page.evaluate(async () => {
      const response = await fetch('/api/seller/inventory?limit=50', { cache: 'no-store' });
      if (!response.ok) throw new Error(`inventory request failed: ${response.status}`);
      const payload = await response.json() as { items: Array<{ sku_id: string; stock_quantity: number; sku_name: string }> };
      return payload.items[0];
    });
    expect(inventoryItem).toBeTruthy();
    skuId = inventoryItem.sku_id;
    originalOnHand = inventoryItem.stock_quantity;
    const skuName = (await card.locator('h2').innerText()).trim();
    const reason = `UI-11 ${Date.now()}`;
    await card.locator('input[name="delta"]').fill('1');
    await card.locator('input[name="reason"]').fill(reason);

    const statusResponsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/seller/inventory/adjustments/') && response.request().method() === 'GET');
    await card.locator('button[type="submit"]').click();
    const statusResponse = await statusResponsePromise;
    expect(statusResponse.status()).toBe(200);
    const status = await page.evaluate(async (key) => {
      const response = await fetch(`/api/seller/inventory/adjustments/${key}`, { cache: 'no-store' });
      return { httpStatus: response.status, operation: await response.json() as { status: string; sku_id: string; delta: number; on_hand: number } };
    }, idempotencyKey);
    expect(status.httpStatus).toBe(200);
    expect(status.operation).toMatchObject({ status: 'COMMITTED', sku_id: skuId, delta: 1, on_hand: originalOnHand + 1 });
    expect(idempotencyKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(committed).toBe(true);
    expect(firstPostCount).toBe(1);
    await expect(page.getByRole('status').filter({ hasText: `Server confirmed stock for ${skuName}` })).toBeVisible();

    await page.reload();
    await expect(page.locator('.inventory-card').first().locator('dl dd').first()).toHaveText(String(originalOnHand + 1));
    const viewportName = testInfo.project.name.replace(/-chromium$/, '');
    await page.screenshot({
      path: resolve(process.cwd(), `../docs/automation/seller_runs/2026-10-18/ui-11-timeout-recovery/evidence/stock-confirmed-${viewportName}.png`),
    });
  } finally {
    if (!page.isClosed()) await page.unroute(adjustmentPath);
    if (!page.isClosed() && committed && skuId) {
      const cleanup = await page.evaluate(async (targetSkuId) => {
        const csrfResponse = await fetch('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' });
        const csrf = await csrfResponse.json() as { token?: string };
        if (!csrfResponse.ok || !csrf.token) return { status: csrfResponse.status, stock_quantity: null };
        const response = await fetch(`/api/seller/skus/${targetSkuId}/stock-adjustments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token, 'Idempotency-Key': crypto.randomUUID() },
          body: JSON.stringify({ delta: -1, reason: 'UI-11 fixture cleanup' }),
        });
        const result = await response.json() as { stock_quantity?: number };
        return { status: response.status, stock_quantity: result.stock_quantity ?? null };
      }, skuId);
      expect(cleanup, 'cleanup must restore the original shared QA SKU quantity').toEqual({ status: 200, stock_quantity: originalOnHand });
    }
  }
});

test('seller keeps an unresolved stock operation key and does not claim it succeeded', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const postedKeys: string[] = [];
  await page.route(adjustmentPath, async (route) => {
    postedKeys.push(route.request().headers()['idempotency-key'] ?? '');
    await route.fulfill({ status: 503, json: { title: 'Adjustment acknowledgement unavailable' } });
  });
  await page.route('**/api/seller/inventory/adjustments/*', (route) => route.fulfill({
    status: 200,
    json: { status: 'PENDING' },
  }));

  await page.goto(`${seller}/login?next=%2Finventory`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  await page.locator('#login-form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/inventory$/);
  const card = page.locator('.inventory-card').first();
  await expect(card).toBeVisible();
  const reason = `UI-11 pending ${Date.now()}`;
  await card.locator('input[name="delta"]').fill('1');
  await card.locator('input[name="reason"]').fill(reason);

  await card.locator('button[type="submit"]').click();
  await expect(page.locator('.seller-error[role="alert"]')).toContainText('operation key will be reused');
  await expect(page.getByRole('status').filter({ hasText: 'Server confirmed stock' })).toHaveCount(0);
  const keyAfterFirstAttempt = postedKeys[0];
  expect(keyAfterFirstAttempt).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

  await card.locator('button[type="submit"]').click();
  await expect(page.locator('.seller-error[role="alert"]')).toContainText('operation key will be reused');
  expect(postedKeys).toHaveLength(2);
  expect(postedKeys[1]).toBe(keyAfterFirstAttempt);
  const viewportName = testInfo.project.name.replace(/-chromium$/, '');
  await page.screenshot({
    path: resolve(process.cwd(), `../docs/automation/seller_runs/2026-10-18/ui-11-timeout-recovery/evidence/stock-status-unknown-${viewportName}.png`),
  });
});
