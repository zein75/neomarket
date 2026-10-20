import { expect, test } from '@playwright/test';

import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3003';
const productId = 'b2a8f451-476a-4d89-a591-6f7e4a2a710e';
const require = createRequire(resolve(process.cwd(), 'playwright.config.ts'));
const axePath = require.resolve('axe-core/axe.min.js');

async function useSellerUiSession(page: import('@playwright/test').Page) {
  // E2E uses the Seller app's existing development-only open-access switch.
  // Browser routes below still stub UI APIs; no production auth path is changed.
  await page.route('**/api/seller/auth/session', (route) => route.fulfill({
    status: 200,
    json: { user_id: 'e2e-user', seller_id: '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a', role: 'OWNER' },
  }));
  await page.route('**/api/seller/auth/logout', (route) => route.fulfill({
    status: 200,
    headers: { 'Set-Cookie': 'nm_seller_access=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax' },
    json: { ok: true },
  }));
}

const product = (revision: number, title: string) => ({
  id: productId,
  title,
  description: 'Rejected product description',
  category_id: null,
  status: 'BLOCKED',
  slug: 'revision-conflict-fixture',
  revision,
  blocked: true,
  blocking_reason: null,
  field_reports: [],
  characteristics: [{ name: 'material', value: 'steel' }],
  skus: [],
  updated_at: '2026-10-18T12:00:00Z',
});

test('blocked product autosaves a draft and resolves a stale revision explicitly', async ({ page }, testInfo) => {
  let patchCount = 0;
  let putCount = 0;
  const patchBodies: Array<{ title: string; description: string; characteristics: Array<{ name: string; value: string }> }> = [];
  const patchRequests: Array<{ ifMatch: string | null; status: number }> = [];

  await page.route(`**/api/seller/products/${productId}`, async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({ status: 200, json: product(patchCount === 0 ? 4 : 5, patchCount === 0 ? 'Server title' : 'Concurrent server title') });
      return;
    }
    if (method === 'PATCH') {
      patchCount += 1;
      patchBodies.push(route.request().postDataJSON() as { title: string; description: string; characteristics: Array<{ name: string; value: string }> });
      const status = patchCount === 1 ? 412 : 200;
      patchRequests.push({ ifMatch: route.request().headers()['if-match'] ?? null, status });
      await route.fulfill(patchCount === 1
        ? { status: 412, json: { detail: { code: 'REVISION_CONFLICT', message: 'Product revision is stale', current_revision: 5 } } }
        : { status: 200, json: { ...product(6, patchBodies[patchBodies.length - 1]!.title), description: patchBodies[patchBodies.length - 1]!.description } });
      return;
    }
    if (method === 'PUT') putCount += 1;
    await route.continue();
  });
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-playwright-csrf' } }));

  await useSellerUiSession(page);
  await page.goto(`${seller}/products/${productId}`);
  await expect(page.getByRole('heading', { name: 'Correct rejected fields' })).toBeVisible();

  const titleInput = page.getByLabel('Product title');
  await titleInput.fill('My local correction');
  const descriptionInput = page.getByLabel('Description');
  await descriptionInput.fill('Description saved from the local correction form.');
  const attributesInput = page.getByLabel('Product attributes (JSON)');
  await attributesInput.fill('{"material":"aluminum"}');
  const conflict = page.getByRole('alertdialog', { name: 'This draft changed elsewhere' });
  await expect(conflict).toBeVisible({ timeout: 8_000 });
  await expect(titleInput).toHaveValue('My local correction');
  await expect(descriptionInput).toHaveValue('Description saved from the local correction form.');
  await expect(attributesInput).toHaveValue('{"material":"aluminum"}');
  await page.addScriptTag({ path: axePath });
  const dialogViolations = await page.evaluate(async () => {
    const axe = (window as Window & { axe?: { run: (context: Document, options: unknown) => Promise<{ violations: Array<{ id: string; impact: string | null; nodes: Array<{ target: string[] }> }> }> } }).axe;
    if (!axe) throw new Error('axe-core did not load in the browser');
    const result = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } });
    return result.violations.map(({ id, impact, nodes }) => ({ id, impact, targets: nodes.map(({ target }) => target) }));
  });
  expect(dialogViolations).toEqual([]);
  const evidenceDir = resolve(process.cwd(), '../../docs/automation/evidence');
  await mkdir(evidenceDir, { recursive: true });
  await page.screenshot({ path: resolve(evidenceDir, `seller-ui09-conflict-${testInfo.project.name}-2026-10-18.png`), fullPage: true });
  const loadServer = conflict.getByRole('button', { name: 'Load server version' });
  const keepLocal = conflict.getByRole('button', { name: 'Keep my corrections' });
  expect(await conflict.evaluate((dialog) => dialog.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Shift+Tab');
  await expect(keepLocal).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(loadServer).toBeFocused();
  await keepLocal.click();
  await expect(page.getByText('All changes saved.')).toBeVisible({ timeout: 8_000 });
  await page.screenshot({ path: resolve(evidenceDir, `seller-ui09-saved-${testInfo.project.name}-2026-10-18.png`), fullPage: true });

  expect(patchCount).toBe(2);
  expect(putCount).toBe(0);
  expect(patchBodies).toEqual([
    { title: 'My local correction', description: 'Description saved from the local correction form.', characteristics: [{ name: 'material', value: 'aluminum' }] },
    { title: 'My local correction', description: 'Description saved from the local correction form.', characteristics: [{ name: 'material', value: 'aluminum' }] },
  ]);
  expect(page.getByRole('alertdialog')).toHaveCount(0);
  await writeFile(resolve(evidenceDir, `seller-ui09-${testInfo.project.name}-2026-10-18.json`), JSON.stringify({
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    authenticatedRoute: `/products/${productId}`,
    autosaveDebounceMs: 900,
    patchRequests,
    patchBodies,
    dialogViolations,
    localTitlePreservedAtConflict: 'My local correction',
    keyboardFocusStayedInsideDialog: true,
    conflictResolution: 'Keep my corrections',
    secondPatchCommitted: patchCount === 2 && patchRequests[1]?.status === 200,
    explicitModerationSubmitRequested: putCount > 0,
    finalSaveStatus: await page.getByRole('status').filter({ hasText: 'All changes saved.' }).innerText(),
  }, null, 2));
});

test('new product form autosaves per tenant, restores after reload, and warns before leaving', async ({ page }, testInfo) => {
  const tenantId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const categoryId = 'e2e3e554-b222-4cad-a8a7-9f2586c35a7e';
  const productPosts: Array<{ url: string; body: { variants: Array<{ price_minor: number }> } }> = [];
  const autosaveBodies: unknown[] = [];
  let autosaveRevision = 0;
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({
    status: 200,
    json: [{ id: tenantId, company_name: 'Local recovery fixture', role: 'OWNER', current: true }],
  }));
  await page.route('**/api/seller/categories', (route) => route.fulfill({
    status: 200,
    json: { items: [{ id: categoryId, name: 'Local category', attribute_schema: [] }] },
  }));
  await page.route(`**/api/seller/v1/products/draft-sessions/*`, async (route) => {
    if (route.request().method() === 'PUT') {
      autosaveRevision += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      autosaveBodies.push(payload);
      await route.fulfill({ status: 200, json: { id: '5d0d7f7e-5ad6-4e1a-9dd3-c0f41e5f4c12', revision: autosaveRevision, updated_at: '2026-10-19T08:00:00Z', payload: { ...payload, category_id: payload.category_id ?? null, media_names: payload.media_names ?? [] } } });
      return;
    }
    if (route.request().method() === 'DELETE') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: { code: 'DRAFT_AUTOSAVE_NOT_FOUND' } } });
  });
  await page.route('**/api/seller/auth/csrf', (route) => route.fulfill({ status: 200, json: { token: 'local-recovery-csrf' } }));
  page.on('request', (request) => {
    if (request.url().endsWith('/api/seller/v1/products/drafts') && request.method() === 'POST') {
      productPosts.push({ url: request.url(), body: request.postDataJSON() as { variants: Array<{ price_minor: number }> } });
    }
  });

  await useSellerUiSession(page);
  await page.goto(`${seller}/products/new`);
  await page.locator('input[name="title"]').fill('Unsaved local product');
  await page.locator('textarea[name="description"]').fill('Recovered after a reload in the same seller tab.');
  await expect(page.locator('select[name="categoryId"]')).toBeEnabled();
  await page.locator('select[name="categoryId"]').selectOption(categoryId);
  await page.locator('input[name="media"]').setInputFiles({ name: 'preview.png', mimeType: 'image/png', buffer: Buffer.from('local-only-preview') });
  await page.locator('.seller-form fieldset input').nth(0).fill('LOCAL-ARTICLE-1');
  await page.locator('.seller-form fieldset input').nth(1).fill('Local SKU');
  await expect(page.getByRole('status').filter({ hasText: 'Draft saved on the server.' })).toBeVisible({ timeout: 8_000 });

  const beforeUnload = page.waitForEvent('dialog');
  const reload = page.reload();
  const dialog = await beforeUnload;
  expect(dialog.type()).toBe('beforeunload');
  await dialog.accept();
  await reload;

  await expect(page.locator('input[name="title"]')).toHaveValue('Unsaved local product');
  await expect(page.locator('textarea[name="description"]')).toHaveValue('Recovered after a reload in the same seller tab.');
  await expect(page.locator('select[name="categoryId"]')).toHaveValue(categoryId);
  await expect(page.locator('.seller-form fieldset input').nth(0)).toHaveValue('LOCAL-ARTICLE-1');
  await expect(page.getByText('После восстановления выберите файлы заново: preview.png')).toBeVisible();
  await expect(page.locator('input[name="media"]')).toHaveValue('');
  await page.locator('.seller-form fieldset input').nth(1).fill('Local SKU');
  await page.locator('.seller-form fieldset input').nth(2).fill('19.99');
  await page.route('**/api/seller/v1/products/drafts', (route) => route.fulfill({
    status: 503,
    json: { detail: { code: 'LOCAL_NETWORK_UNAVAILABLE', message: 'The local draft endpoint is offline' } },
  }));
  const draftMutationId = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? 'null')?.mutationId, `neomarket.seller.new-product-draft.v1.${tenantId}`);
  expect(typeof draftMutationId).toBe('string');
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator('.seller-error[role="alert"]')).toContainText('offline');
  await expect(page.locator('input[name="title"]')).toHaveValue('Unsaved local product');
  expect(productPosts).toHaveLength(1);
  expect(autosaveBodies.length).toBeGreaterThan(0);
  expect(productPosts[0]?.body.variants[0]?.price_minor).toBe(1999);
  expect(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? 'null')?.stage, `neomarket.seller.new-product-draft.v1.${tenantId}`)).toBe('INITIAL_PRODUCT_FORM');
  expect(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? 'null')?.mutationId, `neomarket.seller.new-product-draft.v1.${tenantId}`)).toBe(draftMutationId);
  const formRetainedAfterFailedAtomicCreate = await page.locator('input[name="title"]').inputValue() === 'Unsaved local product';
  const evidenceDir = resolve(process.cwd(), '../../docs/automation/seller_runs/2026-10-18/ui-09-draft-autosave');
  await mkdir(evidenceDir, { recursive: true });
  await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
  await page.screenshot({ path: resolve(evidenceDir, `new-draft-recovery-${testInfo.project.name}.png`), fullPage: true });
  await page.goto(`${seller}/dashboard`);
  await expect(page.locator('.seller-logout')).toBeVisible();
  const logoutDialogs: string[] = [];
  page.on('dialog', async (dialog) => {
    logoutDialogs.push(dialog.type());
    if (logoutDialogs.length === 1) await dialog.dismiss();
    else await dialog.accept();
  });
  await page.locator('.seller-logout').click();
  expect(logoutDialogs).toEqual(['confirm']);
  expect(await page.evaluate((key) => sessionStorage.getItem(key) !== null, `neomarket.seller.new-product-draft.v1.${tenantId}`)).toBeTruthy();
  await page.locator('.seller-logout').click();
  expect(logoutDialogs).toEqual(['confirm', 'confirm']);
  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate((key) => sessionStorage.getItem(key), `neomarket.seller.new-product-draft.v1.${tenantId}`)).toBeNull();
  await writeFile(resolve(evidenceDir, `new-draft-recovery-${testInfo.project.name}.json`), JSON.stringify({
    project: testInfo.project.name,
    tenantScopedStorageKey: `neomarket.seller.new-product-draft.v1.${tenantId}`,
    autosaveDebounceMs: 900,
    stage: 'INITIAL_PRODUCT_FORM',
    mutationIdRetainedAfterFailedCreate: true,
    restoredAfterReload: true,
    mediaFilesNeedReselection: ['preview.png'],
    beforeUnloadPromptShown: dialog.type() === 'beforeunload',
    failedAtomicDraftAttempts: productPosts.length,
    serverAutosaveWrites: autosaveBodies.length,
    formRetainedAfterFailedAtomicCreate,
    logoutWarningShown: logoutDialogs[0] === 'confirm',
    cancelledLogoutPreservedDraft: true,
    confirmedLogoutClearedDraft: true,
  }, null, 2));
});

test('new product recovery resolves a persisted server operation after the create response was lost', async ({ page }) => {
  const tenantId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const mutationId = '5d0d7f7e-5ad6-4e1a-9dd3-c0f41e5f4c12';
  const categoryId = 'e2e3e554-b222-4cad-a8a7-9f2586c35a7e';
  await page.addInitScript(({ key, draft }) => window.sessionStorage.setItem(key, JSON.stringify(draft)), {
    key: `neomarket.seller.new-product-draft.v1.${tenantId}`,
    draft: {
      version: 1,
      tenantId,
      mutationId,
      stage: 'INITIAL_PRODUCT_FORM',
      updatedAt: '2026-10-19T08:00:00.000Z',
      title: 'Recovered server draft',
      description: 'The create response was lost before the browser received it.',
      categoryId,
      attributes: {},
      currency: 'RUB',
      variants: [{ key: 'variant-1', sellerArticle: 'RECOVERED-1', name: 'Recovered SKU', price: '19.99', onHand: '4', options: '{}' }],
      mediaNames: [],
    },
  });
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({ status: 200, json: [{ id: tenantId, company_name: 'Recovery fixture', role: 'OWNER', current: true }] }));
  await page.route('**/api/seller/categories', (route) => route.fulfill({ status: 200, json: { items: [{ id: categoryId, name: 'Recovery category', attribute_schema: [] }] } }));
  await page.route(`**/api/seller/v1/products/drafts/${mutationId}`, (route) => route.fulfill({
    status: 200,
    json: { id: productId, revision: 1, status: 'DRAFT', operation_id: mutationId, variants: [{ id: '2eae3a9d-0b77-4ab0-bf8a-c4b5b7f8ac31' }] },
  }));
  await useSellerUiSession(page);
  await page.goto(`${seller}/products/new`);
  await expect(page.getByText(/Черновик восстановлен с сервера/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Открыть карточку' })).toHaveAttribute('href', `/products/${productId}`);
  await expect(page.locator('input[name="title"]')).toHaveValue('Recovered server draft');
});

test('new product recovery restores the pre-create server autosave when no atomic operation exists', async ({ page }) => {
  const tenantId = '1cf35c56-8207-4fa7-b67b-4fa60d2eb96a';
  const draftId = '6d0d7f7e-5ad6-4e1a-9dd3-c0f41e5f4c12';
  const mutationId = '7d0d7f7e-5ad6-4e1a-9dd3-c0f41e5f4c12';
  const categoryId = 'e2e3e554-b222-4cad-a8a7-9f2586c35a7e';
  await page.addInitScript(({ storageKey, pointerKey, draft, draftId }) => {
    window.sessionStorage.setItem(storageKey, JSON.stringify(draft));
    window.localStorage.setItem(pointerKey, draftId);
  }, {
    storageKey: `neomarket.seller.new-product-draft.v1.${tenantId}`,
    pointerKey: `neomarket.seller.new-product-draft-id.v1.${tenantId}`,
    draftId,
    draft: {
      version: 1,
      tenantId,
      draftId,
      draftRevision: 1,
      mutationId,
      stage: 'INITIAL_PRODUCT_FORM',
      updatedAt: '2026-10-19T08:00:00.000Z',
      title: 'Recoverable server autosave',
      description: 'The pre-create form was saved before the network dropped.',
      categoryId,
      attributes: {},
      currency: 'RUB',
      variants: [{ key: 'variant-1', sellerArticle: 'AUTOSAVE-1', name: 'Autosave SKU', price: '19.99', onHand: '4', options: '{}' }],
      mediaNames: ['preview.png'],
    },
  });
  await page.route('**/api/seller/auth/organizations', (route) => route.fulfill({ status: 200, json: [{ id: tenantId, company_name: 'Autosave fixture', role: 'OWNER', current: true }] }));
  await page.route('**/api/seller/categories', (route) => route.fulfill({ status: 200, json: { items: [{ id: categoryId, name: 'Autosave category', attribute_schema: [] }] } }));
  await page.route(`**/api/seller/v1/products/drafts/${mutationId}`, (route) => route.fulfill({ status: 404, json: { detail: { code: 'DRAFT_OPERATION_NOT_FOUND' } } }));
  await page.route(`**/api/seller/v1/products/draft-sessions/${draftId}`, (route) => route.fulfill({
    status: 200,
    json: {
      id: draftId,
      revision: 2,
      updated_at: '2026-10-19T08:05:00Z',
      payload: { title: 'Recoverable server autosave', description: 'The pre-create form was saved before the network dropped.', category_id: categoryId, attributes: {}, currency: 'RUB', variants: [{ key: 'variant-1', seller_article: 'AUTOSAVE-1', name: 'Autosave SKU', price: '19.99', on_hand: '4', options: '{}' }], media_names: ['preview.png'] },
    },
  }));
  await useSellerUiSession(page);
  await page.goto(`${seller}/products/new`);
  await expect(page.locator('input[name="title"]')).toHaveValue('Recoverable server autosave');
  await expect(page.locator('textarea[name="description"]')).toHaveValue('The pre-create form was saved before the network dropped.');
  await expect(page.locator('select[name="categoryId"]')).toHaveValue(categoryId);
  await expect(page.getByText(/preview.png/)).toBeVisible();
});

test('Seller BFF persists and fences a pre-create autosave', async ({ request }) => {
  const sellerOrigin = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3016';
  const draftId = '6d0d7f7e-5ad6-4e1a-9dd3-c0f41e5f4c12';
  const access = 'opaque-session-token-' + 'x'.repeat(48);
  const cookie = `nm_seller_access=${access}`;
  const csrf = await request.get(`${sellerOrigin}/api/seller/auth/csrf`, { headers: { Cookie: cookie } });
  expect(csrf.status()).toBe(200);
  const csrfToken = (await csrf.json() as { token: string }).token;
  const headers = { Origin: sellerOrigin, Cookie: `${cookie}; nm_seller_csrf=${csrfToken}`, 'X-CSRF-Token': csrfToken, 'Content-Type': 'application/json' };
  const body = { title: 'BFF autosave', description: 'Persisted through the Seller BFF.', category_id: null, attributes: {}, currency: 'RUB', variants: [{ key: 'variant-1', seller_article: 'BFF-1', name: 'BFF SKU', price: '19.99', on_hand: '2', options: '{}' }], media_names: [] };
  const first = await request.put(`${sellerOrigin}/api/seller/v1/products/draft-sessions/${draftId}`, { headers, data: body });
  expect(first.status()).toBe(200);
  expect(await first.json()).toMatchObject({ id: draftId, revision: 1, payload: body });
  const second = await request.put(`${sellerOrigin}/api/seller/v1/products/draft-sessions/${draftId}`, { headers: { ...headers, 'If-Match': '1' }, data: { ...body, title: 'BFF autosave v2' } });
  expect(second.status()).toBe(200);
  expect(await second.json()).toMatchObject({ revision: 2, payload: { title: 'BFF autosave v2' } });
  const stale = await request.put(`${sellerOrigin}/api/seller/v1/products/draft-sessions/${draftId}`, { headers: { ...headers, 'If-Match': '1' }, data: body });
  expect(stale.status()).toBe(412);
  const restored = await request.get(`${sellerOrigin}/api/seller/v1/products/draft-sessions/${draftId}`, { headers: { Cookie: cookie } });
  expect(restored.status()).toBe(200);
  expect(await restored.json()).toMatchObject({ revision: 2, payload: { title: 'BFF autosave v2' } });
  const deleted = await request.delete(`${sellerOrigin}/api/seller/v1/products/draft-sessions/${draftId}`, { headers });
  expect(deleted.status()).toBe(204);
});
