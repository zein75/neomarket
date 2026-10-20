export type Currency = 'RUB' | 'EUR' | 'USD';
export type ProductAvailability = 'available' | 'unavailable' | 'removed';

export interface ProductCardDto {
  id: string;
  /** Canonical SKU UUID used by cart mutations; never display this to shoppers. */
  skuId?: string;
  /** Seller-facing article, when the authoritative catalog provides one. */
  skuArticle?: string;
  title: string;
  description?: string;
  category: string;
  priceMinor: number;
  currency: Currency;
  imageUrl?: string;
  availability: ProductAvailability;
  stockLabel?: string;
  availableQuantity?: number;
}

export interface ProductDetailDto { id?: string; skuId?: string; skus?: Array<{ id?: unknown; article?: string | null; name?: string | null; price?: unknown; price_minor?: number | null; in_stock?: unknown; available_quantity?: unknown; images?: unknown[] }>; title: string; description?: string; category?: string; characteristics?: Record<string, unknown>; image?: string; images?: unknown[]; price?: number; min_price?: number | null; price_minor?: number | null; min_price_minor?: number | null; currency?: Currency; in_stock?: boolean; has_stock?: boolean; availability?: ProductAvailability; }
export interface CategoryDetailDto { id?: string; name: string; description?: string; product_count?: number; }

export function isProductDetailDto(value: unknown): value is ProductDetailDto {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  const hasValidCurrency = candidate.currency === undefined || ['RUB', 'EUR', 'USD'].includes(String(candidate.currency));
  const priceValues = [candidate.price_minor, candidate.min_price_minor, ...(Array.isArray(candidate.skus) ? candidate.skus.map((sku) => sku && typeof sku === 'object' ? (sku as Record<string, unknown>).price_minor : undefined) : [])];
  const hasValidPrices = priceValues.every((price) => price === undefined || price === null || (typeof price === 'number' && Number.isSafeInteger(price) && price >= 0));
  const hasSafeImage = candidate.image === undefined || (typeof candidate.image === 'string' && (candidate.image.startsWith('/') || candidate.image.startsWith('https://')));
  const hasAvailabilitySignal = candidate.availability !== undefined || candidate.in_stock !== undefined || candidate.has_stock !== undefined;
  const title = candidate.title ?? candidate.name;
  return (candidate.id === undefined || (typeof candidate.id === 'string' && candidate.id.trim().length > 0)) && typeof title === 'string' && title.trim().length > 0 && hasSafeImage && hasValidPrices && hasValidCurrency && hasAvailabilitySignal && (candidate.in_stock === undefined || typeof candidate.in_stock === 'boolean') && (candidate.has_stock === undefined || typeof candidate.has_stock === 'boolean') && (candidate.availability === undefined || ['available', 'unavailable', 'removed'].includes(String(candidate.availability)));
}

export function normalizeProductDetail(value: ProductDetailDto): ProductDetailDto {
  const firstSku = value.skus?.find((sku) => typeof sku.id === 'string');
  const firstImage = Array.isArray(value.images) ? value.images.find((image) => typeof image === 'string' || (image && typeof image === 'object' && typeof (image as { url?: unknown }).url === 'string')) : undefined;
  const image = typeof firstImage === 'string' ? firstImage : firstImage && typeof firstImage === 'object' && typeof (firstImage as { url?: unknown }).url === 'string' ? (firstImage as { url: string }).url : value.image;
  const price = typeof value.price === 'number' ? value.price : typeof value.min_price === 'number' ? value.min_price : typeof firstSku?.price === 'number' ? firstSku.price : undefined;
  const inStock = typeof value.in_stock === 'boolean' ? value.in_stock : typeof value.has_stock === 'boolean' ? value.has_stock : firstSku?.in_stock === true;
  return { ...value, title: value.title || 'Товар', ...(image ? { image } : {}), ...(price !== undefined ? { price } : {}), in_stock: inStock, availability: value.availability ?? (inStock ? 'available' : 'unavailable') };
}

export function isCategoryDetailDto(value: unknown): value is CategoryDetailDto {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return (candidate.id === undefined || (typeof candidate.id === 'string' && candidate.id.trim().length > 0)) && typeof candidate.name === 'string' && candidate.name.trim().length > 0 && (candidate.description === undefined || typeof candidate.description === 'string') && (candidate.product_count === undefined || (Number.isInteger(candidate.product_count) && Number(candidate.product_count) >= 0));
}

export interface CatalogResponse {
  items: ProductCardDto[];
  nextCursor?: string;
  total?: number;
}

export interface CartItemDto {
  skuId: string;
  productId: string;
  name: string;
  unitPriceMinor: number;
  quantity: number;
  lineTotalMinor: number;
  availableQuantity: number;
  isAvailable: boolean;
  unavailableReason?: 'OUT_OF_STOCK' | 'PRODUCT_BLOCKED' | 'PRODUCT_DELISTED' | 'ON_MODERATION';
  image?: Record<string, unknown> | null;
}

export interface CartDto {
  id?: string;
  items: CartItemDto[];
  itemsCount: number;
  subtotalMinor: number;
  isValid: boolean;
}

export type CartValidationIssueType = 'PRICE_CHANGED' | 'OUT_OF_STOCK' | 'QUANTITY_REDUCED' | 'PRODUCT_BLOCKED' | 'PRODUCT_DELETED';
export interface CartValidationIssue { skuId: string; type: CartValidationIssueType; message: string; oldValue?: string | number; newValue?: string | number; }
export interface CartValidation { isValid: boolean; cart: CartDto; issues: CartValidationIssue[]; }

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  requestId?: string;
}

export type SessionRole = 'buyer' | 'seller' | 'moderator' | 'admin';

export interface SessionResponse {
  authenticated: boolean;
  principal?: { id: string; role: SessionRole; displayName?: string };
}

export function isSessionResponse(value: unknown): value is SessionResponse {
  if (!value || typeof value !== 'object' || typeof (value as { authenticated?: unknown }).authenticated !== 'boolean') return false;
  const principal = (value as { principal?: unknown }).principal;
  if (principal === undefined) return true;
  if (!principal || typeof principal !== 'object') return false;
  const candidate = principal as { id?: unknown; role?: unknown };
  return typeof candidate.id === 'string' && ['buyer', 'seller', 'moderator', 'admin'].includes(String(candidate.role));
}
