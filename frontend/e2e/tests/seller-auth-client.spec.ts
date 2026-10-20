import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3012';

async function fillLogin(page) {
  await page.locator('#seller-email').fill('seller@example.test');
  await page.locator('#seller-password').fill('test-password-123');
  await page.locator('#login-form button[type="submit"]').click();
}

test('login client decodes a successful response and attempts redirect', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true }),
  }));
  await page.goto(`${seller}/login`);
  await fillLogin(page);
  await expect(page.locator('.form-error')).toHaveCount(0);
});

test('login client rejects a malformed successful response', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: 'yes' }),
  }));
  await page.goto(`${seller}/login`);
  await fillLogin(page);
  await expect(page.locator('.form-error')).toContainText('Seller API вернул данные неверного формата');
  await expect(page.locator('#login-form button[type="submit"]')).toBeEnabled();
});

test('login client preserves organization selection conflicts', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.fulfill({
    status: 409,
    contentType: 'application/problem+json',
    body: JSON.stringify({
      type: 'about:blank',
      title: 'Choose an organization to sign in',
      status: 409,
      code: 'ORGANIZATION_SELECTION_REQUIRED',
      organizations: [{ id: '11111111-1111-4111-8111-111111111111', company_name: 'Acme', role: 'owner' }],
    }),
  }));
  await page.goto(`${seller}/login`);
  await fillLogin(page);
  await expect(page.locator('#seller-organization')).toBeVisible();
  await expect(page.locator('#seller-organization option')).toHaveText(['Выберите организацию', 'Acme — owner']);
});

test('registration client decodes pending email response', async ({ page }) => {
  await page.route('**/api/seller/auth/register', (route) => route.fulfill({
    status: 202,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'PENDING_EMAIL', message: 'Проверьте почту' }),
  }));
  await page.goto(`${seller}/register`);
  await page.locator('#register-company').fill('Acme');
  await page.locator('#register-email').fill('seller@example.test');
  await page.locator('#register-password').fill('test-password-123');
  await page.locator('#register-form button[type="submit"]').click();
  await expect(page.locator('.seller-auth-success')).toContainText('Проверьте почту');
  await expect(page.locator('#register-password')).toHaveValue('');
});

test('registration client rejects a malformed successful response', async ({ page }) => {
  await page.route('**/api/seller/auth/register', (route) => route.fulfill({
    status: 202,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'PENDING_EMAIL' }),
  }));
  await page.goto(`${seller}/register`);
  await page.locator('#register-company').fill('Acme');
  await page.locator('#register-email').fill('seller@example.test');
  await page.locator('#register-password').fill('test-password-123');
  await page.locator('#register-form button[type="submit"]').click();
  await expect(page.locator('.form-error')).toContainText('Seller API вернул данные неверного формата');
});

test('logout-all uses typed session and CSRF responses', async ({ page }) => {
  let csrfHeader = '';
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'seller-session' }),
  }));
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ token: 'csrf-test-token' }),
  }));
  await page.route('**/api/seller/auth/logout-all', async (route) => {
    csrfHeader = route.request().headers()['x-csrf-token'] ?? '';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
  await page.goto(`${seller}/dashboard`);
  await page.getByRole('button', { name: 'Выйти везде', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(csrfHeader).toBe('csrf-test-token');
});
