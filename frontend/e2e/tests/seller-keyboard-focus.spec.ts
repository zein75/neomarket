import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3003';
const sellerEmail = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const sellerPassword = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const evidenceRoot = process.env.NEOMARKET_SELLER_FOCUS_EVIDENCE_DIR ?? '../../docs/automation/evidence';
const evidenceDate = process.env.NEOMARKET_SELLER_FOCUS_EVIDENCE_DATE ?? '2026-10-18';

test.setTimeout(120_000);

test('seller sign-in supports keyboard traversal and visible focus', async ({ page }, testInfo) => {
  await page.goto(`${seller}/login`);

  const focusOrder = [
    page.locator('.skip-link[href="#main-content"]'),
    page.locator('.skip-link[href="#login-form"]'),
    page.locator('#seller-email'),
    page.locator('#seller-password'),
    page.locator('#login-form button[type="submit"]'),
    page.locator('.seller-auth-switch a'),
    page.locator('.seller-back'),
  ];

  const observations = [];
  for (const target of focusOrder) {
    await page.keyboard.press('Tab');
    await expect(target).toBeFocused();
    observations.push(await target.evaluate((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const focusRules = Array.from(document.styleSheets).flatMap((sheet) => {
        try { return Array.from(sheet.cssRules).map((rule) => rule.cssText).filter((text) => text.includes(':focus-visible') && text.includes('outline: 3px')); }
        catch { return []; }
      });
      return {
        tag: element.tagName,
        id: element.id || null,
        href: element instanceof HTMLAnchorElement ? element.getAttribute('href') : null,
        focusVisible: element.matches(':focus-visible'),
        outlineWidth: style.outlineWidth,
        outlineStyle: style.outlineStyle,
        focusRules,
        inViewport: rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth,
      };
    }));
    expect(observations.at(-1)).toMatchObject({ focusVisible: true, outlineWidth: '3px', outlineStyle: 'solid', inViewport: true });
  }

  const evidenceDir = resolve(process.cwd(), evidenceRoot);
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(
    resolve(evidenceDir, `seller-keyboard-focus-${testInfo.project.name}-${evidenceDate}.png`),
    await page.screenshot({ fullPage: true }),
  );
  await writeFile(
    resolve(evidenceDir, `seller-keyboard-focus-${testInfo.project.name}-${evidenceDate}.json`),
    JSON.stringify({ project: testInfo.project.name, viewport: page.viewportSize(), focusOrder: observations, result: 'PASS' }, null, 2),
  );
});

test('seller navigation is reachable in order by keyboard', async ({ page }, testInfo) => {
  await page.goto(`${seller}/login`);
  await page.locator('#seller-email').fill(sellerEmail);
  const password = page.locator('#seller-password');
  await password.fill(sellerPassword);
  await password.press('Enter');
  await expect(page).toHaveURL(/\/dashboard$/);

  const navigationLinks = page.locator('.seller-sidebar nav a');
  const count = await navigationLinks.count();
  expect(count).toBeGreaterThan(0);
  const mobileNavigationToggle = page.locator('.seller-mobile-nav-toggle');
  if (await mobileNavigationToggle.isVisible()) {
    await mobileNavigationToggle.click();
    await expect(mobileNavigationToggle).toHaveAttribute('aria-expanded', 'true');
  }

  let foundFirstLink = false;
  for (let tab = 0; tab < 30; tab += 1) {
    await page.keyboard.press('Tab');
    if (await navigationLinks.first().evaluate((element) => element === document.activeElement)) {
      foundFirstLink = true;
      break;
    }
  }
  expect(foundFirstLink, 'keyboard tab sequence reaches seller navigation').toBe(true);

  const focusedLinks = [];
  for (let index = 0; index < count; index += 1) {
    if (index > 0) await page.keyboard.press('Tab');
    const link = navigationLinks.nth(index);
    await expect(link).toBeFocused();
    const focus = await link.evaluate((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return {
        href: element.getAttribute('href'),
        outlineWidth: style.outlineWidth,
        outlineStyle: style.outlineStyle,
        inViewport: rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth,
      };
    });
    expect(focus, `focus indication for ${focus.href}: ${JSON.stringify(focus)}`).toMatchObject({ outlineWidth: '3px', outlineStyle: 'solid', inViewport: true });
    focusedLinks.push(focus);
  }

  const evidenceDir = resolve(process.cwd(), evidenceRoot);
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(
    resolve(evidenceDir, `seller-keyboard-navigation-${testInfo.project.name}-${evidenceDate}.png`),
    await page.screenshot({ fullPage: true }),
  );
  await writeFile(
    resolve(evidenceDir, `seller-keyboard-navigation-${testInfo.project.name}-${evidenceDate}.json`),
    JSON.stringify({ project: testInfo.project.name, viewport: page.viewportSize(), focusedLinks, result: 'PASS' }, null, 2),
  );
});

test('seller product, inventory and order screens retain visible keyboard focus', async ({ page }, testInfo) => {
  await page.goto(`${seller}/login`);
  await page.locator('#seller-email').fill(sellerEmail);
  const password = page.locator('#seller-password');
  await password.fill(sellerPassword);
  await password.press('Enter');
  await expect(page).toHaveURL(/\/dashboard$/);

  const routes = [
    '/dashboard',
    '/products',
    '/products/new',
    '/products/b2a8f451-476a-4d89-a591-6f7e4a2a710e',
    '/products/b2a8f451-476a-4d89-a591-6f7e4a2a710e/skus',
    '/inventory',
    '/imports',
    '/orders',
    '/orders/8f40be87-cf72-4e78-89ba-9b2fc9ce3f11',
    '/moderation',
    '/team',
    '/finance',
    '/finance/payouts',
  ];
  for (const route of routes) {
    await page.goto(`${seller}${route}`);
    await expect(page.locator('.seller-app')).toBeVisible();
    const tabCount = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
    )).filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    }).length);
    expect(tabCount, `${route} has keyboard-operable controls`).toBeGreaterThan(0);

    let foundFocusedControl = false;
    const visitedFocusTargets = [];
    expect(tabCount, `${route} traversal stays within the verified 100-control limit`).toBeLessThanOrEqual(100);
    for (let tab = 0; tab < tabCount; tab += 1) {
      await page.keyboard.press('Tab');
      const focus = await page.evaluate(() => {
        const element = document.activeElement;
        if (!(element instanceof HTMLElement)) return null;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return {
          focusVisible: element.matches(':focus-visible'),
          tag: element.tagName,
          id: element.id || null,
          outlineWidth: style.outlineWidth,
          outlineStyle: style.outlineStyle,
          visible: rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth,
        };
      });
      if (!focus) continue;
      foundFocusedControl = true;
      expect(focus).toMatchObject({ focusVisible: true, outlineWidth: '3px', outlineStyle: 'solid', visible: true });
      visitedFocusTargets.push(focus);
      if (tab + 1 >= tabCount) break;
    }
    expect(foundFocusedControl, `${route} can receive keyboard focus`).toBe(true);
    expect(visitedFocusTargets, `${route} exposes focus for every visible keyboard-operable control`).toHaveLength(tabCount);

    const evidenceDir = resolve(process.cwd(), evidenceRoot);
    await mkdir(evidenceDir, { recursive: true });
    const routeName = route.slice(1).replaceAll('/', '-');
    await writeFile(
      resolve(evidenceDir, `seller-keyboard-${routeName}-${testInfo.project.name}-${evidenceDate}.png`),
      await page.screenshot({ fullPage: true }),
    );
    await writeFile(
      resolve(evidenceDir, `seller-keyboard-${routeName}-${testInfo.project.name}-${evidenceDate}.json`),
      JSON.stringify({ route, project: testInfo.project.name, viewport: page.viewportSize(), tabCount, visitedFocusTargets, result: 'PASS' }, null, 2),
    );
  }
});
