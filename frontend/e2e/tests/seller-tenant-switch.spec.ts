import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import { resetLocalLoginIpCounter } from './local-test-helpers';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const password = 'DisposableTenant!2026';

test('user selects and switches only between active organizations with membership', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const orgA = randomUUID();
  const orgB = randomUUID();
  const ownerA = randomUUID();
  const ownerB = randomUUID();
  const member = randomUUID();
  const email = `tenant-switch-browser-${randomUUID()}@example.com`;
  const pythonSeed = `
import asyncio, os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.security import hash_password
from src.models.seller import Seller
from src.models.seller_user import SellerUser
from src.models.seller_membership import SellerMembership

async def seed():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(timezone.utc)
    password_hash = hash_password(${JSON.stringify(password)})
    orgs = [
        Seller(id=__import__('uuid').UUID(${JSON.stringify(orgA)}), email=${JSON.stringify(`tenant-owner-a-${ownerA}@example.com`)}, hashed_password=password_hash, company_name='Tenant Switch Organization A', is_active=True, account_status='ACTIVE', email_verified_at=now),
        Seller(id=__import__('uuid').UUID(${JSON.stringify(orgB)}), email=${JSON.stringify(`tenant-owner-b-${ownerB}@example.com`)}, hashed_password=password_hash, company_name='Tenant Switch Organization B', is_active=True, account_status='ACTIVE', email_verified_at=now),
    ]
    async with sessions() as session:
        session.add_all(orgs)
        await session.flush()
        users = [
            SellerUser(id=orgs[0].id, email=orgs[0].email, hashed_password=password_hash, is_active=True, email_verified_at=now),
            SellerUser(id=orgs[1].id, email=orgs[1].email, hashed_password=password_hash, is_active=True, email_verified_at=now),
            SellerUser(id=__import__('uuid').UUID(${JSON.stringify(member)}), email=${JSON.stringify(email)}, hashed_password=password_hash, is_active=True, email_verified_at=now),
        ]
        session.add_all(users)
        await session.flush()
        session.add_all([
            SellerMembership(seller_id=orgs[0].id, user_id=orgs[0].id, role='OWNER', active=True),
            SellerMembership(seller_id=orgs[1].id, user_id=orgs[1].id, role='OWNER', active=True),
            SellerMembership(seller_id=orgs[0].id, user_id=users[2].id, role='VIEWER', active=True),
            SellerMembership(seller_id=orgs[1].id, user_id=users[2].id, role='SUPPORT', active=True),
        ])
        await session.commit()
    await engine.dispose()

asyncio.run(seed())
`;

  try {
    resetLocalLoginIpCounter();
    execFileSync('docker', ['exec', '-i', 'neomarket-b2b-1', 'uv', 'run', 'python', '-'], { input: pythonSeed, encoding: 'utf8', stdio: ['pipe', 'ignore', 'pipe'] });
    await page.goto(`${seller}/login`);
    await page.locator('#seller-email').fill(email);
    await page.locator('#seller-password').fill(password);
    await page.locator('#login-form button[type=submit]').click();
    await expect(page.locator('#seller-organization')).toBeVisible();
    await expect(page.locator('#seller-organization option')).toHaveCount(3);
    await page.locator('#seller-organization').selectOption(orgB);
    await page.locator('#login-form button[type=submit]').click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.locator('#seller-tenant-select')).toBeVisible();
    await expect(page.locator('#seller-tenant-select option')).toHaveCount(2);
    await page.locator('#seller-tenant-select').selectOption(orgA);
    await page.locator('.seller-tenant-switcher button').click();
    await expect.poll(() => page.locator('#seller-tenant-select').inputValue()).toBe(orgA);
    await expect.poll(async () => page.evaluate(async () => {
      const response = await fetch('/api/seller/auth/organizations', { cache: 'no-store' });
      const rows = await response.json() as Array<{ id: string; current: boolean }>;
      return rows.find((row) => row.current)?.id;
    })).toBe(orgA);

    const auditCount = execFileSync('docker', ['exec', 'neomarket-postgres-1', 'psql', '-U', 'postgres', '-d', 'b2b', '-Atc', `SELECT count(*) FROM seller_tenant_switch_audit WHERE user_id='${member}' AND source_seller_id='${orgB}' AND target_seller_id='${orgA}' AND source_role='SUPPORT' AND target_role='VIEWER';`], { encoding: 'utf8' }).trim();
    expect(auditCount).toBe('1');
    const evidenceDir = resolve(process.cwd(), '../../docs/automation/evidence');
    await mkdir(evidenceDir, { recursive: true });
    await writeFile(resolve(evidenceDir, `seller-tenant-switch-${testInfo.project.name}-2026-10-16.png`), await page.screenshot());
  } finally {
    execFileSync('docker', ['exec', 'neomarket-postgres-1', 'psql', '-U', 'postgres', '-d', 'b2b', '-v', 'ON_ERROR_STOP=1', '-c', `DELETE FROM seller_tenant_switch_audit WHERE user_id='${member}'; DELETE FROM sellers WHERE id IN ('${orgA}', '${orgB}'); DELETE FROM seller_users WHERE id IN ('${ownerA}', '${ownerB}', '${member}', '${orgA}', '${orgB}');`], { stdio: 'ignore' });
  }
});
