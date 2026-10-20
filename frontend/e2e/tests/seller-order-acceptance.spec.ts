import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

test('commercial order actions stay disabled pending ADR and existing test shipments remain read-only', async ({ page }) => {
  const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
  const orderId = randomUUID();
  const itemId = randomUUID();
  const shipmentId = randomUUID();
  const writes: string[] = [];
  let readRequestId = '';
  await page.route(`**/api/seller/orders/${orderId}`, (route) => {
    readRequestId = route.request().headers()['x-request-id'] ?? '';
    return route.fulfill({ json: {
    id: orderId,
    currency: 'RUB',
    status: 'CREATED',
    total_minor: 2598,
    revision: 2,
    allocated_at: '2026-10-16T17:00:00Z',
    seller_accepted_at: null,
    items: [{ id: itemId, sku_id: randomUUID(), product_id: randomUUID(), product_title: 'Test coffee', sku_name: 'Box of 2', quantity: 2, unit_price_minor: 1299, line_total_minor: 2598 }],
    shipments: [{
      id: shipmentId,
      status: 'PACKED',
      packed_at: '2026-10-16T17:02:00Z',
      lines: [{ seller_order_item_id: itemId, quantity: 1 }],
      carrier_operation: { provider: 'LOCAL_TEST', status: 'LABEL_CREATED', tracking_number: 'SIM-0123456789ABCDEF', attempts: 1, last_error: null },
    }],
    } });
  });
  await page.route(`**/api/seller/orders/${orderId}/**`, async (route) => {
    writes.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    await route.fulfill({ status: 503, json: { code: 'COMMERCIAL_FLOW_DISABLED' } });
  });

  await page.goto(`${seller}/orders/${orderId}`);
  await expect(page.getByRole('heading', { name: 'Allocation' })).toBeVisible();
  await expect(page.getByText('Приёмка заказов, упаковка, отправка, возвраты, refund/restock и расчёты отключены до утверждения ADR.')).toBeVisible();
  await expect(page.getByRole('button', { name: /приём|упаков|накладн|отправ/i })).toHaveCount(0);
  await expect(page.getByText('Сохранённые тестовые записи посылок (только просмотр)')).toBeVisible();
  await expect(page.getByText('LOCAL TEST ONLY · не подтверждает реальную доставку')).toBeVisible();
  await expect(page.getByText('SIM-0123456789ABCDEF')).toBeVisible();
  expect(writes).toEqual([]);
  expect(readRequestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test('cancelled allocation remains a read-only snapshot', async ({ page }) => {
  const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
  const orderId = randomUUID();
  await page.route(`**/api/seller/orders/${orderId}`, (route) => route.fulfill({ json: {
    id: orderId,
    currency: 'RUB',
    status: 'CANCELLED',
    total_minor: 500,
    revision: 3,
    allocated_at: '2026-10-16T17:00:00Z',
    seller_accepted_at: '2026-10-16T17:01:00Z',
    items: [{ id: randomUUID(), sku_id: randomUUID(), product_id: randomUUID(), product_title: 'Cancelled tea', sku_name: 'Box', quantity: 2, unit_price_minor: 250, line_total_minor: 500 }],
    shipments: [],
  } }));
  await page.goto(`${seller}/orders/${orderId}`);
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible();
  await expect(page.getByText(/отключены до утверждения ADR/)).toBeVisible();
  await expect(page.getByRole('button', { name: /приём|упаков|накладн|отправ/i })).toHaveCount(0);
});

test('Seller BFF blocks acceptance, packing and dispatch before contacting B2B', async ({ page }) => {
  const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
  const orderId = randomUUID();
  const shipmentId = randomUUID();
  await page.goto(seller);
  const responses = await page.evaluate(async ({ orderId, shipmentId }) => {
    document.cookie = 'nm_seller_access=local-disabled-flow-check; path=/; sameSite=lax';
    const csrfResponse = await fetch('/api/seller/auth/csrf', { cache: 'no-store' });
    const { token } = await csrfResponse.json() as { token: string };
    const idempotencyKey = crypto.randomUUID();
    const requests: Array<[string, RequestInit]> = [
      [`/api/seller/orders/${orderId}/accept`, { method: 'POST' }],
      [`/api/seller/orders/${orderId}/shipments`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey, 'Content-Type': 'application/json' }, body: JSON.stringify({ lines: [] }) }],
      [`/api/seller/orders/${orderId}/shipments/${shipmentId}/dispatch`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey } }],
    ];
    return Promise.all(requests.map(async ([path, init]) => {
      const response = await fetch(path, { ...init, headers: { ...init.headers, 'X-CSRF-Token': token }, cache: 'no-store' });
      return { status: response.status, body: await response.json() as { code?: string; flow?: string } };
    }));
  }, { orderId, shipmentId });
  expect(responses.map(({ status, body }) => [status, body.code, body.flow])).toEqual([
    [503, 'COMMERCIAL_FLOW_DISABLED', 'seller_order_acceptance'],
    [503, 'COMMERCIAL_FLOW_DISABLED', 'seller_packing_manifest'],
    [503, 'COMMERCIAL_FLOW_DISABLED', 'seller_carrier_dispatch'],
  ]);
});

test('order detail rejects a malformed successful B2B snapshot', async ({ page }) => {
  const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
  const orderId = randomUUID();
  await page.route(`**/api/seller/orders/${orderId}`, (route) => route.fulfill({ json: { id: orderId, status: 'CREATED' } }));
  await page.goto(`${seller}/orders/${orderId}`);
  await expect(page.locator('.seller-error[role="alert"]')).toBeVisible();
  await expect(page.locator('.seller-order-summary')).toHaveCount(0);
});
