import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3003';

test('finance page explains provider gate without showing fabricated balances', async ({ page }, testInfo) => {
  await page.route('**/api/seller/finance/overview', (route) => route.fulfill({
    status: 501,
    contentType: 'application/json',
    body: JSON.stringify({
      detail: {
        code: 'FEATURE_NOT_CONFIGURED',
        message: 'Seller finance is unavailable until a payment and commission provider is configured',
      },
    }),
  }));

  await page.goto(`${seller}/finance`);
  const state = page.locator('.seller-finance-state');
  await expect(state).toContainText('Финансовый провайдер не настроен');
  await expect(state).toContainText('платёжного провайдера и правил комиссии');
  await expect(page.getByText(/(?:₽|RUB|доступно|к выплате|баланс)/i)).toHaveCount(0);
  const payoutsLink = page.locator('.seller-sidebar a[href="/finance/payouts"]');
  if (!(await payoutsLink.isVisible())) await page.locator('.seller-sidebar button').click();
  await expect(payoutsLink).toBeVisible();

  const viewport = await page.evaluate(() => {
    const stateBox = document.querySelector('.seller-finance-state');
    const heading = stateBox?.querySelector('h2');
    const rect = stateBox?.getBoundingClientRect();
    return {
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      stateRight: rect?.right ?? 0,
      stateClientWidth: stateBox?.clientWidth ?? 0,
      stateScrollWidth: stateBox?.scrollWidth ?? 0,
      headingClientWidth: heading?.clientWidth ?? 0,
      headingScrollWidth: heading?.scrollWidth ?? 0,
    };
  });
  expect(viewport.documentWidth).toBeLessThanOrEqual(viewport.width);
  expect(viewport.stateRight).toBeLessThanOrEqual(viewport.width + 1);
  expect(viewport.stateScrollWidth).toBeLessThanOrEqual(viewport.stateClientWidth + 1);
  expect(viewport.headingScrollWidth).toBeLessThanOrEqual(viewport.headingClientWidth + 1);

  await page.screenshot({ path: testInfo.outputPath(`finance-provider-gate-${testInfo.project.name}.png`), fullPage: true });
});
