import type { CartDto, CartValidation, CatalogResponse, ProblemDetails } from '@neomarket/api-types';

export interface BuyerAddress { id: string; label: string; addressLine: string; }

export class ApiError extends Error {
  constructor(public readonly problem: ProblemDetails) {
    super(problem.title);
  }
}

const baseUrl = process.env.NEOMARKET_BFF_URL ?? '/bff';

export async function getCatalog(signal?: AbortSignal): Promise<CatalogResponse> {
  const response = await fetch(`${baseUrl}/catalog`, {
    ...(signal ? { signal } : {}),
    headers: { Accept: 'application/json' },
    credentials: 'include',
    cache: 'no-store',
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as ProblemDetails | null;
    throw new ApiError(problem ?? { type: 'about:blank', title: 'Catalog unavailable', status: response.status });
  }
  return normalizeCatalogResponse(await response.json());
}

function normalizeCatalogResponse(payload: unknown): CatalogResponse {
  const raw = (payload && typeof payload === 'object' ? payload : {}) as { items?: unknown; nextCursor?: unknown; next_cursor?: unknown; total?: unknown; total_count?: unknown };
  const items = Array.isArray(raw.items) ? raw.items.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const id = value.id;
    const title = value.title;
    const priceMinor = Number(value.priceMinor ?? value.price_minor ?? value.price);
    const currency = value.currency;
    const availability = value.availability;
    if (typeof id !== 'string' || id.trim().length === 0 || typeof title !== 'string' || title.trim().length === 0 || !Number.isFinite(priceMinor) || priceMinor < 0 || !['RUB', 'EUR', 'USD'].includes(String(currency)) || !['available', 'unavailable', 'removed'].includes(String(availability))) return [];
    const imageCandidate = typeof value.imageUrl === 'string' ? value.imageUrl : typeof value.image === 'string' ? value.image : undefined;
    const imageUrl = imageCandidate && (imageCandidate.startsWith('/') || imageCandidate.startsWith('https://')) ? imageCandidate : undefined;
    const stockLabel = typeof value.stockLabel === 'string' && value.stockLabel.trim().length > 0 ? value.stockLabel : undefined;
    const category = typeof value.category === 'string' && value.category.trim().length > 0 ? value.category : 'Каталог';
    return [{ id, title, category, priceMinor, currency: currency as CatalogResponse['items'][number]['currency'], availability: availability as CatalogResponse['items'][number]['availability'], ...(imageUrl ? { imageUrl } : {}), ...(stockLabel ? { stockLabel } : {}) }];
  }) : [];
  const nextCursor = raw.nextCursor ?? raw.next_cursor;
  const total = Number(raw.total ?? raw.total_count);
  return { items, ...(typeof nextCursor === 'string' && nextCursor.length > 0 ? { nextCursor } : {}), ...(Number.isInteger(total) && total >= 0 ? { total } : {}) };
}

export async function getGuestCart(signal?: AbortSignal): Promise<CartDto> {
  const response = await fetch('/api/storefront/cart', { ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart unavailable', status: response.status });
  return normalizeCart(await response.json());
}

export async function addGuestCartItem(skuId: string, quantity: number, csrfToken: string, signal?: AbortSignal): Promise<CartDto> {
  const response = await fetch('/api/storefront/cart/items', { method: 'POST', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ sku_id: skuId, quantity }), cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart item could not be added', status: response.status });
  return normalizeCart(await response.json());
}

export async function clearGuestCart(csrfToken: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch('/api/storefront/cart', { method: 'DELETE', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrfToken }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart could not be cleared', status: response.status });
}

/** Removes one SKU and returns the server's complete, authoritative cart snapshot. */
export async function removeGuestCartItem(itemId: string, csrfToken: string, signal?: AbortSignal): Promise<CartDto> {
  const response = await fetch(`/api/storefront/cart/items/${encodeURIComponent(itemId)}`, { method: 'DELETE', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrfToken }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart item could not be removed', status: response.status });
  return normalizeCart(await response.json());
}

export async function updateGuestCartItem(itemId: string, quantity: number, csrfToken: string, signal?: AbortSignal): Promise<CartDto> {
  const response = await fetch(`/api/storefront/cart/items/${encodeURIComponent(itemId)}`, { method: 'PATCH', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ quantity }), cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart item could not be updated', status: response.status });
  return normalizeCart(await response.json());
}

export async function validateGuestCart(csrfToken: string, signal?: AbortSignal): Promise<CartValidation> {
  const response = await fetch('/api/storefront/cart/validate', { method: 'POST', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrfToken }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Cart validation failed', status: response.status });
  return normalizeCartValidation(await response.json());
}

export async function getBuyerAddresses(signal?: AbortSignal): Promise<BuyerAddress[]> {
  const response = await fetch('/api/storefront/addresses', { ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Addresses unavailable', status: response.status });
  const payload = await response.json().catch(() => null) as unknown;
  if (!Array.isArray(payload)) return [];
  return payload.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>; const id = value.id; const label = value.label; const addressLine = value.address_line ?? value.addressLine;
    return typeof id === 'string' && typeof label === 'string' && typeof addressLine === 'string' ? [{ id, label, addressLine }] : [];
  });
}

export async function createBuyerAddress(input: { label: string; addressLine: string }, csrfToken: string, signal?: AbortSignal): Promise<BuyerAddress> {
  const response = await fetch('/api/storefront/addresses', { method: 'POST', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ label: input.label, address_line: input.addressLine }), cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Address could not be created', status: response.status });
  const value = await response.json() as Record<string, unknown>;
  const id = value.id; const label = value.label; const addressLine = value.address_line ?? value.addressLine;
  if (typeof id !== 'string' || typeof label !== 'string' || typeof addressLine !== 'string') throw new ApiError({ type: 'about:blank', title: 'Invalid address response', status: 502 });
  return { id, label, addressLine };
}

export async function deleteBuyerAddress(addressId: string, csrfToken: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch(`/api/storefront/addresses/${encodeURIComponent(addressId)}`, { method: 'DELETE', ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrfToken }, cache: 'no-store' });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null)) as ProblemDetails ?? { type: 'about:blank', title: 'Address could not be deleted', status: response.status });
}

function normalizeCartValidation(payload: unknown): CartValidation {
  const raw = (payload && typeof payload === 'object' ? payload : {}) as { is_valid?: unknown; isValid?: unknown; cart?: unknown; issues?: unknown };
  const issues = Array.isArray(raw.issues) ? raw.issues.flatMap((issue) => {
    if (!issue || typeof issue !== 'object') return [];
    const value = issue as Record<string, unknown>;
    const skuId = value.sku_id ?? value.skuId;
    const type = value.type;
    const message = value.message;
    if (typeof skuId !== 'string' || typeof type !== 'string' || !['PRICE_CHANGED', 'OUT_OF_STOCK', 'QUANTITY_REDUCED', 'PRODUCT_BLOCKED', 'PRODUCT_DELETED'].includes(type) || typeof message !== 'string') return [];
    const oldValue = value.old_value ?? value.oldValue;
    const newValue = value.new_value ?? value.newValue;
    const isSafeValue = (candidate: unknown): candidate is string | number => typeof candidate === 'string' || (typeof candidate === 'number' && Number.isFinite(candidate));
    return [{ skuId, type: type as CartValidation['issues'][number]['type'], message, ...(isSafeValue(oldValue) ? { oldValue } : {}), ...(isSafeValue(newValue) ? { newValue } : {}) }];
  }) : [];
  const hasCartSnapshot = Boolean(raw.cart && typeof raw.cart === 'object');
  return { isValid: hasCartSnapshot && issues.length === 0 && (raw.is_valid ?? raw.isValid) === true, cart: normalizeCart(raw.cart), issues };
}

function normalizeCart(payload: unknown): CartDto {
  const raw = (payload && typeof payload === 'object' ? payload : {}) as { id?: unknown; items?: unknown; items_count?: unknown; subtotal?: unknown; is_valid?: unknown };
  const items = Array.isArray(raw.items) ? raw.items.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const skuId = value.sku_id ?? value.skuId;
    const productId = value.product_id ?? value.productId;
    if (typeof skuId !== 'string' || skuId.trim().length === 0 || typeof productId !== 'string' || productId.trim().length === 0 || typeof value.name !== 'string' || value.name.trim().length === 0) return [];
    const reasonCandidate = value.unavailable_reason ?? value.unavailableReason;
    const unavailableReason = typeof reasonCandidate === 'string' && ['OUT_OF_STOCK', 'PRODUCT_BLOCKED', 'PRODUCT_DELISTED', 'ON_MODERATION'].includes(reasonCandidate) ? reasonCandidate as CartDto['items'][number]['unavailableReason'] : undefined;
    const isAvailable = value.is_available ?? value.isAvailable;
    const unitPriceMinor = Number(value.unit_price ?? value.unitPriceMinor);
    const quantity = Number(value.quantity);
    const lineTotalMinor = Number(value.line_total ?? value.lineTotalMinor);
    const availableQuantity = Number(value.available_quantity ?? value.availableQuantity);
    if (typeof isAvailable !== 'boolean' || ![unitPriceMinor, quantity, lineTotalMinor, availableQuantity].every(Number.isInteger) || unitPriceMinor < 0 || quantity <= 0 || lineTotalMinor < 0 || availableQuantity < 0) return [];
    const image = value.image === null || value.image === undefined || (typeof value.image === 'object' && !Array.isArray(value.image)) ? value.image ?? null : null;
    return [{ skuId, productId, name: value.name, unitPriceMinor, quantity, lineTotalMinor, availableQuantity, isAvailable, ...(unavailableReason ? { unavailableReason } : {}), image: image as Record<string, unknown> | null }];
  }) : [];
  const source = raw as typeof raw & { itemsCount?: unknown; subtotalMinor?: unknown; isValid?: unknown };
  const itemsCount = Number(raw.items_count ?? source.itemsCount);
  const subtotalMinor = Number(raw.subtotal ?? source.subtotalMinor);
  return { ...(typeof raw.id === 'string' && raw.id.length > 0 ? { id: raw.id } : {}), items, itemsCount: Number.isInteger(itemsCount) && itemsCount >= 0 ? itemsCount : 0, subtotalMinor: Number.isFinite(subtotalMinor) && subtotalMinor >= 0 ? subtotalMinor : 0, isValid: (raw.is_valid ?? source.isValid) === true };
}
