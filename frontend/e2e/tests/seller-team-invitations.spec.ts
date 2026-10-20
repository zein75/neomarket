import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { APIRequestContext } from '@playwright/test';
import { expect, test } from '@playwright/test';
import { resetLocalLoginIpCounter } from './local-test-helpers';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const b2b = process.env.NEOMARKET_B2B_URL ?? 'http://127.0.0.1:8002';
const mailpit = process.env.NEOMARKET_MAILPIT_URL ?? 'http://127.0.0.1:8025';
const password = 'DisposableSeller!2026';

async function messageFor(request: APIRequestContext, email: string) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const inbox = await request.get(`${mailpit}/api/v1/messages?query=${encodeURIComponent(`to:${email}`)}`);
    expect(inbox.ok()).toBeTruthy();
    const messages = (await inbox.json() as { messages?: Array<{ ID?: string }> }).messages ?? [];
    const found = messages.find((item) => item.ID);
    if (found?.ID) {
      const detail = await request.get(`${mailpit}/api/v1/message/${found.ID}`);
      expect(detail.ok()).toBeTruthy();
      const body = await detail.json() as { Text?: string; HTML?: string };
      return { id: found.ID, text: `${body.Text ?? ''}\n${body.HTML ?? ''}` };
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 200));
  }
  throw new Error(`No local Mailpit message delivered to ${email}`);
}

test('seller owner can invite a staff member and staff can accept the one-use link', async ({ page, request }, testInfo) => {
  const ownerEmail = `seller-team-owner-${randomUUID()}@example.com`;
  const memberEmail = `seller-team-member-${randomUUID()}@example.com`;
  const emails = [ownerEmail, memberEmail].map((email) => email.replaceAll("'", "''"));
  const messageIds: string[] = [];

  try {
    resetLocalLoginIpCounter();
    await page.goto(`${seller}/register`);
    await page.locator('#register-company').fill('Disposable seller team fixture');
    await page.locator('#register-email').fill(ownerEmail);
    await page.locator('#register-password').fill(password);
    await page.locator('#register-form button[type=submit]').click();
    await expect(page.getByRole('status')).toBeVisible();

    const verification = await messageFor(request, ownerEmail);
    messageIds.push(verification.id);
    const verificationLink = verification.text.match(/https?:\/\/[^\s"'<>]+\/verify-email#token=[A-Za-z0-9_-]+/);
    expect(verificationLink).toBeTruthy();
    const verificationToken = new URL(verificationLink![0]).hash.slice('#token='.length);
    const verified = await request.post(`${b2b}/auth/verify-email`, { data: { token: verificationToken } });
    expect(verified.status()).toBe(200);
    execFileSync('docker', ['exec', 'neomarket-postgres-1', 'psql', '-U', 'postgres', '-d', 'b2b', '-v', 'ON_ERROR_STOP=1', '-c', `UPDATE sellers SET is_active=TRUE, account_status='ACTIVE' WHERE email='${emails[0]}'; UPDATE seller_users SET is_active=TRUE WHERE email='${emails[0]}';`], { stdio: 'ignore' });

    await page.goto(`${seller}/login`);
    await page.locator('#seller-email').fill(ownerEmail);
    await page.locator('#seller-password').fill(password);
    await page.locator('#login-form button[type=submit]').click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.goto(`${seller}/team`);
    await expect(page.locator('.seller-team-invite')).toBeVisible();
    await page.locator('#team-email').fill(memberEmail);
    await page.locator('#team-role').selectOption('VIEWER');
    await page.locator('.seller-team-invite button[type=submit]').click();
    await expect(page.locator('.seller-auth-success')).toBeVisible();

    const invitation = await messageFor(request, memberEmail);
    messageIds.push(invitation.id);
    const inviteLink = invitation.text.match(/https?:\/\/[^\s"'<>]+\/team\/accept-invite#token=[A-Za-z0-9_-]+/);
    expect(inviteLink).toBeTruthy();
    const localInviteUrl = new URL(inviteLink![0]);
    localInviteUrl.host = new URL(seller).host;
    await page.goto(localInviteUrl.toString());
    await expect(page.locator('#invite-form')).toBeVisible();
    await expect(page).toHaveURL(/\/team\/accept-invite$/);
    expect(await page.evaluate(() => window.location.hash)).toBe('');
    await page.locator('#invite-email').fill(memberEmail);
    await page.locator('#invite-password').fill(password);
    await page.locator('#invite-form button[type=submit]').click();
    await expect(page).toHaveURL(/\/login\?email=/);
    await expect(page.getByRole('status')).toBeVisible();
    await expect(page.locator('#seller-email')).toHaveValue(memberEmail);

    await page.locator('#seller-password').fill(password);
    await page.locator('#login-form button[type=submit]').click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.goto(`${seller}/team`);
    await expect(page.locator('.seller-team-content [role=alert]')).toBeVisible();

    const evidenceDir = resolve(process.cwd(), '../../docs/automation/evidence');
    await mkdir(evidenceDir, { recursive: true });
    await writeFile(resolve(evidenceDir, `seller-team-viewer-denied-${testInfo.project.name}-2026-10-16.png`), await page.screenshot());
  } finally {
    execFileSync('docker', ['exec', 'neomarket-postgres-1', 'psql', '-U', 'postgres', '-d', 'b2b', '-v', 'ON_ERROR_STOP=1', '-c', `DELETE FROM seller_tenant_switch_audit WHERE user_id IN (SELECT id FROM seller_users WHERE email IN ('${emails[0]}', '${emails[1]}')); DELETE FROM sellers WHERE email IN ('${emails[0]}', '${emails[1]}'); DELETE FROM seller_users WHERE email IN ('${emails[0]}', '${emails[1]}');`], { stdio: 'ignore' });
    if (messageIds.length) {
      const deleted = await fetch(`${mailpit}/api/v1/messages`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ IDs: messageIds }),
      });
      if (!deleted.ok) throw new Error('Could not remove exact disposable Mailpit messages');
    }
  }
});
