import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const require = createRequire(resolve(process.cwd(), 'playwright.config.ts'));
const axePath = require.resolve('axe-core/axe.min.js');
const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3003';
const sellerEmail = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const sellerPassword = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const evidenceDate = process.env.NEOMARKET_SELLER_AXE_EVIDENCE_DATE ?? new Date().toISOString().slice(0, 10);

test('Seller screens meet axe WCAG 2.2 A/AA checks', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const scans: Array<{ name: string; status: number | null; violations: unknown[] }> = [];

  const scan = async (name: string, path: string, authenticated: boolean) => {
    const response = await page.goto(`${seller}${path}`);
    expect(response?.status(), `${path} should render successfully`).toBe(200);
    await expect(page.locator(authenticated ? 'main' : 'body'), `${name} renders its expected page shell`).toBeVisible();
    await page.addScriptTag({ path: axePath });
    const result = await page.evaluate(async (tags) => {
      const axe = (window as Window & { axe?: { run: (context: Document, options: unknown) => Promise<{ violations: Array<{ id: string; impact: string | null; help: string; helpUrl: string; nodes: Array<{ target: string[]; failureSummary?: string | null }> }> }> } }).axe;
      if (!axe) throw new Error('axe-core did not load in the browser');
      const { violations } = await axe.run(document, { runOnly: { type: 'tag', values: tags } });
      return violations.map(({ id, impact, help, helpUrl, nodes }) => ({
        id,
        impact,
        help,
        helpUrl,
        nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })),
      }));
    }, wcagTags);
    scans.push({ name, status: response?.status() ?? null, violations: result });
  };

  await scan('login', '/login', false);
  await scan('registration', '/register', false);
  await scan('email-verification', '/verify-email?token=accessibility-scan', false);
  await scan('unauthorized', '/unauthorized', false);

  await page.goto(`${seller}/login`);
  await page.locator('#seller-email').fill(sellerEmail);
  await page.locator('#seller-password').fill(sellerPassword);
  await page.locator('#seller-password').press('Enter');
  await expect(page).toHaveURL(/\/dashboard$/);

  const staticRoutes = [
    ['dashboard', '/dashboard'],
    ['products', '/products'],
    ['product-create', '/products/new'],
    ['inventory', '/inventory'],
    ['imports', '/imports'],
    ['orders', '/orders'],
    ['moderation', '/moderation'],
    ['team', '/team'],
    ['team-accept-invite', '/team/accept-invite?token=accessibility-scan'],
    ['finance', '/finance'],
    ['payouts', '/finance/payouts'],
  ] as const;

  for (const [name, path] of staticRoutes) await scan(name, path, true);

  await page.goto(`${seller}/products`);
  await expect(page.locator('tbody a.seller-product-link[href^="/products/"]').first()).toBeVisible();
  const productPath = await page.locator('a.seller-product-link[href^="/products/"]').evaluateAll((links) => {
    const href = links.map((link) => (link as HTMLAnchorElement).getAttribute('href'))
      .find((candidate) => candidate && /^\/products\/[\da-f-]{36}$/i.test(candidate));
    return href ?? null;
  });
  expect(productPath, 'the seeded local seller has a product detail to audit').not.toBeNull();
  await scan('product-detail', productPath!, true);
  await scan('product-skus', `${productPath}/skus`, true);

  const evidenceDir = process.env.NEOMARKET_SELLER_AXE_EVIDENCE_DIR
    ? resolve(process.cwd(), process.env.NEOMARKET_SELLER_AXE_EVIDENCE_DIR)
    : resolve(process.cwd(), '../docs/automation/evidence');
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(
    resolve(evidenceDir, `seller-axe-${testInfo.project.name}-${evidenceDate}.json`),
    JSON.stringify({ project: testInfo.project.name, viewport: page.viewportSize(), tags: wcagTags, scans }, null, 2),
  );

  const violations = scans.flatMap(({ name, violations: found }) => found.map((violation) => ({ screen: name, ...violation as object })));
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});
