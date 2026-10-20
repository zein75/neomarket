import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { expect, test } from '@playwright/test';

const admin = process.env.ADMIN_BASE_URL ?? 'http://localhost:3001';

test('a cross-origin form cannot mutate Admin through the BFF', async ({ page }) => {
  const attacker = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    response.end(`<form id="attack" method="post" action="${admin}/api/admin/v1/staff"><input name="permission" value="admin.all"></form><script>document.getElementById('attack').submit()</script>`);
  });
  await new Promise<void>((resolve, reject) => {
    attacker.once('error', reject);
    attacker.listen(0, '127.0.0.1', resolve);
  });

  try {
    const address = attacker.address() as AddressInfo;
    const attackerOrigin = `http://localhost:${address.port}`;
    await page.context().addCookies([
      { name: 'nm_admin_access', value: 'synthetic-session', url: admin, sameSite: 'Strict' },
      { name: 'nm_admin_csrf', value: 'synthetic-csrf', url: admin, sameSite: 'Strict' },
    ]);

    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/admin/v1/staff') && response.request().method() === 'POST',
    );
    await page.goto(attackerOrigin);
    const response = await responsePromise;

    const body = await response.json();
    expect(response.status()).toBe(403);
    expect(body).toEqual({ code: 'CSRF_VALIDATION_FAILED' });
    expect(response.headers()['cache-control']).toContain('no-store');
  } finally {
    attacker.closeAllConnections();
    await new Promise<void>((resolve, reject) => attacker.close((error) => error ? reject(error) : resolve()));
  }
});
