import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const email = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const password = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const targetViewports = [
  { name: 'mobile-320', width: 320, height: 740 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'desktop-1280', width: 1280, height: 800 },
  { name: 'desktop-1440', width: 1440, height: 900 },
] as const;
const screens = [
  ['dashboard', '/dashboard'],
  ['products', '/products'],
  ['product-create', '/products/new'],
  ['inventory', '/inventory'],
  ['imports', '/imports'],
  ['orders', '/orders'],
  ['moderation', '/moderation'],
  ['team', '/team'],
  ['finance', '/finance'],
] as const;

test('Seller screens fit required viewports without client errors or broken images', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto(`${seller}/login?next=%2Fdashboard`);
  await page.locator('#seller-email').fill(email);
  await page.locator('#seller-password').fill(password);
  const loginResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/seller/auth/login') && response.request().method() === 'POST');
  await page.locator('#login-form button[type="submit"]').click();
  expect((await loginResponse).status()).toBe(200);
  await expect(page).toHaveURL(/\/dashboard$/);

  const evidenceDir = resolve(process.cwd(), '../../docs/automation/seller_runs/2026-10-18/ui-04-05-responsive-candidate');
  await mkdir(evidenceDir, { recursive: true });
  const observations: Array<Record<string, unknown>> = [];
  const violations: string[] = [];
  const browserErrors: Array<{ route: string; message: string }> = [];
  const unavailableResponses: Array<{ route: string; url: string; body: Promise<{ code?: string } | null> }> = [];
  let currentRoute = '';
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push({ route: currentRoute, message: message.text() });
  });
  page.on('pageerror', (error) => browserErrors.push({ route: currentRoute, message: error.message }));
  page.on('response', (response) => {
    if (response.status() === 501) {
      unavailableResponses.push({
        route: currentRoute,
        url: response.url(),
        body: response.json().catch(() => null),
      });
    }
  });
  for (const viewport of targetViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const [name, path] of screens) {
      currentRoute = path;
      const response = await page.goto(`${seller}${path}`);
      expect(response?.status(), `${path} should be served at ${viewport.width}px`).toBe(200);
      await expect(page.locator('main')).toBeVisible();
      if (name === 'dashboard') await expect(page.locator('.seller-dashboard-metrics')).toBeVisible();
      if (name === 'product-create') await expect(page.locator('select[name="categoryId"]')).toBeEnabled();
      const navigation = page.locator('.seller-sidebar nav');
      if (viewport.width <= 760) {
        const menuButton = page.getByRole('button', { name: 'Разделы' });
        await expect(menuButton).toBeVisible();
        await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
        await expect(navigation).toBeHidden();
        await menuButton.click();
        await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
        await expect(navigation.locator('[aria-current="page"]')).toBeVisible();
        const drawer = await navigation.boundingBox();
        expect(drawer).not.toBeNull();
        expect(drawer!.x).toBeGreaterThanOrEqual(0);
        expect(drawer!.x + drawer!.width).toBeLessThanOrEqual(viewport.width + 1);
        await navigation.locator('[aria-current="page"]').focus();
        await page.keyboard.press('Escape');
        await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
        await expect(menuButton).toBeFocused();
      } else {
        await expect(page.locator('.seller-mobile-nav-toggle')).toBeHidden();
        await expect(navigation).toBeVisible();
      }
      const layout = await page.evaluate(() => {
        const documentWidth = document.documentElement.scrollWidth;
        const width = document.documentElement.clientWidth;
        const main = document.querySelector('main');
        const mainRect = main?.getBoundingClientRect();
        const sidebar = document.querySelector('.seller-sidebar');
        const nav = sidebar?.querySelector('nav');
        return {
          width,
          documentWidth,
          horizontalOverflow: documentWidth > width,
          mainRight: mainRect?.right ?? null,
          mainWidth: mainRect?.width ?? null,
          navClientWidth: nav?.clientWidth ?? null,
          navScrollWidth: nav?.scrollWidth ?? null,
          mobileMenuVisible: !!document.querySelector('.seller-mobile-nav-toggle') && getComputedStyle(document.querySelector('.seller-mobile-nav-toggle')!).display !== 'none',
          dashboardContentReady: !!document.querySelector('.seller-dashboard-metrics'),
          activeNavigationVisible: !!sidebar?.querySelector('[aria-current="page"]'),
          brokenImages: [...document.images].filter((image) => image.complete && image.naturalWidth === 0).map((image) => image.currentSrc || image.src),
          overflowCandidates: [...document.querySelectorAll('body *')].flatMap((element) => {
            const rect = element.getBoundingClientRect();
            return rect.right > width + 1 || rect.left < -1 || (element as HTMLElement).scrollWidth > (element as HTMLElement).clientWidth + 1
              ? [{ tag: element.tagName, id: element.id, className: typeof element.className === 'string' ? element.className : '', right: Math.round(rect.right), left: Math.round(rect.left), clientWidth: (element as HTMLElement).clientWidth, scrollWidth: (element as HTMLElement).scrollWidth }]
              : [];
          }).slice(0, 12),
        };
      });
      observations.push({ viewport: viewport.name, screen: name, status: response?.status(), ...layout });
      if (layout.horizontalOverflow) violations.push(`${path} overflows at ${viewport.width}px: ${JSON.stringify(layout)}`);
      if ((layout.mainRight ?? 0) > viewport.width + 1) violations.push(`${path} main content escapes viewport at ${viewport.width}px`);
      if (layout.brokenImages.length) violations.push(`${path} has broken images at ${viewport.width}px: ${JSON.stringify(layout.brokenImages)}`);
      if (name === 'dashboard') {
        expect(layout.dashboardContentReady, 'dashboard screenshot must use a completed API state').toBe(true);
        await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
        await page.screenshot({ path: resolve(evidenceDir, `dashboard-${viewport.name}-${testInfo.project.name}.png`), fullPage: true });
      }
      if (name === 'product-create') {
        await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
        await page.screenshot({ path: resolve(evidenceDir, `product-create-${viewport.name}-${testInfo.project.name}.png`), fullPage: true });
      }
    }
  }
  const unavailable = await Promise.all(unavailableResponses.map(async (response) => ({
    route: response.route,
    url: response.url,
    code: (await response.body)?.code ?? null,
  })));
  const expectedUnavailableErrors = browserErrors.filter((error) => error.message.includes('status of 501 (Not Implemented)'));
  const unexpectedBrowserErrors = browserErrors.filter((error) => !error.message.includes('status of 501 (Not Implemented)'));
  const confirmedFeatureDisabled = unavailable.some((response) => response.code === 'FEATURE_NOT_CONFIGURED');
  const onlyExpectedUnavailableEndpoint = unavailable.every((response) =>
    new URL(response.url).pathname === '/api/seller/finance/overview'
      && (response.code === null || response.code === 'FEATURE_NOT_CONFIGURED'));
  if (expectedUnavailableErrors.length !== unavailable.length || !confirmedFeatureDisabled || !onlyExpectedUnavailableEndpoint) {
    violations.push(`Unexpected 501 responses or browser errors: ${JSON.stringify(unavailable)}`);
  }
  violations.push(...unexpectedBrowserErrors.map((error) => `${error.route} browser error: ${error.message}`));
  await writeFile(
    resolve(evidenceDir, `layout-${testInfo.project.name}.json`),
    JSON.stringify({ project: testInfo.project.name, browser: testInfo.project.use.browserName, viewports: targetViewports, screens: observations, browserErrors, unavailable, violations, result: violations.length ? 'FAIL' : 'PASS' }, null, 2),
  );
  expect(violations, 'Seller screens must not overflow or produce client errors/broken images at required viewports').toEqual([]);
});
