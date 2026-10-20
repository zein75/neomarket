import { expect, test } from '@playwright/test';

const admin = process.env.ADMIN_BASE_URL ?? 'http://localhost:3001';
const id = '00000000-0000-4000-8000-000000000001';
const accessDeniedHeading = '\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430';

const protectedPages = [
  '/',
  '/dashboard',
  '/moderation',
  `/moderation/${id}`,
  '/products',
  `/products/${id}`,
  '/taxonomy/categories',
  '/taxonomy/attributes',
  '/taxonomy/brands',
  '/sellers',
  `/sellers/${id}`,
  '/reports',
  `/reports/${id}`,
  '/appeals',
  `/appeals/${id}`,
  '/reasons',
  '/bulk-operations',
  '/operations',
  '/operations/events',
  '/audit',
  '/admin-users',
  `/admin-users/${id}`,
  '/settings',
];

test.describe('Admin anonymous access boundary', () => {
  for (const path of protectedPages) {
    test(`${path} redirects anonymous staff to the access-denied page`, async ({ page }) => {
      await page.goto(new URL(path, admin).toString());

      await expect(page).toHaveURL(new URL('/unauthorized', admin).toString());
      await expect(page.getByRole('heading', { name: accessDeniedHeading })).toBeVisible();
      await expect(page.locator('body')).not.toContainText(/L-Gauge Ultra-Z|FlowValve 300|ShieldCable M12|DEMO DATA/);
    });
  }

  test('Admin BFF returns a machine-readable 401 without a session', async ({ page }) => {
    // Use Chromium fetch so the test honours the explicit staging host mapping
    // configured in the project launch options. APIRequestContext resolves the
    // hostname outside Chromium and cannot reach private staging DNS.
    await page.goto(new URL('/login', admin).toString());
    const result = await page.evaluate(async () => {
      const response = await fetch('/api/admin/v1/moderation/tickets', { cache: 'no-store' });
      return {
        status: response.status,
        body: await response.json(),
        cacheControl: response.headers.get('cache-control'),
      };
    });

    expect(result.status).toBe(401);
    expect(result.body).toEqual({ code: 'ADMIN_SESSION_REQUIRED' });
    expect(result.cacheControl).toContain('no-store');
  });

  test('a forged Admin cookie cannot open a privileged page', async ({ page }) => {
    await page.context().addCookies([{ name: 'nm_admin_access', value: 'forged-token', url: admin }]);
    await page.goto(new URL('/moderation', admin).toString());

    await expect(page).toHaveURL(new URL('/unauthorized', admin).toString());
    await expect(page.getByRole('heading', { name: accessDeniedHeading })).toBeVisible();
    await expect(page.context().cookies(admin)).resolves.not.toContainEqual(expect.objectContaining({ name: 'nm_admin_access', value: 'forged-token' }));
  });
});
