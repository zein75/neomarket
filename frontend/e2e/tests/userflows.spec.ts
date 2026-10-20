import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

// Use the configured canonical storefront origin so mutation CSRF checks exercise
// the same trusted host as the local test deployment.
const storefront = 'http://localhost:3000';
const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3002';
const admin = 'http://127.0.0.1:3001';
const sellerQaEmail = process.env.NEOMARKET_QA_SELLER_EMAIL ?? 'seller.demo@neomarket.ru';
const sellerQaPassword = process.env.NEOMARKET_QA_SELLER_PASSWORD ?? 'NeoMarketDemo!2026';
const sessionQaEmail = process.env.NEOMARKET_QA_SESSION_SELLER_EMAIL;
const sessionQaPassword = process.env.NEOMARKET_QA_SESSION_SELLER_PASSWORD;
const sellerBackend = process.env.NEOMARKET_B2B_TEST_URL ?? 'http://127.0.0.1:8002';
const sellerServiceKey = process.env.NEOMARKET_B2B_SERVICE_KEY ?? 'dev-service-key-change-in-production';

test.describe('storefront public userflows', () => {
  test('home, catalog, cart and authentication entry points render', async ({ page }) => {
    await page.goto(`${storefront}/`);
    await expect(page).toHaveTitle(/NeoMarket/);
    await page.goto(`${storefront}/catalog`);
    await expect(page.locator('main')).toBeVisible();
    await expect(page.getByRole('textbox').first()).toBeVisible();
    await page.goto(`${storefront}/cart`);
    await expect(page.locator('main')).toBeVisible();
    await page.goto(`${storefront}/login`);
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await page.goto(`${storefront}/register`);
    await expect(page.locator('input[name="password"]')).toBeVisible();
  });

  test('BFF health and catalog boundary are reachable', async ({ request }) => {
    const health = await request.get(`${storefront}/api/health`);
    expect(health.ok()).toBeTruthy();
    expect((await health.json()).status).toBe('ok');
    const catalog = await request.get(`${storefront}/bff/catalog?limit=20`);
    expect(catalog.status()).toBe(200);
    expect(catalog.headers()['content-type']).toContain('application/json');
  });

  test('catalog rendering has live API provenance', async ({ page }) => {
    const catalogResponse = page.waitForResponse((response) => response.url().includes('/bff/catalog?') && response.request().method() === 'GET');
    await page.goto(`${storefront}/catalog`);
    expect((await catalogResponse).status()).toBe(200);
    await expect(page.locator('.catalog-results .product-card').first()).toBeVisible();
    await expect(page.locator('footer')).toContainText(/live catalog \/ read-only/i);
  });

  test('catalog cards show only authoritative product details and never expose internal SKU UUIDs', async ({ page }) => {
    await page.goto(`${storefront}/catalog`);
    const payload = await page.evaluate(async () => {
      const response = await fetch('/bff/catalog?limit=20');
      if (!response.ok) throw new Error(`catalog request failed: ${response.status}`);
      return response.json();
    }) as { items?: Array<{ id?: string; name?: string; description?: string | null; min_price_minor?: number | null; skus?: Array<{ id?: string; article?: string | null; active_quantity?: number; is_active?: boolean }> }> };
    const item = payload.items?.find((candidate) => candidate.id && candidate.description && typeof candidate.min_price_minor === 'number' && candidate.skus?.some((sku) => sku.id && (sku.active_quantity ?? 0) > 0));
    expect(item?.id, 'test requires an authoritative product with description, price and stock').toBeTruthy();
    const card = page.locator(`.product-card[data-product-id="${item!.id}"]`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(item!.description!);
    await expect(card).not.toContainText(item!.skus!.find((sku) => sku.id)?.id ?? '');
    const article = item!.skus!.find((sku) => sku.id && (sku.active_quantity ?? 0) > 0)?.article?.trim();
    if (article) await expect(card.locator('.product-sku')).toContainText(article);
    else await expect(card.locator('.product-sku')).toHaveCount(0);
    const totalStock = item!.skus!.filter((sku) => sku.is_active !== false).reduce((total, sku) => total + (Number.isSafeInteger(sku.active_quantity) ? sku.active_quantity! : 0), 0);
    await expect(card.locator('.stock')).toBeVisible();
    await expect(card.locator('.stock')).toContainText(String(totalStock));
    const expectedPrice = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(item!.min_price_minor! / 100);
    await expect(card.locator('.product-footer strong')).toContainText(expectedPrice);
  });

  test('every public catalog item has a resolvable product detail', async ({ request }) => {
    const response = await request.get(`${storefront}/bff/catalog?limit=100`);
    expect(response.status()).toBe(200);
    const payload = await response.json() as { items?: Array<{ id?: string }> };
    expect(payload.items?.length).toBeGreaterThan(0);
    for (const item of payload.items ?? []) {
      expect(item.id).toBeTruthy();
      const detail = await request.get(`${storefront}/api/storefront/products/${item.id}`);
      expect(detail.status(), `catalog item ${item.id} must resolve to detail`).toBe(200);
    }
  });

  test('catalog hides seed ratings and media until verified source data exists', async ({ page }) => {
    const catalogResponse = page.waitForResponse((response) => response.url().includes('/bff/catalog?') && response.request().method() === 'GET');
    await page.goto(`${storefront}/catalog`);
    const response = await catalogResponse;
    expect(response.status()).toBe(200);
    // Read a fresh authoritative payload in-page. Chromium can discard the body
    // of an already-consumed Next.js response under parallel mobile runs.
    const payload = await page.evaluate(async () => {
      const result = await fetch('/bff/catalog?limit=20');
      if (!result.ok) throw new Error(`catalog request failed: ${result.status}`);
      return result.json();
    }) as { items?: Array<{ id?: string; images?: unknown[]; skus?: Array<{ images?: unknown[] }>; rating?: unknown; reviews_count?: unknown }> };
    const visibleIds = await page.locator('.product-card[data-product-id]').evaluateAll((cards) => cards.map((card) => card.getAttribute('data-product-id')));
    const item = payload.items?.find((entry) => typeof entry.id === 'string'
      && visibleIds.includes(entry.id)
      && !entry.images?.length
      && entry.skus?.every((sku) => !sku.images?.length));
    expect(item?.id, 'visible catalog fixture must include a seed product without verified media').toBeTruthy();
    expect(item).not.toHaveProperty('rating');
    expect(item).not.toHaveProperty('reviews_count');
    const card = page.locator('.product-card').filter({ has: page.locator(`a[href*="${item!.id}"]`) }).first();
    await expect(card).toBeVisible();
    await expect(card.locator('.product-rating')).toHaveCount(0);
    await expect(card.locator('.product-image [role="img"]')).toBeVisible();
    await expect(page.locator('.product-sku')).toHaveCount(0);
    await expect(card.locator('.product-tag')).toBeVisible();
    const imageBox = await card.locator('.product-image').boundingBox();
    const favoriteButton = card.locator('.product-favorite-button');
    await expect(favoriteButton).toBeVisible();
    await expect(favoriteButton).toHaveCSS('position', 'absolute');
    const favoriteBox = await favoriteButton.boundingBox();
    expect(imageBox).not.toBeNull();
    expect(favoriteBox).not.toBeNull();
    expect(favoriteBox!.y).toBeGreaterThanOrEqual(imageBox!.y);
    expect(favoriteBox!.y + favoriteBox!.height).toBeLessThanOrEqual(imageBox!.y + 40);
    expect(favoriteBox!.x + favoriteBox!.width).toBeLessThanOrEqual(imageBox!.x + imageBox!.width);
    await expect(favoriteButton.locator('.material-symbols-outlined')).toHaveText('favorite_border');
    const favoriteMutation = page.waitForResponse((candidate) => candidate.url().includes('/api/storefront/favorites/') && candidate.request().method() === 'POST');
    await favoriteButton.click();
    expect((await favoriteMutation).status()).toBe(401);
    await expect(favoriteButton).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('.toast')).toContainText('Войдите');
    for (const productCard of await page.locator('.product-card').all()) {
      await expect(productCard.locator('img[src^="data:image/svg+xml"]')).toHaveCount(0);
    }
  });

  test('catalog category controls come from authoritative facets', async ({ page }) => {
    const facetsResponsePromise = page.waitForResponse((response) => response.url().includes('/bff/catalog/facets') && response.request().method() === 'GET');
    await page.goto(`${storefront}/catalog`);
    const facetsResponse = await facetsResponsePromise;
    expect(facetsResponse.status()).toBe(200);
    const facets = await facetsResponse.json() as { categories?: Array<{ id?: string; name?: string; count?: number }> };
    const categories = (facets.categories ?? []).filter((entry) => typeof entry.name === 'string' && entry.name.trim());
    await expect(page.locator('.catalog-filter-panel')).toBeVisible();
    await expect(page.locator('.catalog-filter-panel .filter-option').first()).toBeVisible();
    for (const category of categories) {
      await expect(page.locator('.catalog-filter-panel .filter-option', { hasText: category.name! })).toBeVisible();
    }
    // The design uses a compact quick-filter row; the full authoritative facet
    // list remains available in the sidebar above, while the first five are
    // surfaced as shortcuts.
    for (const category of categories.slice(0, 5)) {
      await expect(page.locator('.catalog-category-chips .catalog-category-chip', { hasText: category.name! })).toBeVisible();
    }

    // Facets can resolve before the first catalog request, especially on mobile
    // where the catalog application hydrates after the filter controls. Capture
    // the reset baseline only after real catalog cards have rendered.
    await expect(page.locator('.catalog-results .product-card').first()).toBeVisible();
    const initialProductCount = await page.locator('.catalog-results .product-card').count();
    const selectableCategory = categories.find((entry) => entry.id && entry.name);
    if (selectableCategory) {
      await page.locator('.catalog-filter-panel .filter-option', { hasText: selectableCategory.name! }).click();
      await expect.poll(() => page.locator('.catalog-results .product-card').count()).toBe(selectableCategory.count);
      expect(new URL(page.url()).searchParams.get('category_id')).toBe(selectableCategory.id);

      await page.locator('.filter-panel-head button').click();
      await expect.poll(() => page.locator('.catalog-results .product-card').count()).toBe(initialProductCount);
      expect(new URL(page.url()).searchParams.has('category_id')).toBe(false);
    }
  });

  test('catalog search stays synchronized and filters remain pinned to the product rail', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${storefront}/catalog`);
    await expect(page.locator('.catalog-results .product-card').first()).toBeVisible();
    const resultCount = page.locator('.catalog-results-count');
    await expect(resultCount).toBeVisible();
    await expect(resultCount).toHaveCSS('position', 'static');
    await expect(page.locator('.catalog-data-note .catalog-results-count')).toHaveCount(1);
    const countBox = await resultCount.boundingBox();
    const firstCardBox = await page.locator('.catalog-results .product-card').first().boundingBox();
    expect(countBox).not.toBeNull();
    expect(firstCardBox).not.toBeNull();
    expect(countBox!.y + countBox!.height).toBeLessThanOrEqual(firstCardBox!.y);

    const headerSearch = page.getByRole('searchbox', { name: 'Поиск по каталогу' });
    const resultsSearch = page.locator('#catalog-search');
    const firstTitle = (await page.locator('.catalog-results .product-card h3').first().innerText()).trim();
    await headerSearch.fill(firstTitle);
    await expect(resultsSearch).toHaveValue(firstTitle);
    await expect(page.locator('.catalog-results .product-card')).toHaveCount(1);
    await expect(page.locator('.catalog-results-count')).toHaveText('1 товар');

    await page.getByRole('button', { name: 'Список' }).click();
    await expect(page.locator('.catalog-results .product-grid')).toHaveClass(/is-list/);
    await page.getByRole('button', { name: 'Плитка' }).click();
    await expect(page.locator('.catalog-results .product-grid')).not.toHaveClass(/is-list/);

    await headerSearch.fill('');
    await expect.poll(() => page.locator('.catalog-results .product-card').count()).toBeGreaterThan(1);
    await expect.poll(async () => Number((await page.locator('.catalog-results-count').innerText()).match(/\d+/)?.[0])).toBeGreaterThan(1);

    const filters = page.locator('.catalog-filter-panel');
    await expect(filters).toHaveCSS('position', 'sticky');
    if ((page.viewportSize()?.width ?? 0) > 880) {
      const filterTop = await filters.evaluate((element) => Math.round(element.getBoundingClientRect().top));
      const firstCardTop = await page.locator('.catalog-results .product-card').first().evaluate((element) => Math.round(element.getBoundingClientRect().top));
      expect(Math.abs(filterTop - firstCardTop)).toBeLessThanOrEqual(1);
    }
    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = 'auto';
      // Keep the sidebar inside its containing catalog section; sticky is
      // intentionally constrained by the section's bottom edge.
      window.scrollTo(0, 500);
    });
    await expect.poll(() => filters.evaluate((element) => Math.round(element.getBoundingClientRect().top))).toBe(122);
  });

  test('catalog result count stays in the status row above product cards', async ({ page }) => {
    await page.goto(`${storefront}/catalog`);
    const count = page.locator('.catalog-data-note .catalog-results-count');
    const note = page.locator('.catalog-data-note');
    const card = page.locator('.catalog-results .product-card').first();
    await expect(count).toBeVisible();
    await expect(card).toBeVisible();
    const geometry = await page.evaluate(() => {
      const countElement = document.querySelector('.catalog-data-note .catalog-results-count');
      const noteElement = document.querySelector('.catalog-data-note');
      const cardElement = document.querySelector('.catalog-results .product-card');
      if (!countElement || !noteElement || !cardElement) return null;
      const countBox = countElement.getBoundingClientRect();
      const noteBox = noteElement.getBoundingClientRect();
      const cardBox = cardElement.getBoundingClientRect();
      return { countLeft: countBox.left, countRight: countBox.right, countBottom: countBox.bottom, noteLeft: noteBox.left, noteRight: noteBox.right, cardTop: cardBox.top, documentWidth: document.documentElement.scrollWidth, viewportWidth: document.documentElement.clientWidth };
    });
    expect(geometry).not.toBeNull();
    expect(geometry!.countLeft).toBeGreaterThanOrEqual(geometry!.noteLeft);
    expect(geometry!.countRight).toBeLessThanOrEqual(geometry!.noteRight);
    expect(geometry!.countBottom).toBeLessThanOrEqual(geometry!.cardTop);
    expect(geometry!.documentWidth).toBeLessThanOrEqual(geometry!.viewportWidth);
  });

  test('registration accepts a real test-domain address and returns to catalog', async ({ page }) => {
    const email = `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
    await page.goto(`${storefront}/register`);
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill('E2eTestPass-2026!');
    await page.locator('input[name="passwordConfirmation"]').fill('E2eTestPass-2026!');
    const registration = page.waitForResponse((response) => response.url().includes('/api/auth/register'));
    await page.locator('form button[type="submit"]').click();
    expect((await registration).status()).toBe(201);
    await expect(page).toHaveURL(`${storefront}/catalog`);
    const mainNavigation = page.getByRole('navigation', { name: 'Основная навигация' });
    if (page.viewportSize()!.width > 880) {
      await expect(mainNavigation.getByRole('link', { name: 'Аккаунт' })).toHaveAttribute('href', '/account');
    } else {
      await expect(mainNavigation).toBeHidden();
    }
    await expect(page.getByRole('link', { name: 'Личный кабинет' })).toHaveAttribute('href', '/account');
  });

  test('guest cart merges and checkout blocks honestly when no delivery quote exists', async ({ page }) => {
    const email = `e2e-merge-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
    await page.goto(`${storefront}/catalog`);
    const addToCart = page.locator('.product-cart-button:not([disabled])').first();
    await addToCart.waitFor();
    const cartMutation = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await addToCart.click();
    const cartMutationResponse = await cartMutation;
    expect(cartMutationResponse.status()).toBe(200);
    const guestCartAfterAdd = await cartMutationResponse.json();
    expect(guestCartAfterAdd.items?.length ?? 0).toBeGreaterThan(0);
    expect(guestCartAfterAdd.items[0]?.sku_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

    await page.goto(`${storefront}/register`);
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill('E2eMergePass-2026!');
    await page.locator('input[name="passwordConfirmation"]').fill('E2eMergePass-2026!');
    const registration = page.waitForResponse((response) => response.url().includes('/api/auth/register'));
    await page.locator('form button[type="submit"]').click();
    expect((await registration).status()).toBe(201);
    // Registration performs the server-side login and then redirects the
    // browser to the catalog. Wait for that navigation before opening
    // checkout; otherwise mobile/tablet runs can race two navigations and
    // abort the checkout document before the merged cart is loaded.
    await expect(page).toHaveURL(`${storefront}/catalog`);

    await page.goto(`${storefront}/checkout`);
    const total = page.locator('.checkout-summary-total strong');
    await expect(total).toBeVisible();
    await expect(total).not.toHaveText(/^(0|0,00|0 ₽)/);

    await page.goto(`${storefront}/account/addresses`);
    const addressInputs = page.locator('input');
    await expect(addressInputs.nth(0)).toBeEnabled();
    await expect(addressInputs.nth(1)).toBeEnabled();
    await addressInputs.nth(0).fill('E2E warehouse');
    await addressInputs.nth(1).fill('Moscow, Test street 1');
    const addressResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/addresses') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Добавить адрес' }).click();
    expect((await addressResponse).status()).toBe(201);

    await page.goto(`${storefront}/checkout`);
    await expect(page.locator('.checkout-address-card')).toHaveCount(1);
    await expect(page.locator('.checkout-item-image-missing')).toHaveAccessibleName(/Фото товара/);
    await expect(page.locator('.checkout-item-image img')).toHaveCount(0);
    const checkoutItem = page.locator('.checkout-item').first();
    await expect(checkoutItem.locator('.checkout-item-meta')).not.toContainText(/[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i);
    const originalTotal = await page.locator('.checkout-summary-total strong').innerText();
    const increaseQuantity = checkoutItem.getByRole('button', { name: /Увеличить количество/ });
    const increaseRequest = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items/') && response.request().method() === 'PATCH');
    await increaseQuantity.click();
    expect((await increaseRequest).status()).toBe(200);
    await expect(checkoutItem.locator('.checkout-item-qty')).toContainText('2');
    await expect(page.locator('.checkout-summary-total strong')).not.toHaveText(originalTotal);
    const decreaseQuantity = checkoutItem.getByRole('button', { name: /Уменьшить количество/ });
    const decreaseRequest = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items/') && response.request().method() === 'PATCH');
    await decreaseQuantity.click();
    expect((await decreaseRequest).status()).toBe(200);
    await expect(checkoutItem.locator('.checkout-item-qty')).toContainText('1');
    await expect(page.locator('.checkout-summary-total strong')).toHaveText(originalTotal);
    const addressRadio = page.getByRole('radiogroup', { name: 'Сохранённые адреса' }).getByRole('radio');
    await expect(addressRadio).toBeChecked();
    await expect(page.locator('[data-testid="checkout-step-address"]')).toHaveClass(/done/);
    await expect(page.locator('[data-testid="checkout-step-delivery"]')).toHaveClass(/current/);
    await expect(page.locator('#checkout-cart')).toBeVisible();
    await expect(page.locator('#checkout-address')).toBeVisible();
    await expect(page.locator('#checkout-delivery')).toBeVisible();
    await expect(page.locator('#checkout-payment')).toBeVisible();
    await page.locator('.checkout-payment-confirm input[type="checkbox"]').check();
    await expect(page.locator('[data-testid="checkout-step-payment"]')).toHaveClass(/done/);
    await page.getByRole('link', { name: /03\. Получение/ }).click();
    await expect(page).toHaveURL(/#checkout-delivery$/);
    await expect(page.locator('.checkout-delivery-blocked')).toContainText('Расчёт доставки недоступен');
    await expect(page.locator('.checkout-delivery-blocked')).toContainText('стоимость и срок доставки');
    await expect(page.locator('.checkout-summary-row').filter({ hasText: 'Доставка' })).toContainText('Не рассчитана');
    await expect(page.locator('.checkout-summary-total')).toContainText('СУММА БЕЗ ДОСТАВКИ');
    await expect(page.getByText(/СДЭК|1–2 рабочих дня|LOCK_TTL: VALID/)).toHaveCount(0);
    const checkoutPosts: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/storefront/checkout/attempts') && request.method() === 'POST') checkoutPosts.push(request.url());
    });
    await expect(page.locator('.checkout-primary-cta')).toBeDisabled();
    expect(checkoutPosts).toHaveLength(0);
    const removeRequest = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items/') && response.request().method() === 'DELETE');
    await checkoutItem.getByRole('button', { name: /Удалить .* из корзины/ }).click();
    expect((await removeRequest).status()).toBe(200);
    await expect(page.locator('.checkout-item')).toHaveCount(0);
    await expect(page.locator('.checkout-summary-total strong')).toContainText('0');
  });

  test('favorites search, stock filter, grid/table switch, cart add and persistent removal use the live B2C API', async ({ page }) => {
    const email = `e2e-favorites-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
    await page.goto(`${storefront}/register`);
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill('E2eFavoritesPass-2026!');
    await page.locator('input[name="passwordConfirmation"]').fill('E2eFavoritesPass-2026!');
    const registration = page.waitForResponse((response) => response.url().includes('/api/auth/register') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Создать аккаунт' }).click();
    expect((await registration).status()).toBe(201);
    await expect(page).toHaveURL(`${storefront}/catalog`);

    const firstProduct = page.locator('.product-card').first();
    const productTitle = (await firstProduct.locator('h3').innerText()).trim();
    const favoriteRequest = page.waitForResponse((response) => response.url().includes('/api/storefront/favorites/') && response.request().method() === 'POST');
    await firstProduct.getByRole('button', { name: `Добавить ${productTitle} в избранное` }).click();
    expect((await favoriteRequest).status()).toBe(201);

    const favoritesLoad = page.waitForResponse((response) => response.url().includes('/api/storefront/favorites?') && response.request().method() === 'GET');
    await page.goto(`${storefront}/favorites`);
    const favoritePayload = await (await favoritesLoad).json() as { items?: Array<{ product?: { price_minor?: number | null; min_price_minor?: number | null; skus?: Array<{ price_minor?: number | null; active_quantity?: number; is_active?: boolean }> } }> };
    const card = page.locator('.favorite-supply-card');
    await expect(card).toHaveCount(1);
    await expect(page.getByRole('link', { name: 'Избранное, 1 товар' })).toBeVisible();
    await expect(card.first()).toContainText(productTitle);
    // Internal product/SKU UUIDs identify API records, but are not customer-facing articles.
    await expect(card.first()).not.toContainText(/[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i);
    const favoriteProduct = favoritePayload.items?.[0]?.product;
    const favoriteSku = favoriteProduct?.skus?.find((sku) => sku.is_active === true && (sku.active_quantity ?? 0) > 0);
    const canonicalFavoritePrice = favoriteSku?.price_minor ?? favoriteProduct?.min_price_minor ?? favoriteProduct?.price_minor;
    expect(Number.isSafeInteger(canonicalFavoritePrice)).toBeTruthy();
    const expectedFavoritePrice = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(canonicalFavoritePrice! / 100);
    await expect(card.first().locator('.favorite-price strong')).toHaveText(expectedFavoritePrice);
    const favoritesSearch = page.getByRole('searchbox', { name: 'Поиск в избранном' });
    if (page.viewportSize()!.width > 600) {
      await favoritesSearch.fill(productTitle);
      await expect(card).toHaveCount(1);
    } else {
      // The approved mobile composition hides the desktop header search.
      await expect(favoritesSearch).toBeHidden();
    }
    await page.getByRole('button', { name: /В наличии \(1\)/ }).click();
    await expect(card).toHaveCount(1);
    await page.getByRole('button', { name: 'Спецификация' }).click();
    await expect(page.locator('.favorites-list')).toHaveClass(/is-table/);
    await page.getByRole('button', { name: 'Сетка' }).click();
    await expect(page.locator('.favorites-list')).not.toHaveClass(/is-table/);

    const addToCart = card.getByRole('button', { name: 'В корзину' });
    const cartMutation = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await addToCart.click();
    expect((await cartMutation).status()).toBe(200);
    await expect(page.getByRole('status')).toContainText(`${productTitle} добавлен в корзину.`);

    const remove = card.getByRole('button', { name: new RegExp(`Удалить ${productTitle} из избранного`) });
    const removal = page.waitForResponse((response) => response.url().includes('/api/storefront/favorites/') && response.request().method() === 'DELETE');
    await remove.click();
    expect((await removal).status()).toBe(204);
    await expect(page.getByRole('heading', { name: 'В избранном пока нет товаров' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Избранное, 0 товаров' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'В избранном пока нет товаров' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Избранное' })).toBeVisible();
  });

  test('cart quantity, remove and clear actions persist authoritative snapshots', async ({ page }) => {
    await page.goto(`${storefront}/catalog`);
    const add = page.locator('.product-cart-button:not([disabled])').first();
    await add.waitFor();
    const addResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await add.click();
    const addedSnapshot = await addResponse;
    expect(addedSnapshot.status()).toBe(200);
    expect((await addedSnapshot.json()).items?.length ?? 0).toBeGreaterThan(0);

    await page.goto(`${storefront}/cart`);
    await expect(page.locator('.cart-item')).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const initialTotal = await page.locator('.cart-summary-total strong').textContent();
    const quantity = page.locator('.nm-quantity-stepper').first();
    const plus = quantity.getByRole('button', { name: /увеличить/i });
    if (await plus.isEnabled()) {
      const plusResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items/') && response.request().method() === 'PATCH');
      await plus.click();
      expect((await plusResponse).status()).toBe(200);
      await expect(quantity.locator('input')).toHaveValue('2');
      await expect(page.locator('.cart-summary-total strong')).not.toHaveText(initialTotal ?? '');
    } else {
      await expect(quantity.locator('input')).toHaveValue('1');
    }

    const removeResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items/') && response.request().method() === 'DELETE');
    await page.locator('.cart-item').first().getByRole('button', { name: /удалить/i }).click();
    expect((await removeResponse).status()).toBe(200);
    await expect(page.locator('.cart-empty-panel')).toBeVisible();

    await page.goto(`${storefront}/catalog`);
    const addAgain = page.locator('.product-cart-button:not([disabled])').first();
    await addAgain.waitFor();
    const addAgainResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await addAgain.click();
    expect((await addAgainResponse).status()).toBe(200);
    await page.goto(`${storefront}/cart`);
    await expect(page.locator('.cart-item')).toHaveCount(1);
    const clearResponse = page.waitForResponse((response) => response.url().endsWith('/api/storefront/cart') && response.request().method() === 'DELETE');
    await page.locator('.cart-clear-button').click();
    expect((await clearResponse).status()).toBe(204);
    await expect(page.locator('.cart-empty-panel')).toBeVisible();
  });

  test('an already-open cart tab refreshes after another tab changes the server cart', async ({ page, context }) => {
    await page.goto(`${storefront}/cart`);
    await expect(page.locator('.cart-empty-panel')).toBeVisible();

    const cartTab = await context.newPage();
    await cartTab.goto(`${storefront}/cart`);
    await expect(cartTab.locator('.cart-empty-panel')).toBeVisible();

    await page.bringToFront();
    await page.goto(`${storefront}/catalog`);
    const add = page.locator('.product-cart-button:not([disabled])').first();
    await add.waitFor();
    const addResponse = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await add.click();
    expect((await addResponse).status()).toBe(200);

    await expect(cartTab.locator('.cart-item')).toHaveCount(1);
    await expect(cartTab.locator('.cart-empty-panel')).toHaveCount(0);
    const clearResponse = cartTab.waitForResponse((response) => response.url().endsWith('/api/storefront/cart') && response.request().method() === 'DELETE');
    await cartTab.locator('.cart-clear-button').click();
    expect((await clearResponse).status()).toBe(204);
    await expect(cartTab.locator('.cart-empty-panel')).toBeVisible();
    await cartTab.close();
  });

  test('product, private checkout and legal routes remain navigable', async ({ page, request }) => {
    const catalog = await (await request.get(`${storefront}/bff/catalog?limit=1`)).json();
    const productId = catalog.items?.[0]?.id;
    expect(productId).toBeTruthy();
    const cartSnapshotPromise = page.waitForResponse((response) => response.url().endsWith('/api/storefront/cart') && response.request().method() === 'GET');
    await page.goto(`${storefront}/product/${productId}`);
    await expect(page.locator('.product-detail-page')).toBeVisible();
    await expect(page.locator('.product-detail-page h1').first()).toBeVisible();
    const cartSnapshotResponse = await cartSnapshotPromise;
    expect(cartSnapshotResponse.status()).toBe(200);
    const initialCart = await cartSnapshotResponse.json() as { items_count?: number };
    await expect(page.getByRole('link', { name: `Корзина, ${initialCart.items_count ?? 0} товаров` })).toBeVisible();
    const detailResponse = await request.get(`${storefront}/api/storefront/products/${productId}`);
    expect(detailResponse.status()).toBe(200);
    const detail = await detailResponse.json();
    expect((await page.title()).match(/NeoMarket/g) ?? []).toHaveLength(1);
    expect(Number.isSafeInteger(detail.min_price_minor)).toBeTruthy();
    const formattedCanonicalPrice = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: detail.currency ?? 'RUB', maximumFractionDigits: 0 }).format(detail.min_price_minor / 100);
    await expect(page.locator('.detail-price')).toHaveText(formattedCanonicalPrice);
    const quantityBefore = await page.locator('.product-buy-button').innerText();
    await page.getByRole('button', { name: /Количество: увеличить/ }).click();
    await expect(page.locator('.product-buy-button')).not.toHaveText(quantityBefore);
    await expect(page.getByRole('button', { name: /В корзину/ })).toBeEnabled();
    const productCartMutation = page.waitForResponse((response) => response.url().includes('/api/storefront/cart/items') && response.request().method() === 'POST');
    await page.getByRole('button', { name: /В корзину/ }).click();
    const productCartResponse = await productCartMutation;
    expect([200, 201]).toContain(productCartResponse.status());
    const updatedCart = await productCartResponse.json() as { items_count?: number };
    await expect(page.getByRole('link', { name: `Корзина, ${updatedCart.items_count ?? 0} товаров` })).toBeVisible();
    await expect(page.getByRole('status')).toContainText('Товар добавлен');
    await page.goto(`${storefront}/checkout`);
    await expect(page).toHaveURL(/\/login\?next=%2Fcheckout$/);
    await page.goto(`${storefront}/legal/terms`);
    await expect(page.getByRole('heading').first()).toBeVisible();
  });

  test('catalog heart adds and removes the same favorite immediately', async ({ page }) => {
    const email = `e2e-catalog-favorite-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
    await page.goto(`${storefront}/register`);
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill('E2eCatalogFavoritePass-2026!');
    await page.locator('input[name="passwordConfirmation"]').fill('E2eCatalogFavoritePass-2026!');
    const registration = page.waitForResponse((response) => response.url().includes('/api/auth/register') && response.request().method() === 'POST');
    await page.locator('button[type="submit"]').click();
    expect((await registration).status()).toBe(201);

    await page.goto(`${storefront}/catalog`);
    const card = page.locator('.product-card').first();
    const productId = await card.getAttribute('data-product-id');
    expect(productId).toBeTruthy();
    const heart = card.locator('.product-favorite-button');
    await expect(heart).toHaveAttribute('aria-pressed', 'false');
    const added = page.waitForResponse((response) => response.url().includes(`/api/storefront/favorites/${productId}`) && response.request().method() === 'POST');
    await heart.click();
    expect((await added).status()).toBe(201);
    await expect(heart).toHaveAttribute('aria-pressed', 'true');

    const removed = page.waitForResponse((response) => response.url().includes(`/api/storefront/favorites/${productId}`) && response.request().method() === 'DELETE');
    await heart.click();
    expect((await removed).status()).toBe(204);
    await expect(heart).toHaveAttribute('aria-pressed', 'false');
    await page.goto(`${storefront}/favorites`);
    await expect(page.locator('.favorites-list .empty-state')).toBeVisible();
    await expect(page.locator('.favorite-supply-card')).toHaveCount(0);
  });

  test('product favorite toggle persists on the server and survives reload', async ({ page, request }) => {
    const catalog = await (await request.get(`${storefront}/bff/catalog?limit=1`)).json();
    const productId = catalog.items?.[0]?.id;
    expect(productId).toBeTruthy();
    const email = `e2e-product-favorite-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
    await page.goto(`${storefront}/register`);
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill('E2eProductFavoritePass-2026!');
    await page.locator('input[name="passwordConfirmation"]').fill('E2eProductFavoritePass-2026!');
    const registration = page.waitForResponse((response) => response.url().includes('/api/auth/register') && response.request().method() === 'POST');
    await page.getByRole('button', { name: /Создать аккаунт/ }).click();
    expect((await registration).status()).toBe(201);
    const favoritesLoad = page.waitForResponse((response) => response.url().includes('/api/storefront/favorites?') && response.request().method() === 'GET');
    await page.goto(`${storefront}/product/${productId}`);
    expect((await favoritesLoad).status()).toBe(200);
    await expect(page.getByRole('link', { name: 'Избранное, 0 товаров' })).toBeVisible();
    const favoriteButton = page.getByRole('button', { name: 'Добавить в избранное' });
    const addFavorite = page.waitForResponse((response) => response.url().includes(`/api/storefront/favorites/${productId}`) && response.request().method() === 'POST');
    await favoriteButton.click();
    expect((await addFavorite).status()).toBe(201);
    await expect(page.getByRole('link', { name: 'Избранное, 1 товаров' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Удалить из избранного' })).toHaveAttribute('aria-pressed', 'true');
    await page.reload();
    const removeFavoriteButton = page.getByRole('button', { name: 'Удалить из избранного' });
    await expect(removeFavoriteButton).toHaveAttribute('aria-pressed', 'true');
    const removeFavorite = page.waitForResponse((response) => response.url().includes(`/api/storefront/favorites/${productId}`) && response.request().method() === 'DELETE');
    await removeFavoriteButton.click();
    expect((await removeFavorite).status()).toBe(204);
    await expect(page.getByRole('button', { name: 'Добавить в избранное' })).toHaveAttribute('aria-pressed', 'false');
  });
});

test.describe('seller protected flows', () => {
  test('seller allocations render from the owner-scoped B2B projection', async ({ page }, testInfo) => {
    await page.goto(`${seller}/login?next=%2Forders`);
    await page.getByLabel('Рабочий email').fill(sellerQaEmail);
    await page.getByLabel('Пароль').fill(sellerQaPassword);
    await page.getByRole('button', { name: 'Войти в Seller Hub' }).click();
    await expect(page).toHaveURL(/\/orders$/);

    const ordersResponse = page.waitForResponse((response) => response.url().includes('/api/seller/orders?') && response.request().method() === 'GET');
    await page.reload();
    const listResponse = await ordersResponse;
    expect(listResponse.status()).toBe(200);
    const listBody = await page.evaluate(async () => (await fetch('/api/seller/orders?limit=50', { cache: 'no-store' })).json());
    if (listBody.items.length === 0) {
      await expect(page.getByRole('heading', { name: 'Пока нет распределённых заказов' })).toBeVisible();
      return;
    }
    for (const order of listBody.items) expect(order).not.toHaveProperty('buyer_order_id');
    const firstAllocation = page.locator('.seller-orders-table tbody tr').first();
    await expect(firstAllocation).toBeVisible();
    const detailResponse = page.waitForResponse((response) => /\/api\/seller\/orders\/[0-9a-f-]+$/i.test(new URL(response.url()).pathname) && response.request().method() === 'GET');
    await firstAllocation.getByRole('link').click();
    expect((await detailResponse).status()).toBe(200);
    const detailBody = await page.evaluate(async (path) => (await fetch(path, { cache: 'no-store' })).json(), `/api/seller/orders/${new URL(page.url()).pathname.split('/').pop()}`);
    expect(detailBody).not.toHaveProperty('buyer_order_id');
    expect(detailBody).not.toHaveProperty('address');
    expect(detailBody).not.toHaveProperty('contact');
    await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/i);
    await expect(page.getByRole('heading', { name: 'Allocation' })).toBeVisible();
    await expect(page.getByText('CREATED · оплата не подтверждена')).toBeVisible();
    await expect(page.getByText('Получатель')).toHaveCount(0);
    await expect(page.getByText('Адрес доставки')).toHaveCount(0);
    if (testInfo.project.name === 'mobile-chromium') {
      const logoutLayout = await page.locator('.seller-logout').evaluate((button) => ({
        position: getComputedStyle(button).position,
        top: button.getBoundingClientRect().top,
        contentBottom: document.querySelector('.seller-app')!.getBoundingClientRect().bottom,
      }));
      expect(logoutLayout.position).toBe('static');
      expect(logoutLayout.top).toBeGreaterThanOrEqual(logoutLayout.contentBottom - 1);
    }
    await page.screenshot({ path: resolve(process.cwd(), `../docs/automation/evidence/seller-order-detail-${testInfo.project.name}.png`), fullPage: true });
  });

  test('seller creates and replays an atomic 20-variant product draft', async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.route('**/api/seller/categories', async (route) => {
      const response = await route.fetch();
      const payload = await response.json() as { items: Array<Record<string, unknown>> };
      payload.items[0].attribute_schema = [{ key: 'manufacturer', label: 'Manufacturer', required: true, value_type: 'text', options: [], allowed_units: [] }];
      await route.fulfill({
        status: response.status(),
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
    });
    await page.goto(`${seller}/login?next=%2Fproducts%2Fnew`);
    await page.getByLabel('Рабочий email').fill(sellerQaEmail);
    await page.getByLabel('Пароль').fill(sellerQaPassword);
    await page.getByRole('button', { name: /Войти/ }).click();
    await expect(page).toHaveURL(/\/products\/new$/);
    const category = page.locator('[name="categoryId"]');
    await expect(category).toBeEnabled();
    await category.selectOption({ index: 1 });
    await page.getByLabel('Manufacturer *').fill('ExampleCo');
    const runTag = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    const title = `=1+1 ${runTag}`;
    const maliciousSkuName = `@SUM(1,1) ${runTag}-0`;
    await page.locator('[name="title"]').fill(title);
    await page.locator('[name="description"]').fill('Playwright verification of the atomic 20-variant seller draft.');
    for (let index = 1; index < 20; index += 1) await page.getByRole('button', { name: 'Добавить вариант' }).click();
    await expect(page.getByRole('heading', { name: 'Варианты SKU (20/100)' })).toBeVisible();
    const variantForm = page.locator('.seller-section fieldset');
    for (let index = 0; index < 20; index += 1) {
      const variant = variantForm.nth(index);
      await variant.getByLabel('Артикул продавца').fill(`SKU-${runTag}-${index}`);
      await variant.getByLabel('Название SKU').fill(index === 0 ? maliciousSkuName : `Atomic SKU ${runTag}-${index}`);
      await variant.getByLabel('Цена').fill('125.50');
      await variant.getByLabel('Остаток').fill(String(index + 4));
      if (index === 0) await variant.getByLabel('Параметры варианта (JSON)').fill('{"color":"black"}');
    }

    const requestPromise = page.waitForRequest((request) => request.url().endsWith('/api/seller/v1/products/drafts') && request.method() === 'POST');
    const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/seller/v1/products/drafts') && response.request().method() === 'POST');
    await page.locator('.seller-form button[type="submit"]').click();
    const [createRequest, createResponse] = await Promise.all([requestPromise, responsePromise]);
    expect(createResponse.status()).toBe(201);
    expect(createRequest.postDataJSON().attributes).toEqual({ manufacturer: 'ExampleCo' });
    const idempotencyKey = createRequest.headers()['idempotency-key'];
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
    const created = await page.evaluate(async (key) => {
      const response = await fetch(`/api/seller/v1/products/drafts/${key}`, { credentials: 'include', cache: 'no-store' });
      return { status: response.status, body: await response.json() };
    }, idempotencyKey) as { status: number; body: { id: string; operation_id: string; status: string; variants: Array<{ id: string; seller_article: string; name: string; price_minor: number; currency: string; on_hand: number; options: Record<string, string> }> } };
    expect(created.status).toBe(200);
    const draft = created.body;
    expect(draft.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(draft.operation_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(draft.status).toBe('DRAFT');
    expect(draft.variants).toHaveLength(20);
    expect(draft.variants[0]).toMatchObject({ seller_article: `SKU-${runTag}-0`, name: maliciousSkuName, price_minor: 12550, currency: 'RUB', on_hand: 4, options: { color: 'black' } });
    await expect(page.getByRole('status')).toContainText('Черновик сохранён: 20 вариантов.');
    await page.screenshot({ path: resolve(process.cwd(), `../../docs/automation/evidence/seller-atomic-product-${testInfo.project.name}-2026-10-16.png`), fullPage: true });

    const persisted = await page.evaluate(async (productId) => {
      const response = await fetch(`/api/seller/products/${productId}`, { cache: 'no-store' });
      return { status: response.status, etag: response.headers.get('etag'), body: await response.json() };
    }, draft.id) as { status: number; etag: string | null; body: { id: string; title: string; revision: number; skus: Array<{ id: string; article: string; price_minor: number; currency: string; stock_quantity: number; characteristics: Array<{ name: string; value: string }> }> } };
    expect(persisted.status).toBe(200);
    expect(persisted.etag).toBe('"1"');
    expect(persisted.body).toMatchObject({ id: draft.id, title, revision: 1 });
    expect(persisted.body.skus).toHaveLength(20);
    const persistedFirst = persisted.body.skus.find((sku) => sku.id === draft.variants[0].id);
    expect(persistedFirst).toMatchObject({ article: `SKU-${runTag}-0`, price_minor: 12550, currency: 'RUB', stock_quantity: 4, characteristics: [{ name: 'color', value: 'black' }] });

    const csrf = await page.evaluate(async () => {
      const response = await fetch('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' });
      return await response.json() as { token: string };
    });
    const replay = await page.evaluate(async ({ csrfToken, key, body }) => {
      const response = await fetch('/api/seller/v1/products/drafts', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key }, body: JSON.stringify(body) });
      return { status: response.status, body: await response.json() };
    }, { csrfToken: csrf.token, key: idempotencyKey, body: createRequest.postDataJSON() });
    expect(replay.status).toBe(201);
    expect((replay.body as { id: string; operation_id: string }).id).toBe(draft.id);
    expect((replay.body as { id: string; operation_id: string }).operation_id).toBe(draft.operation_id);
    const originalPayload = createRequest.postDataJSON();
    const conflictingReplay = await page.evaluate(async ({ csrfToken, key, body }) => {
      const response = await fetch('/api/seller/v1/products/drafts', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'Idempotency-Key': key }, body: JSON.stringify(body) });
      return response.status;
    }, { csrfToken: csrf.token, key: idempotencyKey, body: { ...originalPayload, description: 'different intent' } });
    expect(conflictingReplay).toBe(409);

    const freshEdit = await page.evaluate(async ({ csrfToken, productId }) => {
      const response = await fetch(`/api/seller/products/${productId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'If-Match': '"1"' }, body: JSON.stringify({ description: 'Seller edited this product at revision one.' }) });
      return { status: response.status, body: await response.json() };
    }, { csrfToken: csrf.token, productId: draft.id });
    expect(freshEdit.status).toBe(200);
    expect((freshEdit.body as { revision: number }).revision).toBe(2);
    const staleEdit = await page.evaluate(async ({ csrfToken, productId }) => {
      const response = await fetch(`/api/seller/products/${productId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'If-Match': '"1"' }, body: JSON.stringify({ description: 'This stale update must not be saved.' }) });
      return response.status;
    }, { csrfToken: csrf.token, productId: draft.id });
    expect(staleEdit).toBe(412);
    const afterStaleEdit = await page.evaluate(async (productId) => {
      const response = await fetch(`/api/seller/products/${productId}`, { cache: 'no-store' });
      return { etag: response.headers.get('etag'), body: await response.json() as { description: string; revision: number } };
    }, draft.id);
    expect(afterStaleEdit).toMatchObject({ etag: '"2"', body: { description: 'Seller edited this product at revision one.', revision: 2 } });

    const approvedTicketId = crypto.randomUUID();
    const approvedActorId = crypto.randomUUID();
    const approval = await page.request.post(`${sellerBackend}/internal/v1/events/moderation`, {
      headers: { 'X-Service-Key': sellerServiceKey },
      data: {
        schema_version: 1,
        event_id: crypto.randomUUID(),
        event_type: 'moderation.approved',
        producer: 'admin',
        aggregate_type: 'moderation_ticket',
        aggregate_id: approvedTicketId,
        aggregate_version: 1,
        occurred_at: new Date().toISOString(),
        correlation_id: crypto.randomUUID(),
        payload: { product_id: draft.id, reviewed_revision: 2, decision_id: crypto.randomUUID(), ticket_id: approvedTicketId, actor_id: approvedActorId, action: 'APPROVE' },
      },
    });
    expect(approval.status()).toBe(202);
    const publicBeforeEdit = await page.request.get(`${sellerBackend}/products/${draft.id}`, { headers: { 'X-Service-Key': sellerServiceKey } });
    expect(publicBeforeEdit.status()).toBe(200);
    const publishedBeforeEdit = await publicBeforeEdit.json() as { description: string };
    expect(publishedBeforeEdit.description).toBe('Seller edited this product at revision one.');
    const pendingEdit = await page.evaluate(async ({ csrfToken, productId }) => {
      const response = await fetch(`/api/seller/products/${productId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'If-Match': '"2"' }, body: JSON.stringify({ description: 'Unapproved seller change must not appear publicly.' }) });
      return { status: response.status, body: await response.json() as { revision: number; status: string } };
    }, { csrfToken: csrf.token, productId: draft.id });
    expect(pendingEdit).toMatchObject({ status: 200, body: { revision: 3, status: 'ON_MODERATION' } });
    const publicDuringReview = await page.request.get(`${sellerBackend}/products/${draft.id}`, { headers: { 'X-Service-Key': sellerServiceKey } });
    expect(publicDuringReview.status()).toBe(200);
    expect((await publicDuringReview.json() as { description: string }).description).toBe('Seller edited this product at revision one.');

    const ticketId = crypto.randomUUID();
    const moderationActorId = crypto.randomUUID();
    const moderation = await page.request.post(`${sellerBackend}/internal/v1/events/moderation`, {
      headers: { 'X-Service-Key': sellerServiceKey },
      data: {
        schema_version: 1,
        event_id: crypto.randomUUID(),
        event_type: 'moderation.blocked',
        producer: 'admin',
        aggregate_type: 'moderation_ticket',
        aggregate_id: ticketId,
        aggregate_version: 1,
        occurred_at: new Date().toISOString(),
        correlation_id: crypto.randomUUID(),
        payload: { product_id: draft.id, reviewed_revision: 3, decision_id: crypto.randomUUID(), ticket_id: ticketId, actor_id: moderationActorId, action: 'BLOCK', reason_code: 'FIELD_CORRECTION', comment: 'Correct the product description.', field_reports: [{ field_path: '/description', reason_code: 'DESCRIPTION_MISMATCH', comment: 'Please clarify the product description.' }] },
      },
    });
    expect(moderation.status(), await moderation.text()).toBe(202);
    const moderationHistory = await page.evaluate(async (productId) => {
      const response = await fetch(`/api/seller/products/${productId}/moderation`, { cache: 'no-store' });
      return { status: response.status, body: await response.json() as { status: string; items: Array<{ action: string; status: string; reviewed_revision: number; ticket_id: string; actor_id: string; reason_code: string; comment: string; field_reports: Array<{ field_name: string; reason_code: string; comment: string }> }> } };
    }, draft.id);
    expect(moderationHistory.status).toBe(200);
    expect(moderationHistory.body.status).toBe('BLOCKED');
    expect(moderationHistory.body.items[0]).toMatchObject({ action: 'BLOCK', status: 'BLOCKED', reviewed_revision: 3, ticket_id: ticketId, actor_id: moderationActorId, reason_code: 'FIELD_CORRECTION', comment: 'Correct the product description.', field_reports: [{ field_name: '/description', reason_code: 'DESCRIPTION_MISMATCH', comment: 'Please clarify the product description.' }] });
    expect(moderationHistory.body.items[1]).toMatchObject({ action: 'APPROVE', status: 'MODERATED', reviewed_revision: 2, ticket_id: approvedTicketId, actor_id: approvedActorId });
    await page.goto(`${seller}/moderation`);
    await page.getByRole('button', { name: 'Показать историю решений' }).first().click();
    const timeline = page.locator(`#moderation-history-${draft.id}`);
    await expect(timeline).toContainText('BLOCK');
    await expect(timeline).toContainText('Проверенная версия: 3');
    await expect(timeline).toContainText('FIELD_CORRECTION');
    await expect(timeline).toContainText('Please clarify the product description.');
    const timelineEvidence = resolve(process.cwd(), '../docs/automation/seller_runs/2026-10-18/ui-12-moderation-timeline/screenshots');
    await mkdir(timelineEvidence, { recursive: true });
    await timeline.screenshot({ path: resolve(timelineEvidence, `moderation-timeline-${testInfo.project.name}.png`) });
    await page.goto(`${seller}/products/${draft.id}`);
    await expect(page.getByRole('heading', { name: 'Correct rejected fields' })).toBeVisible();
    await expect(page.getByText('/description · DESCRIPTION_MISMATCH')).toBeVisible();
    await page.getByLabel('Description').fill('Corrected seller description after moderation feedback.');
    await page.getByRole('button', { name: 'Submit corrections for review' }).click();
    await expect(page.getByRole('status')).toContainText('Corrections saved. The new revision was sent for moderation.');
    const resubmitted = await page.evaluate(async (productId) => {
      const response = await fetch(`/api/seller/products/${productId}`, { cache: 'no-store' });
      return { status: response.status, etag: response.headers.get('etag'), body: await response.json() as { status: string; revision: number; description: string } };
    }, draft.id);
    expect(resubmitted).toMatchObject({ status: 200, etag: '"5"', body: { status: 'ON_MODERATION', revision: 5, description: 'Corrected seller description after moderation feedback.' } });

    const [stockKey, nextStockKey] = await page.evaluate(() => [crypto.randomUUID(), crypto.randomUUID()]);
    const stockUrl = `/api/seller/skus/${draft.variants[0].id}/stock-adjustments`;
    const postFromPage = async (key: string, data: { delta: number; reason: string }) => page.evaluate(async ({ csrfToken, url, idempotencyKey, payload }) => {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(payload) });
      return { status: response.status, body: await response.json() };
    }, { csrfToken: csrf.token, url: stockUrl, idempotencyKey: key, payload: data });
    const firstAdjustment = await postFromPage(stockKey, { delta: 2, reason: 'Playwright cycle count' });
    expect(firstAdjustment.status).toBe(200);
    expect((firstAdjustment.body as { stock_quantity: number }).stock_quantity).toBe(6);
    const secondAdjustment = await postFromPage(nextStockKey, { delta: 3, reason: 'Playwright second count' });
    expect(secondAdjustment.status).toBe(200);
    expect((secondAdjustment.body as { stock_quantity: number }).stock_quantity).toBe(9);
    const stockReplay = await postFromPage(stockKey, { delta: 2, reason: 'Playwright cycle count' });
    expect(stockReplay.status).toBe(200);
    expect((stockReplay.body as { stock_quantity: number }).stock_quantity).toBe(6);
    const stockConflict = await postFromPage(stockKey, { delta: 7, reason: 'Playwright changed count' });
    expect(stockConflict.status).toBe(409);

    await page.goto(`${seller}/inventory`);
    await page.locator('#inventory-search').fill(maliciousSkuName);
    await page.locator('.seller-search button[type="submit"]').click();
    const persistedInventoryCard = page.locator('.inventory-card').filter({ hasText: maliciousSkuName });
    await expect(persistedInventoryCard).toContainText('9');
    const adjustmentUrl = `**/api/seller/skus/${draft.variants[0].id}/stock-adjustments`;
    const statusResponsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/seller/inventory/adjustments/') && response.request().method() === 'GET');
    await page.route(adjustmentUrl, async (route) => {
      const committed = await route.fetch();
      expect(committed.status()).toBe(200);
      await route.fulfill({ status: 503, contentType: 'application/problem+json', body: '{"title":"Upstream response was lost"}' });
    }, { times: 1 });
    await persistedInventoryCard.locator('input[name="delta"]').fill('1');
    await persistedInventoryCard.locator('input[name="reason"]').fill('Playwright lost response');
    await persistedInventoryCard.locator('form').getByRole('button').click();
    expect((await statusResponsePromise).status()).toBe(200);
    await expect(persistedInventoryCard).toContainText('10');
    await page.reload();
    await page.locator('#inventory-search').fill(maliciousSkuName);
    await page.locator('.seller-search button[type="submit"]').click();
    await expect(persistedInventoryCard).toContainText('10');
    await page.screenshot({ path: resolve(process.cwd(), `../../docs/automation/evidence/seller-inventory-csv-${testInfo.project.name}-2026-10-16.png`), fullPage: true });
    await page.getByRole('button', { name: /CSV/ }).click();
    const csvLink = page.getByRole('link', { name: 'Скачать CSV' });
    await expect(csvLink).toBeVisible({ timeout: 90_000 });
    const csvDownloadPromise = page.waitForEvent('download');
    await csvLink.click();
    const csvDownload = await csvDownloadPromise;
    const csvPath = await csvDownload.path();
    expect(csvPath).not.toBeNull();
    const csvText = await readFile(csvPath as string, 'utf8');
    expect(csvText).toContain(`'=1+1 ${runTag}`);
    expect(csvText).toContain(`"'@SUM(1,1) ${runTag}-0"`);

    const cleanup = await page.evaluate(async ({ csrfToken, productId }) => {
      const response = await fetch(`/api/seller/products/${productId}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrfToken } });
      return response.status;
    }, { csrfToken: csrf.token, productId: draft.id });
    expect(cleanup).toBe(202);
  });
  test('seller inventory bounds the stock adjustment reason to the API limit', async ({ page }) => {
    await page.goto(`${seller}/login?next=%2Finventory`);
    await page.getByLabel('Рабочий email').fill(sellerQaEmail);
    await page.getByLabel('Пароль').fill(sellerQaPassword);
    await page.getByRole('button', { name: /Войти/ }).click();
    await expect(page).toHaveURL(/\/inventory$/);
    const reason = page.getByLabel('Причина').first();
    await expect(reason).toHaveAttribute('maxlength', '64');
    await expect(reason).toHaveAttribute('minlength', '3');
  });

  test('seller inventory loads a bounded owner-scoped page and server metrics', async ({ page }) => {
    await page.goto(`${seller}/login?next=%2Finventory`);
    await page.locator('#seller-email').fill(sellerQaEmail);
    await page.locator('#seller-password').fill(sellerQaPassword);
    const inventoryResponsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/seller/inventory?') && response.request().method() === 'GET');
    const metricsResponsePromise = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/dashboard/metrics') && response.request().method() === 'GET');
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/inventory$/);

    const response = await inventoryResponsePromise;
    expect(response.status()).toBe(200);
    const payload = await response.json() as {
      items: Array<{ sku_id: string; product_title: string; sku_name: string; stock_quantity: number; active_quantity: number }>;
      page: { has_more: boolean; next_cursor?: string | null };
    };
    const summaryResponse = await metricsResponsePromise;
    expect(summaryResponse.status()).toBe(200);
    const summary = await summaryResponse.json() as {
      metrics: { sku_count: number; total_on_hand: number; reserved_stock: number; available_stock: number };
      as_of: string;
    };
    expect(payload.items.length).toBeLessThanOrEqual(50);
    expect(summary.metrics.sku_count).toBeGreaterThanOrEqual(payload.items.length);
    expect(Number.isNaN(Date.parse(summary.as_of))).toBe(false);
    if (payload.page.has_more) expect(payload.page.next_cursor).toBeTruthy();
    if (payload.items.length) {
      await expect(page.locator('.inventory-card')).toHaveCount(payload.items.length);
      await expect(page.locator('.inventory-card').first()).toContainText(payload.items[0].product_title);
      await expect(page.locator('.inventory-card').first()).toContainText(payload.items[0].sku_name);
    }
    await expect(page.locator('.seller-inventory-summary')).toContainText(String(summary.metrics.sku_count));
    await expect(page.locator('.seller-muted')).toContainText('Сводка на');
    if (payload.page.has_more) await expect(page.getByRole('button', { name: 'Дальше' })).toBeEnabled();
    else await expect(page.getByRole('button', { name: 'Дальше' })).toBeDisabled();

    const backendFlow = await page.evaluate(async () => {
      const firstResponse = await fetch('/api/seller/inventory?limit=1', { cache: 'no-store' });
      const first = await firstResponse.json() as { items: Array<{ sku_id: string }>; page: { next_cursor?: string | null } };
      const cursor = first.page.next_cursor;
      const secondResponse = cursor
        ? await fetch(`/api/seller/inventory?limit=1&cursor=${encodeURIComponent(cursor)}`, { cache: 'no-store' })
        : null;
      const second = secondResponse?.ok ? await secondResponse.json() as { items: Array<{ sku_id: string }> } : null;
      const mismatchedCursorResponse = cursor
        ? await fetch(`/api/seller/inventory?limit=1&query=changed&cursor=${encodeURIComponent(cursor)}`, { cache: 'no-store' })
        : null;
      const metricsResponse = await fetch('/api/seller/dashboard/metrics', { cache: 'no-store' });
      const metrics = metricsResponse.ok ? await metricsResponse.json() as { metrics: { sku_count: number; available_stock: number }; as_of: string } : null;
      return {
        firstStatus: firstResponse.status,
        firstSku: first.items[0]?.sku_id,
        secondStatus: secondResponse?.status,
        secondSku: second?.items[0]?.sku_id,
        mismatchedCursorStatus: mismatchedCursorResponse?.status,
        metricsStatus: metricsResponse.status,
        metrics,
      };
    });
    expect(backendFlow.firstStatus).toBe(200);
    if (backendFlow.secondStatus !== undefined) {
      expect(backendFlow.secondStatus).toBe(200);
      expect(backendFlow.secondSku).not.toBe(backendFlow.firstSku);
      expect(backendFlow.mismatchedCursorStatus).toBe(422);
    }
    expect(backendFlow.metricsStatus).toBe(200);
    expect(backendFlow.metrics?.metrics.sku_count).toBe(summary.metrics.sku_count);
    expect(Number.isNaN(Date.parse(backendFlow.metrics?.as_of ?? ''))).toBe(false);
    const viewportName = test.info().project.name.replace(/-chromium$/, '');
    await page.screenshot({
      path: resolve(process.cwd(), '../docs/automation/evidence/seller-inventory-cursor-' + viewportName + '-2026-10-16.png'),
      fullPage: true,
    });
    if (payload.items.length) {
      const searchTerm = payload.items[0].product_title;
      const searchResponsePromise = page.waitForResponse((item) =>
        item.url().includes('/api/seller/inventory?') && item.url().includes('query=') && item.request().method() === 'GET');
      await page.locator('#inventory-search').fill(searchTerm);
      await page.getByRole('button', { name: 'Найти' }).click();
      const searchResponse = await searchResponsePromise;
      expect(searchResponse.status()).toBe(200);
      const filtered = await searchResponse.json() as { items: Array<{ product_title: string }> };
      expect(filtered.items.length).toBeGreaterThan(0);
      expect(filtered.items.every((item) => item.product_title.toLocaleLowerCase('ru').includes(searchTerm.toLocaleLowerCase('ru')))).toBe(true);

      const statusResponsePromise = page.waitForResponse((item) =>
        item.url().includes('/api/seller/inventory?') && item.url().includes('status=available') && item.request().method() === 'GET');
      await page.locator('#inventory-status').selectOption('available');
      const statusResponse = await statusResponsePromise;
      expect(statusResponse.status()).toBe(200);
      const available = await statusResponse.json() as { items: Array<{ is_active: boolean; active_quantity: number }> };
      expect(available.items.every((item) => item.is_active && item.active_quantity > 0)).toBe(true);
    }
  });

  test('seller CSV import previews without changing stock and restores its persisted report', async ({ page }) => {
    await page.goto(`${seller}/login?next=%2Finventory`);
    await page.locator('#seller-email').fill(sellerQaEmail);
    await page.locator('#seller-password').fill(sellerQaPassword);
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/inventory$/);

    const fixture = await page.evaluate(async () => {
      const response = await fetch('/api/seller/inventory?limit=100', { cache: 'no-store' });
      if (!response.ok) throw new Error(`inventory request failed: ${response.status}`);
      const payload = await response.json() as { items: Array<{ seller_article?: string | null; stock_quantity: number }> };
      const sku = payload.items.find((item) => item.seller_article);
      if (!sku?.seller_article) throw new Error('live seller inventory has no SKU article for a no-op count');
      return { seller_article: sku.seller_article, stock: sku.stock_quantity };
    });
    await page.goto(`${seller}/imports`);
    await page.getByLabel('Stock count CSV').setInputFiles({
      name: 'inventory-count.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(`seller_article,on_hand\n${fixture.seller_article},${fixture.stock}\nUNKNOWN-${Date.now()},1\n`),
    });
    const previewResponse = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/imports') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Preview import' }).click();
    expect((await previewResponse).status()).toBe(201);
    await expect(page.getByRole('heading', { name: 'Dry-run preview' })).toBeVisible();
    await expect(page.getByText(/2 rows.*1 valid\/unchanged.*1 errors.*0 applied/)).toBeVisible();
    await expect(page.getByRole('cell', { name: fixture.seller_article })).toBeVisible();
    await expect(page.getByText('No seller SKU matches this article')).toBeVisible();

    const afterPreview = await page.evaluate(async (article) => {
      const response = await fetch('/api/seller/inventory?limit=100', { cache: 'no-store' });
      const payload = await response.json() as { items: Array<{ seller_article?: string | null; stock_quantity: number }> };
      return payload.items.find((item) => item.seller_article === article)?.stock_quantity;
    }, fixture.seller_article);
    expect(afterPreview).toBe(fixture.stock);

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Dry-run preview' })).toBeVisible();
    const commitResponse = page.waitForResponse((response) =>
      /\/api\/seller\/imports\/[^/]+$/.test(response.url()) && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Commit valid rows' }).click();
    expect((await commitResponse).status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Import result' })).toBeVisible();
    await expect(page.locator('.status-badge').filter({ hasText: 'PARTIAL' })).toBeVisible();
    await expect(page.getByText(/2 rows.*1 valid\/unchanged.*1 errors.*0 applied/)).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Import result' })).toBeVisible();
    await page.evaluate(() => {
      sessionStorage.removeItem('seller.inventoryImportJobId');
      sessionStorage.removeItem('seller.inventoryImportPreviewKey');
      sessionStorage.removeItem('seller.inventoryImportCommitKey');
    });
  });

  test('seller dashboard shows live SKU rows and its stock controls filter and select', async ({ page }) => {
    await page.goto(`${seller}/login?next=%2Fdashboard`);
    await expect(page.getByRole('button', { name: 'Выйти' })).toHaveCount(0);
    await page.getByLabel('Рабочий email').fill(sellerQaEmail);
    await page.getByLabel('Пароль').fill(sellerQaPassword);
    const metricsResponsePromise = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/dashboard/metrics') && response.request().method() === 'GET');
    await page.getByRole('button', { name: 'Войти в Seller Hub' }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    const metricsResponse = await metricsResponsePromise;
    expect(metricsResponse.status()).toBe(200);
    const serverMetrics = await metricsResponse.json() as {
      metrics: { live_products: number; sku_count: number; available_stock: number; reserved_stock: number };
      as_of: string;
    };
    const metricCards = page.locator('.seller-dashboard-metrics article');
    await expect(metricCards.nth(0).locator('strong')).toHaveText(serverMetrics.metrics.live_products.toLocaleString('ru-RU'));
    await expect(metricCards.nth(1).locator('strong')).toHaveText(serverMetrics.metrics.sku_count.toLocaleString('ru-RU'));
    await expect(metricCards.nth(2).locator('strong')).toHaveText(serverMetrics.metrics.available_stock.toLocaleString('ru-RU'));
    await expect(metricCards.nth(3).locator('strong')).toHaveText(serverMetrics.metrics.reserved_stock.toLocaleString('ru-RU'));
    expect(Number.isNaN(Date.parse(serverMetrics.as_of))).toBe(false);
    await expect(page.locator('.seller-dashboard-content > .seller-muted')).toContainText('Сводка B2B API на');

    const rows = page.locator('.seller-stock-table tbody tr');
    await expect(rows.first()).toBeVisible();
    const totalRows = await rows.count();
    expect(totalRows).toBeGreaterThan(0);
    await expect(rows).toHaveCount(6);
    await expect(rows.first().locator('td').nth(1)).toBeVisible();
    const logoutButton = page.getByRole('button', { name: 'Выйти', exact: true });
    await expect(logoutButton).toBeVisible();
    await expect(page.getByRole('button', { name: 'Выйти везде' })).toBeVisible();
    const testViewportWidth = await page.evaluate(() => window.innerWidth);
    const detailPanel = page.locator('.seller-stock-detail');
    if (testViewportWidth > 1180) await expect(detailPanel).toHaveCSS('position', 'sticky');
    else await expect(detailPanel).toHaveCSS('position', 'static');
    if (testViewportWidth > 680) expect(await logoutButton.evaluate((button) => getComputedStyle(button).top)).toBe('22px');
    else expect(await logoutButton.evaluate((button) => getComputedStyle(button).bottom)).toBe('20px');
    const pagination = page.getByRole('navigation', { name: 'Страницы складских позиций' });
    await expect(pagination).toContainText(/1 \/ \d+/);
    const pageCount = Number((await pagination.innerText()).match(/1 \/ (\d+)/)?.[1] ?? 0);
    expect(pageCount).toBeGreaterThan(1);
    const firstPageProduct = await rows.first().locator('.seller-stock-product').innerText();
    const firstPageVariant = await rows.first().locator('.seller-stock-variant').innerText();
    await pagination.getByRole('button', { name: 'Следующая страница' }).click();
    await expect(pagination).toContainText('2 /');
    await expect(rows).toHaveCount(6);
    await expect(rows.first().locator('.seller-stock-product')).toHaveText(firstPageProduct);
    await expect(rows.first().locator('.seller-stock-variant')).not.toHaveText(firstPageVariant);
    await pagination.getByRole('button', { name: 'Предыдущая страница' }).click();
    await expect(pagination).toContainText('1 /');
    if (testViewportWidth > 680) {
      await page.evaluate(() => window.scrollTo(0, 900));
      await expect.poll(() => page.locator('.seller-topbar').evaluate((header) => Math.round(header.getBoundingClientRect().top))).toBe(0);
      await page.evaluate(() => window.scrollTo(0, 0));
    } else {
      await expect(page.locator('.seller-topbar')).toHaveCSS('position', 'static');
    }
    const thumbnails = page.locator('.seller-stock-thumb[role="img"]');
    await expect(thumbnails).toHaveCount(totalRows);
    expect(await page.locator('.seller-stock-thumb-empty').evaluateAll((icons) => icons.every((icon) => icon.tagName.toLowerCase() === 'svg' && icon.textContent?.trim() === ''))).toBeTruthy();
    await expect(thumbnails.first()).toHaveAttribute('aria-label', /^Фото товара/);
    const viewportName = test.info().project.name.replace(/-chromium$/, '');
    await page.screenshot({
      path: resolve(process.cwd(), '../docs/automation/seller_runs/2026-10-18/dashboard-full-export-link', `dashboard-${viewportName}.png`),
      fullPage: true,
    });
    const imageCount = await page.locator('.seller-stock-thumb img').count();
    const placeholderCount = await page.locator('.seller-stock-thumb-empty').count();
    expect(imageCount + placeholderCount).toBe(totalRows);
    if (imageCount > 0) {
      const firstSkuImage = await page.locator('.seller-stock-thumb img').first().getAttribute('src');
      expect(firstSkuImage).toBeTruthy();
    }

    const availableFilter = page.getByRole('button', { name: /В наличии/ });
    const fullExportLink = page.locator('.seller-dashboard-actions a');
    await expect(fullExportLink).toHaveAttribute('href', '/inventory');
    await fullExportLink.click();
    await expect(page).toHaveURL(/\/inventory$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(rows.first()).toBeVisible();

    await availableFilter.click();
    await expect(availableFilter).toHaveAttribute('aria-pressed', 'true');
    expect(await rows.count()).toBeLessThanOrEqual(totalRows);

    await page.getByRole('button', { name: /Все SKU/ }).click();
    const skuName = await page.locator('.seller-stock-variant').first().innerText();
    await page.getByLabel('Поиск по названию или артикулу').fill(skuName);
    await expect(rows.first()).toBeVisible();
    await page.locator('.seller-row-select').first().click();
    await expect(page.locator('.seller-stock-detail h2')).toContainText(skuName);
    await page.getByLabel('Сортировка').selectOption('available');

    const viewport = page.viewportSize();
    const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, document: document.documentElement.scrollWidth }));
    expect(widths.body).toBeLessThanOrEqual(viewport!.width);
    expect(widths.document).toBeLessThanOrEqual(viewport!.width);
    const tableWidths = await page.locator('.seller-stock-table-wrap').evaluate((element) => ({ client: element.clientWidth, content: element.scrollWidth }));
    if (testViewportWidth <= 1440) expect(tableWidths.content).toBeGreaterThan(tableWidths.client);
    else expect(tableWidths.content).toBeLessThanOrEqual(tableWidths.client);

    const categoriesRequest = page.waitForResponse((response) => response.url().endsWith('/api/seller/categories') && response.request().method() === 'GET');
    await page.goto(`${seller}/products/new`);
    const categoriesResponse = await categoriesRequest;
    expect(categoriesResponse.status()).toBe(200);
    const categoriesPayload = await categoriesResponse.json() as { items?: Array<{ id: string; name: string }> };
    const categorySelect = page.locator('[name="categoryId"]');
    await expect(categorySelect).toBeEnabled();
    await expect(categorySelect.locator('option')).toHaveCount((categoriesPayload.items?.length ?? 0) + 1);
    for (const category of categoriesPayload.items ?? []) await expect(categorySelect.locator(`option[value="${category.id}"]`)).toHaveText(category.name);
    const formHeading = page.locator('.page-heading h1');
    await expect(formHeading).toBeVisible();
    expect(await formHeading.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThanOrEqual(60);
    await expect(page.locator('.page-heading > .seller-product-link')).toHaveCSS('white-space', 'nowrap');
    await expect(categorySelect).toHaveCSS('border-style', 'solid');
    expect(await categorySelect.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(48);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport!.width);
  });

  test('seller logout-all clears the BFF cookie and revokes the previous JWT', async ({ page }) => {
    test.skip(!sessionQaEmail || !sessionQaPassword, 'requires a dedicated disposable seller session fixture');
    await page.goto(`${seller}/login?next=%2Fdashboard`);
    await page.locator('input[name="username"]').fill(sessionQaEmail!);
    await page.locator('input[name="password"]').fill(sessionQaPassword!);
    const loginResponsePromise = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/auth/login') && response.request().method() === 'POST');
    await page.locator('#login-form button[type="submit"]').click();
    const loginResponse = await loginResponsePromise;
    await expect(page).toHaveURL(/dashboard$/);

    const cookies = await page.context().cookies();
    const accessCookie = cookies.find((cookie) => /^(?:__Host-)?nm_seller_access$/.test(cookie.name));
    const oldToken = accessCookie?.value;
    expect(oldToken, `login=${loginResponse.status()} set-cookie=${loginResponse.headers()['set-cookie']?.split(';')[0] ?? 'none'} url=${page.url()}; cookies=${cookies.map((cookie) => `${cookie.name}@${cookie.domain}`).join(',')}`).toBeTruthy();
    const logoutResponse = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/auth/logout-all') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Выйти везде', exact: true }).click();
    expect((await logoutResponse).status()).toBe(200);
    await expect(page).toHaveURL(/login/);

    const oldTokenResponse = await page.request.get(`${sellerBackend}/auth/me`, {
      headers: { Authorization: `Bearer ${oldToken}` },
    });
    expect(oldTokenResponse.status()).toBe(401);
    expect((await page.context().cookies()).some((cookie) => /^(?:__Host-)?nm_seller_access$/.test(cookie.name))).toBe(false);
  });

  test('seller login replaces an access cookie supplied before authentication', async ({ page, context }) => {
    test.skip(!sessionQaEmail || !sessionQaPassword, 'requires a dedicated disposable seller session fixture');
    const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
    await context.addCookies([{
      name: cookieName,
      value: 'stale-pre-authentication-cookie',
      url: seller,
      httpOnly: true,
      sameSite: 'Lax',
    }]);

    await page.goto(`${seller}/login?next=%2Fdashboard`);
    await page.locator('input[name="username"]').fill(sessionQaEmail!);
    await page.locator('input[name="password"]').fill(sessionQaPassword!);
    const loginResponsePromise = page.waitForResponse((response) =>
      response.url().endsWith('/api/seller/auth/login') && response.request().method() === 'POST');
    await page.locator('#login-form button[type="submit"]').click();
    const loginResponse = await loginResponsePromise;
    expect(loginResponse.status()).toBe(200);
    await expect(page).toHaveURL(/dashboard$/);

    const accessCookie = (await context.cookies()).find((cookie) => cookie.name === cookieName);
    expect(accessCookie?.value).toBeTruthy();
    expect(accessCookie?.value).not.toBe('stale-pre-authentication-cookie');
    const remainingLifetimeMs = accessCookie!.expires * 1000 - Date.now();
    expect(remainingLifetimeMs).toBeGreaterThan(14 * 60 * 1000);
    expect(remainingLifetimeMs).toBeLessThanOrEqual(15 * 60 * 1000);
    const sessionResponse = await page.request.get(`${seller}/api/seller/auth/session`);
    expect(sessionResponse.status()).toBe(200);
  });

  test('seller login accepts the exact local origin and rejects cross-site form posts', async ({ request }) => {
    const localRequest = await request.post(`${seller}/api/seller/auth/login`, {
      headers: { Origin: seller },
      form: { username: 'invalid@qa.local', password: 'invalid-for-origin-check' },
    });
    expect(localRequest.status()).not.toBe(403);

    const crossSiteRequest = await request.post(`${seller}/api/seller/auth/login`, {
      headers: { Origin: 'https://attacker.example', 'Sec-Fetch-Site': 'cross-site' },
      form: { username: 'invalid@qa.local', password: 'invalid-for-origin-check' },
    });
    expect(crossSiteRequest.status()).toBe(403);
  });

  test('all frontend shells enforce CSP instead of report-only mode', async ({ request }) => {
    for (const origin of [storefront, seller, admin]) {
      const response = await request.get(`${origin}/`);
      expect(response.ok()).toBeTruthy();
      expect(response.headers()['content-security-policy']).toContain("default-src 'self'");
      expect(response.headers()['content-security-policy-report-only']).toBeUndefined();
    }
  });

  test('login and protected pages fail closed without a session', async ({ page }) => {
    await page.goto(`${seller}/login`);
    await expect(page.locator('input').first()).toBeVisible();
    for (const path of ['/dashboard', '/products', '/inventory', '/moderation']) {
      await page.goto(`${seller}${path}`);
      await expect(page.getByRole('heading').first()).toBeVisible();
    }
    await page.context().addCookies([{ name: 'nm_seller_access', value: 'forged-token', domain: '127.0.0.1', path: '/' }]);
    await page.goto(`${seller}/dashboard`);
    await expect(page).toHaveURL(/\/login(?:\?|$)/);
  });

  test('seller stock mutation rejects missing CSRF token', async ({ request }) => {
    const response = await request.post(`${seller}/api/seller/skus/00000000-0000-4000-8000-000000000000/stock-adjustments`, {
      headers: {
        Origin: seller,
        Cookie: 'nm_seller_access=forged-token',
        'Idempotency-Key': '00000000-0000-4000-8000-000000000001',
      },
      data: { delta: 1, reason: 'qa' },
    });
    expect(response.status()).toBe(403);
  });

  test('seller product mutations reject missing CSRF token', async ({ request }) => {
    const product = await request.post(`${seller}/api/seller/products`, { headers: { Origin: seller, Cookie: 'nm_seller_access=forged-token' }, data: { title: 'QA', description: 'QA', category_id: '00000000-0000-4000-8000-000000000000', images: [{ url: 'https://example.com/qa.png' }] } });
    expect(product.status()).toBe(403);
    const atomicProduct = await request.post(`${seller}/api/seller/products/with-first-sku`, {
      headers: { Origin: seller, Cookie: 'nm_seller_access=forged-token', 'Idempotency-Key': '00000000-0000-4000-8000-000000000001' },
      data: { product: { title: 'QA', description: 'QA', category_id: '00000000-0000-4000-8000-000000000000', images: [{ url: 'https://example.com/qa.png' }] }, first_sku: { name: 'QA SKU', price: 1, stock: 1, images: [{ url: 'https://example.com/qa.png' }] } },
    });
    expect(atomicProduct.status()).toBe(403);
    const sku = await request.post(`${seller}/api/seller/products/00000000-0000-4000-8000-000000000000/skus`, { headers: { Origin: seller, Cookie: 'nm_seller_access=forged-token' }, data: { product_id: '00000000-0000-4000-8000-000000000000', name: 'QA', price: 1, stock: 1, images: [{ url: 'https://example.com/qa.png' }] } });
    expect(sku.status()).toBe(403);
    const logout = await request.post(`${seller}/api/seller/auth/logout`, { headers: { Origin: seller, Cookie: 'nm_seller_access=forged-token' } });
    expect(logout.status()).toBe(403);
  });
});

test.describe('admin protected flows', () => {
  test('OIDC/MFA gate is visible and admin pages do not expose data', async ({ page }) => {
    await page.goto(`${admin}/login`);
    await expect(page.getByRole('heading').first()).toBeVisible();
    await page.goto(`${admin}/moderation`);
    await expect(page.getByRole('heading').first()).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/L-Gauge Ultra-Z|FlowValve 300|ShieldCable M12|DEMO DATA/);
    for (const path of ['/audit', '/reasons']) {
      await page.goto(`${admin}${path}`);
      await expect(page.getByRole('heading').first()).toBeVisible();
    }
  });

  test('admin forged cookie cannot open privileged routes', async ({ page }) => {
    await page.context().addCookies([{ name: 'nm_admin_access', value: 'forged-token', domain: '127.0.0.1', path: '/' }]);
    await page.goto(`${admin}/moderation`);
    await expect(page).toHaveURL(/\/unauthorized(?:\?|$)/);
  });
});
