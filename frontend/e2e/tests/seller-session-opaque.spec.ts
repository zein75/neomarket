import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3014';

test('BFF login stores an opaque cookie and revokes it through the server session endpoint', async ({ request }) => {
  const login = await request.post(`${seller}/api/seller/auth/login`, {
    headers: { Origin: seller },
    form: { username: 'opaque-session@example.test', password: 'opaque-session-password' },
  });
  expect(login.status()).toBe(200);
  const setCookie = login.headers()['set-cookie'] ?? '';
  const cookieMatch = setCookie.match(/(?:__Host-)?nm_seller_access=([^;]+)/);
  expect(cookieMatch).not.toBeNull();
  const accessCookie = cookieMatch![1]!;
  expect(accessCookie).toMatch(/^[A-Za-z0-9_-]{40,}$/);
  expect(accessCookie).not.toContain('.');

  const cookie = `nm_seller_access=${accessCookie}`;
  const session = await request.get(`${seller}/api/seller/auth/session`, { headers: { Cookie: cookie } });
  expect(session.status()).toBe(200);
  expect(await session.json()).toMatchObject({ id: 'opaque-session-user' });

  const csrf = await request.get(`${seller}/api/seller/auth/csrf`, { headers: { Cookie: cookie } });
  expect(csrf.status()).toBe(200);
  const csrfToken = (await csrf.json() as { token: string }).token;
  const refresh = await request.post(`${seller}/api/seller/auth/session/refresh`, {
    headers: { Origin: seller, Cookie: `${cookie}; nm_seller_csrf=${csrfToken}`, 'X-CSRF-Token': csrfToken },
  });
  expect(refresh.status()).toBe(200);
  const refreshedCookie = refresh.headers()['set-cookie'] ?? '';
  const refreshedMatch = refreshedCookie.match(/(?:__Host-)?nm_seller_access=([^;]+)/);
  expect(refreshedMatch).not.toBeNull();
  const refreshedToken = refreshedMatch![1]!;
  expect(refreshedToken).toMatch(/^[A-Za-z0-9_-]{40,}$/);
  expect(refreshedToken).not.toBe(accessCookie);

  const refreshedSession = await request.get(`${seller}/api/seller/auth/session`, {
    headers: { Cookie: `nm_seller_access=${refreshedToken}` },
  });
  expect(refreshedSession.status()).toBe(200);
  expect(await refreshedSession.json()).toMatchObject({ id: 'opaque-session-user' });

  const refreshedCsrf = await request.get(`${seller}/api/seller/auth/csrf`, {
    headers: { Cookie: `nm_seller_access=${refreshedToken}` },
  });
  expect(refreshedCsrf.status()).toBe(200);
  const refreshedCsrfToken = (await refreshedCsrf.json() as { token: string }).token;
  const logout = await request.post(`${seller}/api/seller/auth/logout`, {
    headers: { Origin: seller, Cookie: `nm_seller_access=${refreshedToken}; nm_seller_csrf=${refreshedCsrfToken}`, 'X-CSRF-Token': refreshedCsrfToken },
  });
  expect(logout.status()).toBe(200);
  expect(logout.headers()['set-cookie']).toContain('Max-Age=0');
});
