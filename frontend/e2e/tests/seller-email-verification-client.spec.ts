import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';

test('email verification uses a correlated typed request and clears the token fragment', async ({ page }) => {
  const token = 'V'.repeat(48);
  let requestId = '';
  let requestToken = '';
  await page.route('**/api/seller/auth/verify-email', async (route) => {
    requestId = route.request().headers()['x-request-id'] ?? '';
    requestToken = (route.request().postDataJSON() as { token: string }).token;
    await route.fulfill({ status: 200, json: { status: 'PENDING_REVIEW', message: 'Email verified. Account pending review.' } });
  });

  await page.goto(`${seller}/verify-email#token=${token}`);
  await expect(page.getByRole('status')).toHaveText('Email verified. Account pending review.');
  await expect(page).toHaveURL(/\/verify-email$/);
  expect(await page.evaluate(() => window.location.hash)).toBe('');
  expect(requestToken).toBe(token);
  expect(requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test('email verification resend keeps its privacy-safe response and uses the typed client', async ({ page }) => {
  const email = 'seller-verify@example.test';
  let requestId = '';
  let requestEmail = '';
  let verificationAttempts = 0;
  await page.route('**/api/seller/auth/verify-email', (route) => { verificationAttempts += 1; return route.fulfill({ status: 503, json: { title: 'Unexpected verification attempt' } }); });
  await page.route('**/api/seller/auth/email-verification/resend', async (route) => {
    requestId = route.request().headers()['x-request-id'] ?? '';
    requestEmail = (route.request().postDataJSON() as { email: string }).email;
    await route.fulfill({ status: 202, json: { message: 'If the account needs verification, a new link was sent.' } });
  });

  await page.goto(`${seller}/verify-email`);
  await page.locator('#resend-email').fill(email);
  await page.locator('.seller-auth-form button[type="submit"]').click();
  await expect(page.getByRole('status')).toHaveText('If the account needs verification, a new link was sent.');
  expect(verificationAttempts).toBe(0);
  expect(requestEmail).toBe(email);
  expect(requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test('email verification rejects malformed successful response shapes', async ({ page }) => {
  await page.route('**/api/seller/auth/verify-email', (route) => route.fulfill({ status: 200, json: { status: 'PENDING_REVIEW' } }));
  await page.goto(`${seller}/verify-email#token=${'M'.repeat(48)}`);
  await expect(page.locator('.form-error[role="alert"]')).toBeVisible();
  await expect(page.getByRole('status')).toHaveCount(0);
});
