import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const require = createRequire(resolve(process.cwd(), 'playwright.config.ts'));
const axePath = require.resolve('axe-core/axe.min.js');
const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3003';
const orderId = '8f40be87-cf72-4e78-89ba-9b2fc9ce3f11';

test('seller order detail fixture is axe-clean', async ({ page }, testInfo) => {
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'ui07-test', seller_id: '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a', role: 'OWNER' },
  }));
  await page.route('**/api/seller/auth/permissions', (route) => route.fulfill({
    status: 200,
    json: { role: 'OWNER', permissions: ['orders.fulfill'] },
  }));
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

  expect((await page.goto(`${seller}/orders/${orderId}`))?.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Allocation' })).toBeVisible();
  await page.addScriptTag({ path: axePath });
  const violations = await page.evaluate(async () => {
    const axe = (window as Window & { axe?: { run: (context: Document, options: unknown) => Promise<{ violations: Array<{ id: string; impact: string | null; help: string; helpUrl: string; nodes: Array<{ target: string[]; failureSummary?: string | null }> }> }> } }).axe;
    if (!axe) throw new Error('axe-core did not load');
    const result = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } });
    return result.violations;
  });
  const evidenceDir = resolve(process.cwd(), '../../docs/automation/seller_runs/2026-10-19/ui-07-order-detail-axe');
  await mkdir(evidenceDir, { recursive: true });
  await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
  await page.screenshot({ path: resolve(evidenceDir, `order-detail-axe-${testInfo.project.name}.png`), fullPage: true });
  await writeFile(resolve(evidenceDir, `order-detail-axe-${testInfo.project.name}.json`), JSON.stringify({ project: testInfo.project.name, viewport: page.viewportSize(), violations }, null, 2));
  expect(violations).toEqual([]);
});
