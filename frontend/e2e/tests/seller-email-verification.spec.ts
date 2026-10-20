import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const mailpit = process.env.NEOMARKET_MAILPIT_URL ?? 'http://127.0.0.1:8025';
const password = 'DisposableSeller!2026';

test('seller registration requires verified email and keeps account pending review', async ({ page, request }, testInfo) => {
  const email = `seller-email-${randomUUID()}@example.com`;
  let verificationToken = '';
  let deliveredMessageId: string | undefined;
  try {
    await page.goto(`${seller}/register`);
    await page.getByLabel('Название компании').fill('Disposable verification fixture');
    await page.getByLabel('Рабочий email').fill(email);
    await page.getByLabel('Пароль').fill(password);
    await page.getByRole('button', { name: 'Создать аккаунт' }).click();
    await expect(page.getByRole('status')).toContainText('Проверьте почту');

    await page.goto(`${seller}/login`);
    await page.getByLabel('Рабочий email').fill(email);
    await page.getByLabel('Пароль').fill(password);
    await page.getByRole('button', { name: 'Войти в Seller Hub' }).click();
    await expect(page.locator('.form-error')).toContainText('Подтвердите email');

    let message: { ID?: string } | undefined;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const inbox = await request.get(`${mailpit}/api/v1/messages?query=${encodeURIComponent(`to:${email}`)}`);
      expect(inbox.ok()).toBeTruthy();
      const payload = await inbox.json() as { messages?: Array<{ ID?: string }> };
      message = payload.messages?.find((entry) => entry.ID);
      if (message) break;
      await page.waitForTimeout(250);
    }
    expect(message?.ID, 'registration must deliver a verification message to local SMTP inbox').toBeTruthy();
    deliveredMessageId = message!.ID;
    const detailResponse = await request.get(`${mailpit}/api/v1/message/${message!.ID}`);
    expect(detailResponse.ok()).toBeTruthy();
    const detail = await detailResponse.json() as { Text?: string; HTML?: string };
    const messageBody = `${detail.Text ?? ''}\n${detail.HTML ?? ''}`;
    const link = messageBody.match(/https?:\/\/[^\s"'<>]+\/verify-email#token=[A-Za-z0-9_-]+/);
    expect(link, 'email must contain a one-time verification URL fragment').toBeTruthy();
    verificationToken = new URL(link![0]).hash.slice('#token='.length);

    await page.goto(link![0]);
    await expect(page.getByRole('status')).toContainText('Email подтверждён');
    await expect(page.getByRole('status')).toContainText('ожидает проверки');
    await expect(page).toHaveURL(/\/verify-email$/);
    expect(await page.evaluate(() => window.location.hash)).toBe('');
    const evidenceDir = resolve(process.cwd(), '../../docs/automation/evidence');
    await mkdir(evidenceDir, { recursive: true });
    await writeFile(resolve(evidenceDir, `seller-email-verified-${testInfo.project.name}-2026-10-16.png`), await page.screenshot());

    const replay = await request.post(`${seller}/api/seller/auth/verify-email`, {
      headers: { Origin: seller },
      data: { token: verificationToken },
    });
    expect(replay.status()).toBe(400);

    await page.goto(`${seller}/login`);
    await page.getByLabel('Рабочий email').fill(email);
    await page.getByLabel('Пароль').fill(password);
    await page.getByRole('button', { name: 'Войти в Seller Hub' }).click();
    await expect(page.locator('.form-error')).toContainText('ожидает проверки');
  } finally {
    if (deliveredMessageId) {
      const deleted = await request.delete(`${mailpit}/api/v1/messages`, { data: { IDs: [deliveredMessageId] } });
      expect(deleted.ok(), 'delete the exact disposable verification message from Mailpit').toBeTruthy();
    }
    // This E2E uses only a UUID-scoped disposable local fixture.
    const sqlEmail = email.replaceAll("'", "''");
    execFileSync('docker', [
      'exec', 'neomarket-postgres-1', 'psql', '-U', 'postgres', '-d', 'b2b', '-v', 'ON_ERROR_STOP=1',
      '-c', `DELETE FROM sellers WHERE email = '${sqlEmail}'`,
    ], { stdio: 'ignore' });
  }
});
