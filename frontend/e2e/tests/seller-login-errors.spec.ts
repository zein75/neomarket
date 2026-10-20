import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
const wrongCredentials = '\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 email \u0438\u043b\u0438 \u043f\u0430\u0440\u043e\u043b\u044c';
const verificationRequired = '\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 email \u043f\u043e \u0441\u0441\u044b\u043b\u043a\u0435 \u0438\u0437 \u043f\u0438\u0441\u044c\u043c\u0430';
const tooManyAttempts = '\u0421\u043b\u0438\u0448\u043a\u043e\u043c \u043c\u043d\u043e\u0433\u043e \u043f\u043e\u043f\u044b\u0442\u043e\u043a. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435';
const connectionError = '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u043f\u044b\u0442\u043a\u0443.';

async function fillAndSubmit(page) {
  await page.locator('#seller-email').fill('seller@example.test');
  await page.locator('#seller-password').fill('test-password-123');
  await page.locator('#login-form button[type="submit"]').click();
}

test('invalid credentials are readable and the seller can retry', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/seller/auth/login', async (route) => {
    attempts += 1;
    await route.fulfill({ status: 401, contentType: 'application/problem+json', body: JSON.stringify({ title: wrongCredentials }) });
  });
  await page.goto(`${seller}/login`);
  await fillAndSubmit(page);
  await expect(page.locator('.form-error')).toHaveText(wrongCredentials);
  await expect(page.locator('#seller-email')).toHaveValue('seller@example.test');
  await expect(page.locator('#seller-password')).toHaveValue('test-password-123');
  await expect(page.locator('#login-form button[type="submit"]')).toBeEnabled();
  await page.locator('#login-form button[type="submit"]').click();
  await expect(page.locator('.form-error')).toHaveText(wrongCredentials);
  expect(attempts).toBe(2);
});

test('email verification error explains the next step', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.fulfill({
    status: 403,
    contentType: 'application/problem+json',
    body: JSON.stringify({ title: verificationRequired }),
  }));
  await page.goto(`${seller}/login`);
  await fillAndSubmit(page);
  await expect(page.locator('.form-error')).toHaveText(verificationRequired);
});

test('rate-limit error stays visible without disabling retry', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.fulfill({
    status: 429,
    headers: { 'Retry-After': '60' },
    contentType: 'application/problem+json',
    body: JSON.stringify({ title: tooManyAttempts }),
  }));
  await page.goto(`${seller}/login`);
  await fillAndSubmit(page);
  await expect(page.locator('.form-error')).toHaveText(tooManyAttempts);
  await expect(page.locator('#login-form button[type="submit"]')).toBeEnabled();
});

test('network errors use a localized message instead of a raw browser exception', async ({ page }) => {
  await page.route('**/api/seller/auth/login', (route) => route.abort('failed'));
  await page.goto(`${seller}/login`);
  await fillAndSubmit(page);
  await expect(page.locator('.form-error')).toHaveText(connectionError);
  await expect(page.locator('.form-error')).not.toContainText('Failed to fetch');
  await expect(page.locator('#login-form button[type="submit"]')).toBeEnabled();
});
