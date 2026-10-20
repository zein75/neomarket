import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';

test('team page decodes members and preserves CSRF/request identity for invite and role update', async ({ page }) => {
  const memberId = randomUUID();
  let memberRole = 'VIEWER';
  let membersReads = 0;
  let inviteRequestId = '';
  let roleRequestId = '';
  let ifMatch = '';
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-csrf-token' } }));
  await page.route('**/api/seller/team/members', (route) => {
    membersReads += 1;
    return route.fulfill({ status: 200, json: [
      { id: '00000000-0000-4000-8000-000000000001', email: 'owner@example.test', role: 'OWNER', active: true, created_at: '2026-10-19T07:00:00Z', revision: 1 },
      { id: memberId, email: 'member@example.test', role: memberRole, active: true, created_at: '2026-10-19T07:01:00Z', revision: memberRole === 'MANAGER' ? 2 : 1 },
    ] });
  });
  await page.route('**/api/seller/team/invitations', async (route) => {
    inviteRequestId = route.request().headers()['x-request-id'] ?? '';
    expect(route.request().headers()['x-csrf-token']).toBe('local-csrf-token');
    await route.fulfill({ status: 201, json: { id: randomUUID(), role: 'VIEWER', expires_at: '2026-10-22T07:00:00Z', status: 'PENDING' } });
  });
  await page.route(`**/api/seller/team/members/${memberId}`, async (route) => {
    roleRequestId = route.request().headers()['x-request-id'] ?? '';
    ifMatch = route.request().headers()['if-match'] ?? '';
    expect(route.request().headers()['x-csrf-token']).toBe('local-csrf-token');
    memberRole = (route.request().postDataJSON() as { role: string }).role;
    await route.fulfill({ status: 200, json: { id: memberId, email: 'member@example.test', role: memberRole, active: true, created_at: '2026-10-19T07:01:00Z', revision: 2 } });
  });

  await page.goto(`${seller}/team`);
  await expect(page.getByText('member@example.test')).toBeVisible();
  await page.locator('#team-email').fill('invite@example.test');
  await page.locator('.seller-team-invite button[type="submit"]').click();
  await expect(page.locator('.seller-auth-success[role="status"]')).toContainText('Приглашение отправлено');

  const roleSelect = page.getByLabel('Новая роль участника member@example.test');
  await roleSelect.selectOption('MANAGER');
  await page.getByLabel('Причина изменения доступа member@example.test').fill('Team responsibility changed');
  await page.getByRole('button', { name: 'Сохранить роль' }).click();
  await expect(page.locator('.seller-auth-success[role="status"]')).toContainText('Роль участника обновлена');
  expect(membersReads).toBeGreaterThanOrEqual(2);
  expect(inviteRequestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(roleRequestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(ifMatch).toBe('"1"');
});

test('team page rejects malformed member response', async ({ page }) => {
  await page.route('**/api/seller/team/members', (route) => route.fulfill({ status: 200, json: { members: [] } }));
  await page.goto(`${seller}/team`);
  await expect(page.locator('.seller-error[role="alert"]')).toBeVisible();
  await expect(page.getByText('В команде пока нет участников.')).toHaveCount(0);
});

test('invite acceptance uses typed CSRF and clears the invite token fragment', async ({ page }) => {
  const token = 'I'.repeat(48);
  let requestId = '';
  let requestToken = '';
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'anonymous-csrf-token' } }));
  await page.route('**/api/seller/team/invitations/accept', async (route) => {
    requestId = route.request().headers()['x-request-id'] ?? '';
    requestToken = (route.request().postDataJSON() as { token: string }).token;
    expect(route.request().headers()['x-csrf-token']).toBe('anonymous-csrf-token');
    await route.fulfill({ status: 201, json: { status: 'ACCEPTED', email: 'member@example.test', seller_id: randomUUID(), role: 'VIEWER' } });
  });
  await page.goto(`${seller}/team/accept-invite#token=${token}`);
  await page.locator('#invite-email').fill('member@example.test');
  await page.locator('#invite-password').fill('DisposableInvite!2026');
  await page.locator('#invite-form button[type="submit"]').click();
  await page.waitForURL(/\/login\?email=member%40example\.test&invite=accepted/);
  expect(requestToken).toBe(token);
  expect(requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(await page.evaluate(() => window.location.hash)).toBe('');
});
