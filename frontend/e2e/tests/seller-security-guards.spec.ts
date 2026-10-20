import { readdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3011';
const routesRoot = resolve(process.cwd(), 'apps/seller/app/api/seller');
const writeMethods = /export async function (?:POST|PUT|PATCH|DELETE)\s*\(/g;
const csrfExemptions = new Set([
  'auth/email-verification/resend/route.ts',
  'auth/login/route.ts',
  'auth/register/route.ts',
  'auth/verify-email/route.ts',
  'media/uploads/[assetId]/route.ts',
]);

async function routeFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return routeFiles(path);
    return entry.isFile() && entry.name === 'route.ts' ? [path] : [];
  }));
  return nested.flat();
}

test('all Seller BFF mutations enforce an exact origin and a CSRF or scoped capability check', async ({ request }) => {
  const routePaths = await routeFiles(routesRoot);
  const mutations: Array<{ route: string; source: string }> = [];

  for (const routePath of routePaths) {
    const source = await readFile(routePath, 'utf8');
    if (!writeMethods.test(source)) {
      writeMethods.lastIndex = 0;
      continue;
    }
    writeMethods.lastIndex = 0;
    const route = routePath.slice(routesRoot.length + 1).replaceAll('\\', '/');
    mutations.push({ route, source });
    expect(source, `${route} must call the shared exact-origin guard`).toContain('if (!isTrustedSellerOrigin(request))');
    if (csrfExemptions.has(route)) {
      expect(source, `${route} exemption must be a public auth action or signed upload`).toContain('isTrustedSellerOrigin(request)');
      if (route.startsWith('media/')) expect(source).toContain("url.searchParams.get('token')");
    } else {
      expect(source, `${route} must call the session-bound CSRF verifier`).toContain('csrfMatches(request)');
    }
  }

  expect(mutations.length).toBeGreaterThan(15);
  const crossSiteMutation = await request.post(`${seller}/api/seller/products`, {
    headers: { Origin: 'https://attacker.example', 'Sec-Fetch-Site': 'cross-site', Cookie: 'nm_seller_access=forged-token' },
    data: {},
  });
  expect(crossSiteMutation.status()).toBe(403);

  const preflight = await request.fetch(`${seller}/api/seller/products`, {
    method: 'OPTIONS',
    headers: { Origin: 'https://attacker.example', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-csrf-token' },
  });
  expect(preflight.headers()['access-control-allow-origin']).toBeUndefined();
});
