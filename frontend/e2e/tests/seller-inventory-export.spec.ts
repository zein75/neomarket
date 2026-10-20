import { expect, test } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3004';
const jobId = 'e94bf56a-f4c8-488e-8aca-eaa81bf3908c';
const sellerId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';

async function useSellerSession(page: import('@playwright/test').Page) {
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'inventory-export-ui', seller_id: sellerId, role: 'OWNER' },
  }));
  await page.route('**/api/seller/auth/permissions', (route) => route.fulfill({
    status: 200,
    json: { role: 'OWNER', permissions: ['inventory.read', 'inventory.adjust'] },
  }));
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({
    status: 200,
    json: { token: 'inventory-export-csrf' },
  }));
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({
    status: 200,
    json: [{ id: sellerId, company_name: 'Export QA seller', role: 'OWNER', current: true }],
  }));
  await page.route('**/api/seller/inventory?**', (route) => route.fulfill({
    status: 200,
    json: { items: [], page: { has_more: false, next_cursor: null } },
  }));
  await page.route('**/api/seller/dashboard/metrics', (route) => route.fulfill({
    status: 200,
    json: { metrics: { live_products: 1, sku_count: 1, total_on_hand: 4, reserved_stock: 0, available_stock: 4, pending_moderation: 0 }, as_of: '2026-10-18T12:00:00Z' },
  }));
}

test('dashboard export action opens the complete server CSV export surface', async ({ page }) => {
  await page.route('**/api/seller/products?**', (route) => route.fulfill({
    status: 200,
    json: {
      items: [{
        id: '7f74b5a1-456d-4143-867e-df2f6a930d2f',
        title: 'Export QA product',
        status: 'CREATED',
        skus_count: 1,
        total_active_quantity: 4,
        skus: [{
          id: '65d25d91-9e4f-459f-a70b-9405e44d4195',
          product_id: '7f74b5a1-456d-4143-867e-df2f6a930d2f',
          name: 'Export QA SKU',
          article: 'EXPORT-QA-1',
          images: [],
          stock_quantity: 4,
          active_quantity: 4,
          reserved_quantity: 0,
          is_active: true,
        }],
      }],
      page: { has_more: false },
    },
  }));
  await useSellerSession(page);
  await page.goto(`${seller}/dashboard`);
  const exportLink = page.locator('.seller-dashboard-actions a');
  await expect(exportLink).toBeVisible();
  await expect(exportLink).toHaveAttribute('href', '/inventory');
  await exportLink.click();
  await expect(page).toHaveURL(/\/inventory$/);
  await expect(page.locator('.seller-content button.seller-submit[type="button"]')).toContainText('\u0421\u0444\u043E\u0440\u043C\u0438\u0440\u043E\u0432\u0430\u0442\u044C\u0020\u043F\u043E\u043B\u043D\u044B\u0439\u0020CSV');
});

async function capture(page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, name: string) {
  const directory = resolve(process.cwd(), '../../docs/automation/seller_runs/2026-10-18/inventory-export-ui');
  await mkdir(directory, { recursive: true });
  await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
  await page.screenshot({ path: resolve(directory, `${name}-${testInfo.project.name}.png`), fullPage: true });
}

test('seller requests and downloads the complete server-generated inventory CSV', async ({ page }, testInfo) => {
  let polls = 0;
  let requestKey = '';
  await page.route('**/api/seller/inventory/exports', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({ format: 'CSV', query: null, status: null });
    requestKey = route.request().headers()['idempotency-key'];
    expect(requestKey).toMatch(/^[0-9a-f-]{36}$/i);
    await route.fulfill({ status: 202, json: { id: jobId, state: 'PENDING', row_count: 0 } });
  });
  await page.route(`**/api/seller/inventory/exports/${jobId}`, async (route) => {
    polls += 1;
    await route.fulfill({
      status: 200,
      json: polls === 1
        ? { id: jobId, state: 'PROCESSING', row_count: 0 }
        : { id: jobId, state: 'READY', row_count: 37, download_url: `/api/seller/inventory/exports/${jobId}/download?token=signed-csv-token` },
    });
  });
  await page.route(`**/api/seller/inventory/exports/${jobId}/download**`, (route) => route.fulfill({
    status: 200,
    contentType: 'text/csv; charset=utf-8',
    headers: { 'Content-Disposition': 'attachment; filename="seller-inventory-test.csv"' },
    body: '\uFEFFProduct,SKU,Seller article,SKU ID,Product status,On hand,Reserved,Available,Active\r\nA product,Blue,QA-1,sku-1,CREATED,5,1,4,Yes\r\n',
  }));
  await useSellerSession(page);
  expect((await page.goto(`${seller}/inventory`))?.status()).toBe(200);
  await expect(page.getByRole('button', { name: 'Сформировать полный CSV' })).toBeEnabled();
  await capture(page, testInfo, 'inventory-export-idle');
  await page.getByRole('button', { name: 'Сформировать полный CSV' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Формируем CSV на сервере' })).toBeVisible();
  const downloadLink = page.getByRole('link', { name: 'Скачать CSV' });
  await expect(downloadLink).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('status').filter({ hasText: '37 SKU' })).toBeVisible();
  await capture(page, testInfo, 'inventory-export-ready');
  const [download] = await Promise.all([page.waitForEvent('download'), downloadLink.click()]);
  expect(download.suggestedFilename()).toBe('seller-inventory-test.csv');
  const directory = resolve(process.cwd(), '../../docs/automation/seller_runs/2026-10-18/inventory-export-ui');
  const savedPath = resolve(directory, `download-${testInfo.project.name}.csv`);
  await download.saveAs(savedPath);
  expect((await readFile(savedPath)).toString('utf-8')).toContain('SKU ID');
  expect(requestKey).toBeTruthy();
});

test('seller retries an unknown export result with the same idempotency key', async ({ page }, testInfo) => {
  const requestKeys: string[] = [];
  let acceptedJobId = '';
  await page.route('**/api/seller/inventory/exports', async (route) => {
    const key = route.request().headers()['idempotency-key'];
    requestKeys.push(key);
    if (requestKeys.length === 1) {
      await route.fulfill({ status: 503, contentType: 'application/problem+json', json: { title: 'Export acknowledgement was lost' } });
      return;
    }
    acceptedJobId = jobId;
    await route.fulfill({ status: 202, json: { id: acceptedJobId, state: 'PENDING', row_count: 0 } });
  });
  await page.route(`**/api/seller/inventory/exports/${jobId}`, (route) => route.fulfill({
    status: 200,
    json: { id: jobId, state: 'READY', row_count: 1, download_url: `/api/seller/inventory/exports/${jobId}/download?token=signed-csv-token` },
  }));
  await useSellerSession(page);
  await page.goto(`${seller}/inventory`);
  const exportButton = page.getByRole('button', { name: 'Сформировать полный CSV' });
  await exportButton.click();
  await expect(page.locator('.seller-app [role="alert"]')).toContainText('Export acknowledgement was lost');
  await exportButton.click();
  await expect(page.getByRole('link', { name: 'Скачать CSV' })).toBeVisible({ timeout: 10_000 });
  expect(requestKeys).toHaveLength(2);
  expect(requestKeys[0]).toBe(requestKeys[1]);
  expect(acceptedJobId).toBe(jobId);
  await capture(page, testInfo, 'inventory-export-recovered');
});
