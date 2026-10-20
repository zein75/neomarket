'use client';

import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import type { CartDto, ProductCardDto } from '@neomarket/api-types';
import { addGuestCartItem, clearGuestCart, getBuyerAddresses, getGuestCart, removeGuestCartItem, updateGuestCartItem, validateGuestCart } from '@neomarket/api-client';
import type { BuyerAddress } from '@neomarket/api-client';
import { QuantityStepper } from '@neomarket/ui';
import { ProductCard } from './ProductCard';
import { CartView } from './CartView';
import { announceCartChanged, isCartSyncEvent } from './cart-sync';
import { StorefrontHeader } from './StorefrontHeader';

const products: ProductCardDto[] = [
  { id: 'iot-42', title: 'Промышленный IoT-контроллер N42', category: 'Электроника & IoT', priceMinor: 1299000, currency: 'RUB', imageUrl: '/design-system/catalog.png', availability: 'available', stockLabel: 'На складе: 42 шт.' },
  { id: 'robot-arm', title: 'Манипулятор R-5 / graphite', category: 'Робототехника', priceMinor: 8490000, currency: 'RUB', imageUrl: '/design-system/seller-dashboard.png', availability: 'available', stockLabel: 'Отгрузка за 24 часа' },
  { id: 'modular-desk', title: 'Модульный стол SHIFT 02', category: 'Промышленный дизайн', priceMinor: 2590000, currency: 'RUB', imageUrl: '/design-system/cart-checkout.png', availability: 'available', stockLabel: 'Осталось 6 шт.' },
  { id: 'removed-sku', title: 'Позиция снята с продажи', category: 'Архив', priceMinor: 99000, currency: 'RUB', imageUrl: '/design-system/admin-moderation.png', availability: 'removed', stockLabel: 'Недоступно' },
];

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 });
const productCountRules = new Intl.PluralRules('ru');

function formatProductCount(count: number) {
  const form = productCountRules.select(count);
  return `${count} ${form === 'one' ? 'товар' : form === 'few' ? 'товара' : 'товаров'}`;
}

type CatalogState = 'preview' | 'loading' | 'ready' | 'error';
type CartLoadState = 'preview' | 'loading' | 'ready' | 'error';
type SortOption = 'popularity' | 'price_asc' | 'price_desc' | 'new';
const validationIssueLabels: Record<string, string> = {
  PRICE_CHANGED: 'Цена изменилась',
  OUT_OF_STOCK: 'Товара нет в наличии',
  QUANTITY_REDUCED: 'Количество уменьшено',
  PRODUCT_BLOCKED: 'Товар заблокирован',
  PRODUCT_DELETED: 'Товар удалён',
};
const cartUnavailableLabels: Record<string, string> = {
  OUT_OF_STOCK: 'Нет в наличии',
  PRODUCT_BLOCKED: 'Товар заблокирован',
  PRODUCT_DELISTED: 'Снят с продажи',
  ON_MODERATION: 'На модерации',
};

function normalizeCatalog(payload: unknown): ProductCardDto[] {
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as { items?: unknown }).items)) return [];
  return (payload as { items: unknown[] }).items.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const raw = item as { id?: unknown; sku_id?: unknown; skuId?: unknown; skus?: unknown; title?: string; name?: string; description?: unknown; category?: unknown; image?: unknown; images?: unknown; price_minor?: unknown; min_price_minor?: unknown; currency?: string; availability?: unknown; in_stock?: unknown; has_stock?: unknown };
    const title = typeof raw.title === 'string' ? raw.title : typeof raw.name === 'string' ? raw.name : null;
    if (typeof raw.id !== 'string' || raw.id.trim().length === 0 || title === null || title.trim().length === 0) return [];
    const currency = ['RUB', 'EUR', 'USD'].includes(String(raw.currency)) ? String(raw.currency) : 'RUB';
    if (typeof raw.title !== 'string') raw.title = title;
    if (raw.currency === undefined) raw.currency = currency;
    if (raw.availability !== undefined && !['available', 'unavailable', 'removed'].includes(String(raw.availability))) return [];
    const inStock = typeof raw.in_stock === 'boolean' ? raw.in_stock : typeof raw.has_stock === 'boolean' ? raw.has_stock : undefined;
    if (raw.availability === undefined && inStock === undefined) return [];
    // The public contract uses integer minor units. Do not treat legacy `price`
    // or `min_price` values as trustworthy money: their units are ambiguous.
    const price = typeof raw.price_minor === 'number' ? raw.price_minor : raw.min_price_minor;
    if (typeof price !== 'number' || !Number.isSafeInteger(price) || price < 0) return [];
    const availability = raw.availability as ProductCardDto['availability'] | undefined ?? (inStock === false ? 'unavailable' : 'available');
    const firstImage = Array.isArray(raw.images) ? raw.images.find((entry) => entry && typeof entry === 'object' && typeof (entry as { url?: unknown }).url === 'string') as { url: string } | undefined : undefined;
    const firstSkuImage = Array.isArray(raw.skus) ? raw.skus.flatMap((sku) => sku && typeof sku === 'object' && Array.isArray((sku as { images?: unknown }).images) ? (sku as { images: unknown[] }).images : []).find((entry) => entry && typeof entry === 'object' && typeof (entry as { url?: unknown }).url === 'string') as { url: string } | undefined : undefined;
    const imageCandidate = typeof raw.image === 'string' ? raw.image : firstImage?.url ?? firstSkuImage?.url;
    const image = typeof imageCandidate === 'string' && (imageCandidate.startsWith('/') || imageCandidate.startsWith('https://')) ? imageCandidate : '';
    return [{
      id: raw.id as string,
      title,
      ...(typeof raw.description === 'string' && raw.description.trim() ? { description: raw.description.trim() } : {}),
      category: typeof raw.category === 'string' && raw.category.trim().length > 0 ? raw.category : 'Catalog',
      priceMinor: price as number,
      currency: currency as ProductCardDto['currency'],
      imageUrl: image,
      availability,
      stockLabel: availability === 'removed' ? 'Снято с продажи' : availability === 'unavailable' ? 'Нет в наличии' : 'В наличии',
    } satisfies ProductCardDto];
    /*
    const category = typeof raw.category === 'string' && raw.category.trim().length > 0 ? raw.category : 'Каталог';
    return [{ id: raw.id, title: raw.title, category, priceMinor: price, currency: raw.currency as ProductCardDto['currency'], imageUrl: image, availability, stockLabel: availability === 'removed' ? 'Снято с продажи' : availability === 'unavailable' ? 'Нет в наличии' : 'Доступно по API' } satisfies ProductCardDto];
    */
  });
}

function attachCatalogSkus(items: ProductCardDto[], payload: unknown): ProductCardDto[] {
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as { items?: unknown }).items)) return items;
  const catalogDetails = new Map<string, Pick<ProductCardDto, 'skuId' | 'skuArticle' | 'availableQuantity' | 'stockLabel' | 'availability'>>();
  for (const entry of (payload as { items: unknown[] }).items) {
    if (!entry || typeof entry !== 'object') continue;
    const raw = entry as { id?: unknown; sku_id?: unknown; skuId?: unknown; availability?: unknown; has_stock?: unknown; in_stock?: unknown; skus?: unknown };
    if (typeof raw.id !== 'string') continue;
    const directSkuId = typeof raw.sku_id === 'string' ? raw.sku_id : raw.skuId;
    const skus = Array.isArray(raw.skus) ? raw.skus.filter((sku): sku is Record<string, unknown> => !!sku && typeof sku === 'object') : [];
    const availableSku = skus
      .find((sku) => {
        if (!sku || typeof sku !== 'object') return false;
        const candidate = sku as { id?: unknown; active_quantity?: unknown; available_quantity?: unknown; in_stock?: unknown; is_active?: unknown };
        const activeQuantity = candidate.active_quantity ?? candidate.available_quantity;
        return typeof candidate.id === 'string'
          && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(candidate.id)
          && (typeof activeQuantity === 'number' ? activeQuantity > 0 : candidate.in_stock === true)
          && candidate.is_active !== false;
      });
    // Cart endpoints accept the canonical SKU UUID, never a seller-facing article.
    // Choosing only an actually available SKU also avoids adding a variant the
    // catalog currently marks as exhausted.
    const validDirectSkuId = typeof directSkuId === 'string'
      && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(directSkuId)
      ? directSkuId
      : undefined;
    const skuId = validDirectSkuId ?? (typeof availableSku?.id === 'string' ? availableSku.id : undefined);
    const displaySku = skus.find((sku) => sku.id === skuId) ?? availableSku;
    const quantityValues = skus
      .filter((sku) => sku.is_active !== false)
      .map((sku) => sku.active_quantity ?? sku.available_quantity)
      .filter((quantity): quantity is number => typeof quantity === 'number' && Number.isSafeInteger(quantity) && quantity >= 0);
    const availableQuantity = quantityValues.length ? quantityValues.reduce((total, quantity) => total + quantity, 0) : undefined;
    const isAvailable = raw.has_stock === true || raw.in_stock === true || (availableQuantity !== undefined && availableQuantity > 0);
    const availability: ProductCardDto['availability'] = raw.availability === 'removed'
      ? 'removed'
      : availableQuantity !== undefined
        ? availableQuantity > 0 ? 'available' : 'unavailable'
        : raw.has_stock === false || raw.in_stock === false ? 'unavailable' : 'available';
    const stockLabel = availableQuantity !== undefined
      ? availableQuantity > 0 ? `В наличии: ${availableQuantity} шт.` : 'Нет в наличии'
      : isAvailable ? 'В наличии' : undefined;
    catalogDetails.set(raw.id, {
      ...(skuId?.trim() ? { skuId: skuId.trim() } : {}),
      ...(typeof displaySku?.article === 'string' && displaySku.article.trim() ? { skuArticle: displaySku.article.trim() } : {}),
      ...(availableQuantity !== undefined ? { availableQuantity } : {}),
      availability,
      ...(stockLabel ? { stockLabel } : {}),
    });
  }
  return items.map((item) => {
    const details = catalogDetails.get(item.id);
    return details ? { ...item, ...details } : item;
  });
}

async function fetchCatalogWithRetry(url: string, signal: AbortSignal) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(url, { signal, credentials: 'include', headers: { Accept: 'application/json' } });
      if (response.ok || ![502, 503, 504].includes(response.status) || attempt === 1) return response;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      if (attempt === 1) throw error;
    }
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    await new Promise<void>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout>;
      const onAbort = () => { clearTimeout(timer); signal.removeEventListener('abort', onAbort); reject(new DOMException('Aborted', 'AbortError')); };
      const finish = () => { signal.removeEventListener('abort', onAbort); resolve(); };
      timer = setTimeout(finish, 120 * (attempt + 1));
      signal.addEventListener('abort', onAbort, { once: true });
    });
  }
  throw new Error('catalog_retry_exhausted');
}

export function Storefront({ initialView = 'catalog', initialQuery = '', initialCategory = '', initialSort = 'popularity', initialPage = 1 }: { initialView?: 'catalog' | 'cart' | 'orders' | 'checkout'; initialQuery?: string; initialCategory?: string; initialSort?: SortOption; initialPage?: number }) {
  // Production must never render the local design preview as if it were live data.
  // Preview fixtures are opt-in and development-only. Staging/production must
  // always use the authoritative catalog even if an old live-catalog flag is
  // accidentally carried into the environment.
  const staticPreviewEnabled = process.env.NODE_ENV === 'development' && process.env.NEXT_PUBLIC_ENABLE_STATIC_PREVIEW === 'true';
  const liveCatalogEnabled = !staticPreviewEnabled;
  const [active, setActive] = useState<'catalog' | 'cart' | 'orders' | 'checkout'>(initialView);
  const [query, setQuery] = useState(initialQuery);
  const [category, setCategory] = useState(initialCategory);
  const [categoryId, setCategoryId] = useState('');
  const [catalogFacets, setCatalogFacets] = useState<{ categories: Array<{ id: string; name: string; count: number }>; price?: { min?: number | null; max?: number | null } }>({ categories: [] });
  const [sort, setSort] = useState<SortOption>(initialSort);
  const [availabilityFilter, setAvailabilityFilter] = useState<'all' | 'available' | 'unavailable'>('all');
  const [, setMinRating] = useState(0);
  const [priceCap, setPriceCap] = useState(10000000);
  const [catalogView, setCatalogView] = useState<'grid' | 'list'>('grid');
  const [page, setPage] = useState(Math.min(10000, Math.max(1, initialPage)));
  const [cart, setCart] = useState<Record<string, number>>(() => liveCatalogEnabled ? {} : { 'iot-42': 1, 'modular-desk': 1 });
  const [authoritativeCart, setAuthoritativeCart] = useState<CartDto | null>(null);
  const [cartLoadState, setCartLoadState] = useState<CartLoadState>(liveCatalogEnabled ? 'loading' : 'preview');
  const [cartRetryNonce, setCartRetryNonce] = useState(0);
  const cartRefreshQueued = useRef(false);
  const [notice, setNotice] = useState('');
  const [favoriteIds, setFavoriteIds] = useState<string[]>([]);
  const [favoritePendingIds, setFavoritePendingIds] = useState<string[]>([]);
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);
  const [buyerAuthenticated, setBuyerAuthenticated] = useState<boolean | null>(null);
  const [checkoutPending, setCheckoutPending] = useState(false);
  const [checkoutUnknown, setCheckoutUnknown] = useState(false);
  const [cartMutationPending, setCartMutationPending] = useState(false);
  const [addPendingId, setAddPendingId] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ProductCardDto[]>(liveCatalogEnabled ? [] : products);
  const [catalogState, setCatalogState] = useState<CatalogState>(liveCatalogEnabled ? 'loading' : 'preview');
  const [retryNonce, setRetryNonce] = useState(0);
  const [addresses, setAddresses] = useState<BuyerAddress[]>([]);
  const [addressesLoading, setAddressesLoading] = useState(false);
  const deferredQuery = useDeferredValue(query);
  useEffect(() => {
    if (active !== 'checkout') return;
    let cancelled = false;
    fetch('/api/auth/session', { credentials: 'include', cache: 'no-store' })
      .then(async (response) => {
        const session = await response.json().catch(() => null) as { authenticated?: unknown } | null;
        if ((!response.ok || session?.authenticated !== true) && !cancelled && typeof window !== 'undefined') window.location.assign(`/login?next=${encodeURIComponent('/checkout')}`);
      })
      .catch(() => {
        if (!cancelled && typeof window !== 'undefined') window.location.assign(`/login?next=${encodeURIComponent('/checkout')}`);
      });
    const controller = new AbortController();
    setAddressesLoading(true);
    getBuyerAddresses(controller.signal).then(setAddresses).catch(() => setAddresses([])).finally(() => setAddressesLoading(false));
    return () => { cancelled = true; controller.abort(); };
  }, [active]);
  useEffect(() => {
    if (active !== 'catalog' || typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (query.trim()) params.set('q', query.trim().slice(0, 200)); else params.delete('q');
    if (categoryId.trim()) params.set('category_id', categoryId.trim()); else params.delete('category_id');
    if (sort !== 'popularity') params.set('sort', sort); else params.delete('sort');
    if (page > 1) params.set('page', String(page)); else params.delete('page');
    window.history.replaceState(null, '', `${window.location.pathname}${params.toString() ? `?${params}` : ''}`);
  }, [active, query, categoryId, sort, page]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const syncFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const nextSort = params.get('sort');
      const nextPage = Number(params.get('page'));
      setQuery((params.get('q') ?? '').slice(0, 200));
      setCategory((params.get('category') ?? '').slice(0, 100));
      setCategoryId((params.get('category_id') ?? '').slice(0, 100));
      setSort(nextSort === 'price_asc' || nextSort === 'price_desc' || nextSort === 'new' ? nextSort : 'popularity');
      setPage(Number.isInteger(nextPage) && nextPage >= 1 ? Math.min(10000, nextPage) : 1);
    };
    window.addEventListener('popstate', syncFromUrl);
    return () => window.removeEventListener('popstate', syncFromUrl);
  }, []);
  useEffect(() => {
    if (!liveCatalogEnabled) return;
    fetch('/bff/catalog/facets', { credentials: 'include', cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(async (response) => response.ok ? response.json() : null)
      .then((payload: unknown) => {
        if (!payload || typeof payload !== 'object') return;
        const raw = payload as { categories?: unknown; price?: unknown };
        const categories = Array.isArray(raw.categories) ? raw.categories.flatMap((entry) => {
          if (!entry || typeof entry !== 'object') return [];
          const item = entry as { id?: unknown; name?: unknown; count?: unknown };
          return typeof item.id === 'string' && typeof item.name === 'string' ? [{ id: item.id, name: item.name, count: typeof item.count === 'number' ? item.count : 0 }] : [];
        }) : [];
        const price = raw.price && typeof raw.price === 'object' ? raw.price as { min?: number | null; max?: number | null } : undefined;
        setCatalogFacets(price ? { categories, price } : { categories });
        if (typeof price?.max === 'number' && price.max > 0) setPriceCap((current) => current === 10000000 ? price.max ?? current : current);
      })
      .catch(() => setCatalogFacets({ categories: [] }));
  }, [liveCatalogEnabled]);
  useEffect(() => {
    if (!category.trim()) { setCategoryId(''); return; }
    const match = catalogFacets.categories.find((entry) => entry.name.toLowerCase() === category.trim().toLowerCase());
    if (match && match.id !== categoryId) setCategoryId(match.id);
  }, [category, catalogFacets.categories, categoryId]);
  useEffect(() => {
    if (!liveCatalogEnabled) return;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 5000);
    const params = new URLSearchParams({ limit: '20', offset: String((page - 1) * 20), sort });
    if (deferredQuery.trim()) params.set('q', deferredQuery.trim());
    if (categoryId.trim()) params.set('category_id', categoryId.trim());
    if (availabilityFilter === 'available') params.set('in_stock', 'true');
    if (availabilityFilter === 'unavailable') params.set('in_stock', 'false');
    if (Number.isFinite(priceCap)) params.set('price_max', String(Math.max(0, Math.round(priceCap))));
    setCatalogState('loading');
    fetchCatalogWithRetry(`/bff/catalog?${params.toString()}`, controller.signal)
      .then(async (response) => { if (!response.ok) throw new Error(`catalog_${response.status}`); const payload = await response.json(); return attachCatalogSkus(normalizeCatalog(payload), payload); })
      .then((items) => { setCatalog(items); setCatalogState('ready'); })
      .catch((error: unknown) => { if (error instanceof DOMException && error.name === 'AbortError') { if (timedOut) setCatalogState('error'); return; } setCatalogState('error'); })
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [liveCatalogEnabled, deferredQuery, categoryId, availabilityFilter, priceCap, retryNonce, sort, page]);
  useEffect(() => {
    if (!liveCatalogEnabled) { setCartLoadState('preview'); return; }
    const controller = new AbortController();
    setCartLoadState('loading');
    getGuestCart(controller.signal)
      .then((snapshot) => { setAuthoritativeCart(snapshot); setCart(snapshot.items.reduce<Record<string, number>>((next, item) => { next[item.productId] = item.quantity; return next; }, {})); setCartLoadState('ready'); })
      .catch(() => { if (!controller.signal.aborted) { setAuthoritativeCart(null); setCart({}); setCartLoadState('error'); } });
    return () => controller.abort();
  }, [liveCatalogEnabled, cartRetryNonce]);
  useEffect(() => {
    if (!liveCatalogEnabled) return;
    let disposed = false;
    let inFlight = false;
    let activeController: AbortController | null = null;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    const refreshFromServer = () => {
      if (cartLoadState !== 'ready' || cartMutationPending || inFlight) {
        cartRefreshQueued.current = true;
        return;
      }
      cartRefreshQueued.current = false;
      inFlight = true;
      activeController = new AbortController();
      timeout = setTimeout(() => activeController?.abort(), 5000);
      getGuestCart(activeController.signal)
        .then((snapshot) => {
          if (disposed) return;
          setAuthoritativeCart(snapshot);
          setCart(snapshot.items.reduce<Record<string, number>>((next, item) => {
            next[item.productId] = item.quantity;
            return next;
          }, {}));
          setCartLoadState('ready');
        })
        .catch(() => {
          // Keep the last authoritative snapshot on transient refresh errors.
        })
        .finally(() => {
          if (timeout) clearTimeout(timeout);
          activeController = null;
          inFlight = false;
          if (!disposed && cartRefreshQueued.current && cartLoadState === 'ready' && !cartMutationPending) {
            refreshFromServer();
          }
        });
    };
    const onStorage = (event: StorageEvent) => {
      if (isCartSyncEvent(event)) refreshFromServer();
    };
    const onFocus = () => refreshFromServer();
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshFromServer();
    };

    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibilityChange);
    if (cartRefreshQueued.current && cartLoadState === 'ready' && !cartMutationPending) refreshFromServer();
    return () => {
      disposed = true;
      if (timeout) clearTimeout(timeout);
      activeController?.abort();
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [liveCatalogEnabled, cartLoadState, cartMutationPending]);
  useEffect(() => {
    // Check the same-origin session boundary before requesting the private
    // favorites resource. Anonymous catalog visits should not generate an
    // expected-but-noisy 401 request; the API remains fail-closed for direct
    // callers.
    fetch('/api/auth/session', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(async (response) => response.ok ? response.json() as Promise<{ authenticated?: unknown }> : null)
      .then((session) => {
        const authenticated = session?.authenticated === true;
        setBuyerAuthenticated(authenticated);
        return authenticated
          ? fetch('/api/storefront/favorites?limit=100', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' }).then(async (response) => response.ok ? response.json() as Promise<{ items?: unknown }> : null)
          : null;
      })
      .then((payload) => {
        if (!payload || !Array.isArray(payload.items)) { setFavoriteIds([]); return; }
        const ids = payload.items.flatMap((item) => item && typeof item === 'object' && typeof (item as { product_id?: unknown }).product_id === 'string' ? [(item as { product_id: string }).product_id] : []);
        setFavoriteIds(Array.from(new Set(ids)));
      })
      .catch(() => { setBuyerAuthenticated(false); setFavoriteIds([]); })
      .finally(() => setFavoritesLoaded(true));
  }, []);
  const filtered = useMemo(() => {
    const matches = catalog.filter((product) => {
      const textMatches = `${product.title} ${product.category}`.toLowerCase().includes(query.toLowerCase());
      const stockMatches = availabilityFilter === 'all' || (availabilityFilter === 'available' ? product.availability === 'available' : product.availability !== 'available');
      const priceMatches = product.priceMinor <= priceCap;
      return textMatches && stockMatches && priceMatches;
    });
    return [...matches].sort((a, b) => sort === 'price_asc' ? a.priceMinor - b.priceMinor : sort === 'price_desc' ? b.priceMinor - a.priceMinor : 0);
  }, [catalog, query, sort, availabilityFilter, priceCap]);
  const catalogCartLines = catalog.filter((product) => cart[product.id]).map((product) => {
    const serverLine = authoritativeCart?.items.find((item) => item.productId === product.id);
    if (serverLine && !serverLine.isAvailable) return { ...product, availability: 'unavailable' as const, stockLabel: cartUnavailableLabels[serverLine.unavailableReason ?? ''] ?? 'Недоступно по authoritative cart' };
    return product;
  });
  const missingCartLines = liveCatalogEnabled && authoritativeCart ? authoritativeCart.items.filter((item) => !catalog.some((product) => product.id === item.productId)).map((item) => ({ id: item.productId, title: item.name, category: 'Корзина', priceMinor: 0, currency: 'RUB' as const, availability: 'unavailable' as const, stockLabel: cartUnavailableLabels[item.unavailableReason ?? ''] ?? 'Товар больше не опубликован' })) : [];
  const cartLines = [...catalogCartLines, ...missingCartLines];
  const totalMinor = liveCatalogEnabled && authoritativeCart ? authoritativeCart.subtotalMinor : cartLines.reduce((sum, product) => product.availability === 'available' ? sum + product.priceMinor * (cart[product.id] ?? 0) : sum, 0);

  async function add(product: ProductCardDto) {
    if (product.availability !== 'available') return;
    if (liveCatalogEnabled) {
      // The cart hydration response establishes the guest-session cookie.
      // Starting another cart GET here can race that response and let two
      // newly-created session cookies overwrite one another.
      if (cartLoadState !== 'ready' || !authoritativeCart) {
        setNotice('Корзина ещё загружается. Повторите добавление через секунду.');
        return;
      }
      if (!product.skuId || cartMutationPending || addPendingId) { setNotice('Товар нельзя добавить: API каталога не передал SKU для покупки.'); return; }
      setAddPendingId(product.id);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      try {
        const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
        if (!csrfResponse.ok) throw new Error('csrf_unavailable');
        const csrf = await csrfResponse.json() as { token?: unknown };
        if (typeof csrf.token !== 'string' || csrf.token.length === 0) throw new Error('csrf_invalid');
        const snapshot = await addGuestCartItem(product.skuId, 1, csrf.token, controller.signal);
        setAuthoritativeCart(snapshot);
        setCart(snapshot.items.reduce<Record<string, number>>((next, item) => { next[item.productId] = item.quantity; return next; }, {}));
        announceCartChanged();
        setNotice('Товар добавлен. Корзина обновлена authoritative-ответом сервера.');
      } catch { setNotice('Не удалось добавить товар. Корзина не изменена; повторите запрос.'); }
      finally { clearTimeout(timeout); setAddPendingId(null); }
      return;
    }
    setCart((current) => ({ ...current, [product.id]: (current[product.id] ?? 0) + 1 }));
    setNotice(`${product.title} добавлен в корзину`);
  }

  async function favorite(product: ProductCardDto) {
    if (!favoritesLoaded || favoritePendingIds.includes(product.id)) return;
    const isFavorite = favoriteIds.includes(product.id);
    setFavoritePendingIds((current) => [...current, product.id]);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('csrf');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string') throw new Error('csrf');
      const response = await fetch(`/api/storefront/favorites/${encodeURIComponent(product.id)}`, { method: isFavorite ? 'DELETE' : 'POST', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrf.token }, cache: 'no-store' });
      if (response.status === 401) { setNotice('Войдите, чтобы управлять избранными товарами.'); return; }
      if (!response.ok) throw new Error('favorite');
      setFavoriteIds((current) => isFavorite ? current.filter((id) => id !== product.id) : current.includes(product.id) ? current : [...current, product.id]);
      setNotice(isFavorite ? 'Товар удалён из избранного.' : 'Товар сохранён в избранном.');
    } catch {
      setNotice('Не удалось изменить избранное. Попробуйте ещё раз.');
    } finally {
      setFavoritePendingIds((current) => current.filter((id) => id !== product.id));
    }
  }
  async function remove(id: string) {
    if (cartMutationPending) return;
    if (!liveCatalogEnabled) {
      setCart((current) => { const next = { ...current }; delete next[id]; return next; });
      setNotice('Preview: позиция удалена локально. В live-режиме корзина обновляется authoritative API.');
      return;
    }
    setCartMutationPending(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('csrf_unavailable');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string' || csrf.token.length === 0) throw new Error('csrf_invalid');
      const serverItem = authoritativeCart?.items.find((item) => item.productId === id);
      const snapshot = await removeGuestCartItem(serverItem?.skuId ?? id, csrf.token, controller.signal);
      setAuthoritativeCart(snapshot);
      setCart(snapshot.items.reduce<Record<string, number>>((next, item) => { next[item.productId] = item.quantity; return next; }, {}));
      announceCartChanged();
      setNotice('Позиция удалена. Корзина обновлена authoritative-ответом сервера.');
    } catch {
      setNotice('Не удалось удалить позицию. Корзина не изменена; повторите запрос.');
    } finally {
      clearTimeout(timeout);
      setCartMutationPending(false);
    }
  }

  async function updateQuantity(productId: string, quantity: number) {
    if (!liveCatalogEnabled) { setCart((current) => ({ ...current, [productId]: quantity })); setNotice('Preview: количество изменено локально.'); return; }
    if (cartMutationPending || quantity < 1) return;
    const item = authoritativeCart?.items.find((entry) => entry.productId === productId);
    if (!item) { setNotice('Позиция не найдена в authoritative cart.'); return; }
    setCartMutationPending(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('csrf_unavailable');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string' || csrf.token.length === 0) throw new Error('csrf_invalid');
      const snapshot = await updateGuestCartItem(item.skuId, quantity, csrf.token, controller.signal);
      setAuthoritativeCart(snapshot);
      setCart(snapshot.items.reduce<Record<string, number>>((next, entry) => { next[entry.productId] = entry.quantity; return next; }, {}));
      announceCartChanged();
    } catch { setNotice('Не удалось изменить количество. Серверная корзина не изменена.'); }
    finally { clearTimeout(timeout); setCartMutationPending(false); }
  }

  async function clearCart() {
    if (cartMutationPending) return;
    if (!liveCatalogEnabled) { setCart({}); setNotice('Preview: корзина очищена локально.'); return; }
    setCartMutationPending(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('csrf_unavailable');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string' || csrf.token.length === 0) throw new Error('csrf_invalid');
      await clearGuestCart(csrf.token, controller.signal);
      const snapshot = await getGuestCart(controller.signal);
      setAuthoritativeCart(snapshot);
      setCart(snapshot.items.reduce<Record<string, number>>((next, item) => { next[item.productId] = item.quantity; return next; }, {}));
      announceCartChanged();
      setNotice('Корзина очищена. Получен новый authoritative snapshot.');
    } catch { setNotice('Не удалось очистить корзину. Серверные данные не изменены.'); }
    finally { clearTimeout(timeout); setCartMutationPending(false); }
  }

  async function validateBeforeCheckout(checkoutInput?: { addressId?: string; deliveryMethod?: string; paymentMethod?: string; legalConsents?: Array<{ type: string; version: string; acceptedAt: string }> }) {
    if (checkoutPending) return;
    // A retry after PENDING_UNKNOWN is explicit (button click) and reuses the
    // same key from sessionStorage; it never creates a second checkout intent.
    if (!liveCatalogEnabled) {
      setNotice('Preview: checkout включится после подключения live cart API.');
      return;
    }
    setCheckoutPending(true);
    setCheckoutUnknown(false);
    const controller = new AbortController();
    // Validation is fast, but the same request then performs the durable
    // checkout saga and B2B reservation. Do not abort it on the short cart
    // mutation deadline: an early client abort can leave a committed order
    // with an "unknown" UI state. The BFF has the matching bounded timeout.
    const timeout = setTimeout(() => controller.abort(), 25000);
    let activeIdempotencyKey = '';
    setNotice('Проверяем корзину по authoritative API…');
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('csrf_unavailable');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string') throw new Error('csrf_invalid');
      const result = await validateGuestCart(csrf.token, controller.signal);
      setAuthoritativeCart(result.cart);
      setCart(result.cart.items.reduce<Record<string, number>>((next, item) => { next[item.productId] = item.quantity; return next; }, {}));
      announceCartChanged();
      if (!result.isValid) {
        const issue = result.issues[0];
        const changedValues = issue?.oldValue !== undefined && issue.newValue !== undefined ? ` (${issue.oldValue} → ${issue.newValue})` : '';
        const reason = issue ? `${validationIssueLabels[issue.type] ?? 'Корзина изменилась'}: ${issue.message}${changedValues}` : 'Корзина изменилась, проверьте позиции.';
        setNotice(`Требуется проверка корзины: ${reason}`);
        return;
      }
      const addressId = checkoutInput?.addressId?.trim() || document.querySelector<HTMLInputElement | HTMLSelectElement>('input[name="address"], select[name="address"]')?.value.trim();
      if (!addressId) throw new Error('address_required');
      const deliveryMethod = checkoutInput?.deliveryMethod || 'STANDARD';
      const paymentMethod = checkoutInput?.paymentMethod || 'wire_vat';
      const storageKey = 'neomarket.checkout.idempotency';
      let idempotencyKey = '';
      if (typeof window !== 'undefined') {
        try {
          const stored = JSON.parse(window.localStorage.getItem(storageKey) ?? 'null') as { key?: unknown; addressId?: unknown; deliveryMethod?: unknown; paymentMethod?: unknown } | null;
          if (stored && stored.addressId === addressId && stored.deliveryMethod === deliveryMethod && stored.paymentMethod === paymentMethod && typeof stored.key === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored.key)) idempotencyKey = stored.key;
        } catch { /* corrupted local state is discarded below */ }
      }
      if (!idempotencyKey) {
        idempotencyKey = crypto.randomUUID();
        if (typeof window !== 'undefined') window.localStorage.setItem(storageKey, JSON.stringify({ key: idempotencyKey, addressId, deliveryMethod, paymentMethod }));
      }
      activeIdempotencyKey = idempotencyKey;
      const checkoutResponse = await fetch('/api/storefront/checkout/attempts', { method: 'POST', credentials: 'include', signal: controller.signal, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token, 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ ...(typeof result.cart.id === 'string' ? { cartId: result.cart.id } : {}), addressId, deliveryMethod, ...(checkoutInput?.legalConsents ? { legalConsents: checkoutInput.legalConsents } : {}) }) });
      if (!checkoutResponse.ok) {
        const payload = await checkoutResponse.json().catch(() => null) as { title?: string; detail?: string } | null;
        const error = new Error(payload?.detail || payload?.title || `checkout_${checkoutResponse.status}`) as Error & { status?: number };
        error.status = checkoutResponse.status;
        throw error;
      }
      const order = await checkoutResponse.json().catch(() => null) as { id?: unknown } | null;
      if (!order || typeof order.id !== 'string' || !/^[0-9a-f-]{36}$/i.test(order.id)) throw new Error('checkout_operation_missing');
      if (typeof window !== 'undefined') window.localStorage.removeItem(storageKey);
      window.location.assign(`/checkout/status/${encodeURIComponent(order.id)}`);
    } catch (error) {
      const status = (error as { status?: number } | null)?.status;
      if (status === 503 || (error instanceof DOMException && error.name === 'AbortError')) {
        // Resolve the same durable operation before showing an ambiguous
        // state. This is a safe read keyed by the original UUID, never a new
        // checkout attempt.
        if (activeIdempotencyKey) {
          try {
            const lookup = await fetch('/api/storefront/checkout/attempts/by-key', { credentials: 'include', headers: { Accept: 'application/json', 'Idempotency-Key': activeIdempotencyKey }, cache: 'no-store' });
            if (lookup.ok) {
              const operation = await lookup.json() as { operation_id?: unknown; state?: string; order_id?: unknown };
              if (typeof operation.operation_id === 'string' && /^[0-9a-f-]{36}$/i.test(operation.operation_id)) {
                window.location.assign(`/checkout/status/${encodeURIComponent(operation.operation_id)}`);
                return;
              }
            }
          } catch { /* keep the explicit unknown/retry state below */ }
        }
        setCheckoutUnknown(true);
        setNotice('Ответ checkout не подтверждён. Не создавайте новый заказ: сохранённый Idempotency-Key будет использован после восстановления связи.');
      } else {
        setNotice('Не удалось оформить заказ. Серверная корзина не изменена; проверьте данные и повторите осознанно.');
      }
    } finally {
      clearTimeout(timeout);
      setCheckoutPending(false);
    }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#content">К содержимому</a>
    <StorefrontHeader
      active={active === 'orders' ? 'orders' : 'catalog'}
      favoriteCount={favoritesLoaded ? favoriteIds.length : null}
      cartCount={!liveCatalogEnabled || cartLoadState === 'ready' ? Object.values(cart).reduce((sum, quantity) => sum + quantity, 0) : null}
      accountAuthenticated={buyerAuthenticated}
      status={catalogState === 'ready' ? `???????: ${catalog.length} ПОЗИЦИЙ ДОСТУПНО` : catalogState === 'error' ? '??????? ???????? ??????????' : '??????? ???????????'}
      searchValue={query}
      onSearchChange={setQuery}
      onSearchSubmit={() => { setActive('catalog'); document.getElementById('catalog-search')?.focus(); }}
    />

    <main id="content">
      {active === 'catalog' && catalogState === 'loading' && <div className="inline-state" role="status">Загружаем authoritative каталог…</div>}
      {active === 'catalog' && catalogState === 'error' && <div className="inline-state inline-state-error" role="alert"><span>Каталог временно недоступен.</span><button className="button button-secondary" onClick={() => setRetryNonce((value) => value + 1)}>Повторить</button></div>}
      {active === 'checkout' && checkoutPending && <div className="inline-state" role="status" aria-live="polite">Проверяем корзину по authoritative API…</div>}
      {notice && <div className="toast" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Закрыть уведомление">×</button></div>}
      {active === 'catalog' && <div className="marketplace-catalog">
        <section className="catalog-intro" aria-labelledby="catalog-title">
          <div className="catalog-intro-copy">
            <p className="catalog-kicker">NEOMARKET <span>/</span> КАТАЛОГ ПОСТАВЩИКОВ</p>
            <h1 id="catalog-title">Прямые поставки и технологичный B2C/B2B маркетплейс</h1>
            <p>Товары и доступность загружаются из каталога. Финальные цена и наличие подтверждаются сервером при оформлении.</p>
          </div>
          <div className="catalog-api-status" role="status"><span className={catalogState === 'ready' ? 'catalog-status-dot is-live' : 'catalog-status-dot'} />
            <div><strong>{catalogState === 'ready' ? 'КАТАЛОГ СИНХРОНИЗИРОВАН' : catalogState === 'error' ? 'КАТАЛОГ НЕДОСТУПЕН' : 'ЗАГРУЗКА КАТАЛОГА'}</strong><span>{catalog.length} позиций загружено</span></div>
          </div>
          <nav className="catalog-category-chips" aria-label="Быстрый выбор категории">
            <button className={!category ? 'catalog-category-chip is-active' : 'catalog-category-chip'} onClick={() => setCategory('')}>Все категории</button>
            {catalogFacets.categories.slice(0, 5).map((entry) => <button key={entry.id} className={category === entry.name ? 'catalog-category-chip is-active' : 'catalog-category-chip'} onClick={() => setCategory(entry.name)}>{entry.name}</button>)}
          </nav>
        </section>
        <section className="catalog-controlbar" aria-label="Поиск и параметры каталога">
          <label className="catalog-search"><span>Поиск по каталогу</span><input id="catalog-search" aria-label="Поиск по каталогу" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название товара или категория" /></label>
          {category && <button className="catalog-active-filter" onClick={() => setCategory('')}>Категория: {category}<span aria-hidden="true">×</span></button>}
          <label className="catalog-sort"><span>Сортировка</span><select value={sort} onChange={(event) => setSort(event.target.value as SortOption)}><option value="popularity">Популярность</option><option value="price_asc">Сначала дешевле</option><option value="price_desc">Сначала дороже</option><option value="new">Новинки</option></select></label>
          <div className="catalog-view-switch" role="group" aria-label="Вид каталога">
            <button type="button" aria-label="Плитка" aria-pressed={catalogView === 'grid'} className={catalogView === 'grid' ? 'is-active' : ''} onClick={() => setCatalogView('grid')}><svg aria-hidden="true" viewBox="0 0 20 20"><rect x="2" y="2" width="6" height="6"/><rect x="12" y="2" width="6" height="6"/><rect x="2" y="12" width="6" height="6"/><rect x="12" y="12" width="6" height="6"/></svg></button>
            <button type="button" aria-label="Список" aria-pressed={catalogView === 'list'} className={catalogView === 'list' ? 'is-active' : ''} onClick={() => setCatalogView('list')}><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M7 4h11M7 10h11M7 16h11"/><circle cx="3" cy="4" r="1"/><circle cx="3" cy="10" r="1"/><circle cx="3" cy="16" r="1"/></svg></button>
          </div>
        </section>
        <div className="catalog-data-note-row" role="note">
          <div className="catalog-data-note-spacer" aria-hidden="true" />
          <div className="catalog-data-note"><span className="material-symbols-outlined" aria-hidden="true">info</span><span>Данные о товарах, ценах и доступности получены из каталога NeoMarket.</span><span className="catalog-results-count">{formatProductCount(filtered.length)}</span></div>
        </div>
        <div className="marketplace-workspace">
          <aside className="catalog-filter-panel" aria-label="Фильтры каталога">
            <div className="filter-panel-head"><span>ФИЛЬТРЫ</span><button type="button" onClick={() => { setCategory(''); setAvailabilityFilter('all'); setMinRating(0); setPriceCap(catalogFacets.price?.max ?? 10000000); }}>СБРОСИТЬ</button></div>
            <div className="filter-group"><b>КАТЕГОРИЯ</b>{[{ id: '', name: 'Все категории', count: catalog.length }, ...catalogFacets.categories.map((entry) => ({ id: entry.id, name: entry.name, count: entry.count }))].map((item) => <button key={item.id || item.name} type="button" className={(item.id === '' ? !category : category === item.name) ? 'filter-option active' : 'filter-option'} onClick={() => setCategory(item.id === '' ? '' : item.name)}><span>{item.name}</span><small>{item.count}</small></button>)}</div>
            <div className="filter-group"><b>НАЛИЧИЕ</b><label className="filter-check"><input type="radio" name="availability" checked={availabilityFilter === 'all'} onChange={() => setAvailabilityFilter('all')} /> Все товары</label><label className="filter-check"><input type="radio" name="availability" checked={availabilityFilter === 'available'} onChange={() => setAvailabilityFilter('available')} /> В наличии</label><label className="filter-check"><input type="radio" name="availability" checked={availabilityFilter === 'unavailable'} onChange={() => setAvailabilityFilter('unavailable')} /> Нет в наличии</label></div>
            <div className="filter-group"><b>РЕЙТИНГ</b><p className="filter-unavailable-note">Фильтр появится после подключения проверенных отзывов.</p></div>
            <div className="filter-group"><b>ЦЕНА ДО, ₽</b><input aria-label="Максимальная цена" className="filter-price-input" type="number" min="0" step="1000" value={priceCap} onChange={(event) => setPriceCap(Math.max(0, Number(event.target.value) || 0))} /></div>
          </aside>
          <section className="catalog-results" aria-labelledby="catalog-results-title">
            <div className="catalog-results-heading"><div><span>АКТУАЛЬНЫЙ АССОРТИМЕНТ</span><h2 id="catalog-results-title">Каталог</h2></div></div>
            <div className={`product-grid${catalogView === 'list' ? ' is-list' : ''}`}>{filtered.map((product) => <ProductCard key={product.id} product={product} onAdd={add} {...(liveCatalogEnabled ? { onFavorite: favorite } : {})} isFavorite={favoriteIds.includes(product.id)} favoritePending={!favoritesLoaded || favoritePendingIds.includes(product.id)} pending={addPendingId === product.id || (liveCatalogEnabled && cartLoadState !== 'ready')} mutationsEnabled />)}</div>
            {filtered.length === 0 && <div className="empty-state"><h3>Ничего не найдено</h3><p>Измените запрос или сбросьте фильтры.</p><button className="button button-secondary" onClick={() => { setQuery(''); setCategory(''); setAvailabilityFilter('all'); setMinRating(0); }}>Сбросить фильтры</button></div>}
            <div className="pagination-row catalog-pagination-bottom"><button className="chip" disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>← Назад</button><span className="mono">СТРАНИЦА {page}</span><button className="chip" disabled={catalog.length < 20} onClick={() => setPage((current) => Math.min(10000, current + 1))}>Дальше →</button></div>
          </section>
        </div>
      </div>}
      {active === 'cart' && liveCatalogEnabled && cartLoadState === 'loading' && <section className="content-section"><div className="inline-state" role="status">Загружаем authoritative корзину…</div></section>}
      {active === 'cart' && liveCatalogEnabled && cartLoadState === 'error' && <section className="content-section"><p className="eyebrow">SF-06 / CART</p><h1>Корзина недоступна</h1><div className="empty-state"><h3>Не удалось получить серверный snapshot</h3><p>Локальные preview-позиции скрыты, чтобы не показать неверный итог.</p><button className="button button-primary" type="button" onClick={() => setCartRetryNonce((value) => value + 1)}>Повторить запрос</button></div></section>}
      {active === 'cart' && (!liveCatalogEnabled || cartLoadState === 'ready') && <CartView lines={cartLines} cart={cart} totalMinor={totalMinor} cartValid={authoritativeCart?.isValid ?? true} pending={cartMutationPending} onRemove={remove} onQuantity={updateQuantity} onClear={clearCart} onCheckout={() => setActive('checkout')} maxQuantity={(id) => authoritativeCart?.items.find((item) => item.productId === id)?.availableQuantity ?? 99} />}
      {active === 'checkout' && <CheckoutView lines={cartLines} cart={cart} totalMinor={totalMinor} pending={checkoutPending} unknown={checkoutUnknown} addresses={addresses} addressesLoading={addressesLoading} onBack={() => { if (typeof window !== 'undefined') window.location.assign('/cart'); }} onClear={clearCart} onRemove={remove} onQuantity={updateQuantity} maxQuantity={(id) => authoritativeCart?.items.find((item) => item.productId === id)?.availableQuantity ?? 99} onSubmit={validateBeforeCheckout} />}
      {active === 'orders' && <section className="content-section"><p className="eyebrow">ACCOUNT / ORDERS</p><h1>Заказы</h1><div className="empty-state"><h3>Войдите, чтобы увидеть историю</h3><p>Приватные данные загружаются только через same-origin серверную сессию.</p><a className="button button-primary" href="/login">Войти безопасно</a></div></section>}
    </main>
    <footer className="footer">
      <div className="footer-grid">
        <section className="footer-brand-block" aria-label="О NeoMarket">
          <a className="footer-brand" href="/catalog"><span className="brand-mark">N</span><b>NEOMARKET</b></a>
          <p>Единый каталог для розничных заказов и закупок партиями. Цены и наличие подтверждаются сервером.</p>
          <span className="footer-api-state"><span className={`status-dot${catalogState === 'ready' ? ' is-live' : ''}`} aria-hidden="true" />{catalogState === 'ready' ? 'КАТАЛОГ ПОДКЛЮЧЕН' : catalogState === 'error' ? 'API ВРЕМЕННО НЕДОСТУПЕН' : 'ПОДКЛЮЧАЕМ КАТАЛОГ'}</span>
        </section>
        <section className="footer-links"><h2>Магазин</h2><a href="/catalog">Каталог товаров</a><a href="/favorites">Избранное</a><a href="/cart">Корзина</a></section>
        <section className="footer-links"><h2>Покупателям</h2><a href="/account/orders">Мои заказы</a><a href="/account/addresses">Адреса доставки</a><a href={buyerAuthenticated ? '/account' : '/login'}>{buyerAuthenticated ? 'Личный кабинет' : 'Войти в аккаунт'}</a></section>
        <section className="footer-links"><h2>Документы</h2><a href="/legal/terms">Правила продажи</a><a href="/legal/privacy">Конфиденциальность</a><a href="/legal/cookies">Cookies</a></section>
      </div>
      <div className="footer-bottom"><span>© 2026 NEOMARKET</span><span>СОСТОЯНИЕ API: {liveCatalogEnabled ? 'LIVE CATALOG / READ-ONLY' : 'PREVIEW / READ-ONLY'}</span><span>ПРАВИЛА ОБРАБОТКИ ДАННЫХ — В РАЗДЕЛЕ «ДОКУМЕНТЫ»</span></div>
    </footer>
  </div>;
}

function LegacyCheckoutView({ totalMinor, pending, onBack, onSubmit }: { totalMinor: number; pending: boolean; onBack: () => void; onSubmit: () => void }) {
  return <section className="content-section checkout-layout" aria-busy={pending}><div><button className="text-button" type="button" onClick={onBack} disabled={pending}>← Вернуться в корзину</button><p className="eyebrow checkout-eyebrow">SF-07 / CHECKOUT</p><h1>Оформление</h1><p className="section-copy">Выберите сохранённый адрес. Перед подтверждением сервер валидирует корзину и создаёт durable checkout attempt.</p><form className="checkout-form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}><label>ID сохранённого адреса<input required name="address" placeholder="UUID адреса из аккаунта" autoComplete="off" disabled={pending} /></label><div className="checkout-note" role="note"><strong>Проверка перед отправкой</strong><span>Повтор запроса выполняется с тем же Idempotency-Key.</span></div><button className="button button-primary" type="submit" disabled={!totalMinor || pending} aria-describedby="checkout-submit-status">{pending ? 'Оформляем…' : 'Создать заказ'}</button><span id="checkout-submit-status" className="checkout-submit-status" role="status" aria-live="polite">{pending ? 'Получаем подтверждение сервера.' : ''}</span></form></div><aside className="summary-card"><p className="eyebrow">CHECKOUT TOTAL</p><div className="summary-total"><span>ИТОГО</span><strong>{money.format(totalMinor / 100)}</strong></div><p className="muted">Финальная сумма приходит только от authoritative cart validation.</p></aside></section>;
}

function OldCheckoutView({ totalMinor, pending, unknown, addresses, addressesLoading, onBack, onSubmit }: { totalMinor: number; pending: boolean; unknown: boolean; addresses: BuyerAddress[]; addressesLoading: boolean; onBack: () => void; onSubmit: () => void }) {
  return <section className="content-section checkout-layout" aria-busy={pending}><div><button className="text-button" type="button" onClick={onBack} disabled={pending}>← Вернуться в корзину</button><p className="eyebrow checkout-eyebrow">SF-07 / CHECKOUT</p><h1>Оформление</h1><p className="section-copy">Выберите сохранённый адрес. Checkout создаёт durable intent до резервирования товара.</p><form className="checkout-form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}><label>Адрес доставки<select required name="address" defaultValue="" disabled={pending || addressesLoading || addresses.length === 0}><option value="" disabled>{addressesLoading ? 'Загружаем адреса…' : addresses.length ? 'Выберите адрес' : 'Сначала добавьте адрес в аккаунте'}</option>{addresses.map((address) => <option key={address.id} value={address.id}>{address.label} — {address.addressLine}</option>)}</select></label>{!addressesLoading && addresses.length === 0 && <a className="text-button" href="/account/addresses">Добавить адрес →</a>}{unknown && <div className="cart-validation-warning" role="alert">Ответ сервера не подтверждён. Кнопка ниже повторит тот же durable checkout с сохранённым ключом.</div>}<div className="checkout-note" role="note"><strong>Проверка перед отправкой</strong><span>Повтор запроса выполняется с тем же Idempotency-Key.</span></div><button className="button button-primary" type="submit" disabled={!totalMinor || pending || addresses.length === 0}>{pending ? 'Оформляем…' : unknown ? 'Проверить checkout повторно' : 'Создать заказ'}</button></form></div><aside className="summary-card"><p className="eyebrow">CHECKOUT TOTAL</p><div className="summary-total"><span>ИТОГО</span><strong>{money.format(totalMinor / 100)}</strong></div><p className="muted">Сумма приходит только от authoritative cart validation.</p></aside></section>;
}

function LegacyCartView({ lines, cart, totalMinor, cartValid, pending, onRemove, onQuantity, onCheckout }: { lines: ProductCardDto[]; cart: Record<string, number>; totalMinor: number; cartValid: boolean; pending: boolean; onRemove: (id: string) => void; onQuantity: (id: string, quantity: number) => void; onCheckout: () => void }) {
  return <section className="content-section cart-layout"><div><p className="eyebrow">SF-06 / CART</p><h1>Корзина</h1><p className="section-copy">Удалённые позиции показаны как недоступные и не входят в итог — сервер остаётся источником суммы.</p>{!cartValid && <div className="cart-validation-warning" role="alert"><strong>Корзина требует проверки</strong><span>Цена, наличие или количество изменились. Перед checkout сервер обновит актуальные данные.</span></div>}{lines.length === 0 ? <div className="empty-state cart-empty-state"><h3>Корзина пуста</h3><p>Добавьте доступный товар из каталога, чтобы начать заказ.</p><a className="button button-primary" href="/catalog">Открыть каталог</a></div> : <div className="cart-list">{lines.map((line) => <div className="cart-line" key={line.id}><div><p className="eyebrow">{line.category}</p><h3>{line.title}</h3><span>{line.availability === 'available' ? `Количество: ${cart[line.id]}` : 'Позиция недоступна'}</span></div><div className="cart-line-actions"><strong className={line.availability === 'available' ? '' : 'muted'}>{line.availability === 'available' ? money.format((line.priceMinor * (cart[line.id] ?? 0)) / 100) : '—'}</strong><button className="text-button" disabled={pending} aria-label={`Удалить ${line.title}`} onClick={() => onRemove(line.id)}>{pending ? 'Обновляем…' : 'Удалить'}</button></div></div>)}</div>}</div><aside className="summary-card"><p className="eyebrow">ORDER SUMMARY</p><div className="summary-row"><span>Доступные позиции</span><b>{money.format(totalMinor / 100)}</b></div><div className="summary-row muted"><span>Доставка</span><span>Рассчитается на checkout</span></div><div className="summary-total"><span>ИТОГО</span><strong>{money.format(totalMinor / 100)}</strong></div><button className="button button-primary wide" disabled={!totalMinor || pending} onClick={onCheckout}>Перейти к оформлению →</button></aside></section>;
}

function LegacyCheckoutView2({ lines, cart, totalMinor, pending, unknown, addresses, addressesLoading, onBack, onSubmit }: { lines: ProductCardDto[]; cart: Record<string, number>; totalMinor: number; pending: boolean; unknown: boolean; addresses: BuyerAddress[]; addressesLoading: boolean; onBack: () => void; onSubmit: () => void }) {
  const [selectedAddressId, setSelectedAddressId] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('wire_vat');
  useEffect(() => {
    const firstAddress = addresses[0];
    if (!selectedAddressId && firstAddress) setSelectedAddressId(firstAddress.id);
  }, [addresses, selectedAddressId]);
  return <section className="checkout-brutalist" aria-busy={pending}>
    <div className="checkout-stepper"><span className="checkout-ref">CHECKOUT FLOW / NM-CHK</span><ol><li className="done">01. Корзина ✓</li><li className="current">02. Адрес доставки</li><li>03. Получение</li><li>04. Оплата</li><li>05. Подтверждение</li></ol></div>
    <div className="checkout-lock"><span className="checkout-lock-icon">◷</span><div><b>РЕЗЕРВ НА СКЛАДЕ: SECURED ALLOCATION</b><strong>Сервер удерживает доступные позиции на 30 минут</strong><small>Цена и наличие подтверждаются повторно перед созданием заказа.</small></div><span className="checkout-lock-status">LOCK_TTL: VALID</span></div>
    <div className="checkout-brutalist-grid">
      <div className="checkout-brutalist-main">
        <button className="checkout-back" type="button" onClick={onBack} disabled={pending}>← Вернуться в корзину</button>
        <div className="checkout-section-heading"><span>STEP 02</span><h1>Адрес доставки и разгрузки</h1></div>
        <p className="checkout-copy">Выберите сохранённый адрес. Данные принадлежат текущей buyer-сессии и проверяются сервером.</p>
        <section className="checkout-items" aria-labelledby="checkout-items-heading">
          <div className="checkout-subheading"><h2 id="checkout-items-heading">Активные позиции корзины</h2><span>{lines.length} ПОЗ.</span></div>
          {lines.length === 0 ? <p className="checkout-empty-items">Корзина пуста. <a href="/catalog">Вернуться в каталог →</a></p> : <div className="checkout-item-list">{lines.map((line) => <article className="checkout-item" key={line.id}>
            <img src={line.imageUrl} alt="" />
            <div className="checkout-item-main"><span className="checkout-item-meta">{line.category} · {line.stockLabel}</span><h3>{line.title}</h3><span className="checkout-item-qty">КОЛ-ВО: {cart[line.id] ?? 0} ШТ</span></div>
            <strong>{money.format((line.priceMinor * (cart[line.id] ?? 0)) / 100)}</strong>
          </article>)}</div>}
        </section>
        {addresses.length === 0 && !addressesLoading && <div className="checkout-empty-address"><b>Адресов пока нет</b><a href="/account/addresses">Добавить адрес →</a></div>}
        <form className="checkout-brutalist-form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
          {addresses.length > 0 && <div className="checkout-address-grid" role="radiogroup" aria-label="Сохранённые адреса">{addresses.map((address) => <button key={address.id} type="button" className={`checkout-address-card${selectedAddressId === address.id ? ' selected' : ''}`} onClick={() => setSelectedAddressId(address.id)} aria-pressed={selectedAddressId === address.id}><span className="checkout-address-tag">{address.label}</span><strong>{address.addressLine}</strong><span>{selectedAddressId === address.id ? '✓ Выбрано' : 'Выбрать адрес'}</span></button>)}</div>}
          <label>Сохранённый адрес<select required name="address" value={selectedAddressId} onChange={(event) => setSelectedAddressId(event.target.value)} disabled={pending || addressesLoading || addresses.length === 0}><option value="" disabled>{addressesLoading ? 'Загружаем адреса…' : 'Выберите адрес'}</option>{addresses.map((address) => <option key={address.id} value={address.id}>{address.label} — {address.addressLine}</option>)}</select></label>
          <div className="checkout-delivery-card"><span className="checkout-delivery-icon">▣</span><div><b>СТАНДАРТНАЯ ДОСТАВКА</b><small>СДЭК B2B ЭКСПРЕСС · 1–2 рабочих дня</small></div><span className="checkout-delivery-status">ДОСТУПНО</span></div>
          {unknown && <div className="checkout-warning" role="alert">Ответ checkout не подтверждён. Повтор используйте с тем же ключом идемпотентности.</div>}
          <div className="checkout-idempotency"><b>ЗАЩИТА ОТ ПОВТОРНЫХ СПИСАНИЙ</b><span>Повтор запроса использует сохранённый Idempotency-Key.</span></div>
          <button className="checkout-primary-cta" type="submit" disabled={!totalMinor || pending || addresses.length === 0}>{pending ? 'ПРОВЕРЯЕМ КОРЗИНУ…' : unknown ? 'ПРОВЕРИТЬ CHECKOUT ПОВТОРНО' : 'ОФОРМИТЬ И ЗАБРОНИРОВАТЬ ЗАКАЗ'} <span>→</span></button>
        </form>
      </div>
      <aside className="checkout-brutalist-summary"><div className="checkout-summary-title"><h2>Итог заказа</h2><span>EST_CHECKOUT</span></div><div className="checkout-summary-row"><span>Доступные товары</span><b>{money.format(totalMinor / 100)}</b></div><div className="checkout-summary-row"><span>Доставка</span><span>Рассчитается по адресу</span></div><div className="checkout-summary-total"><span>ИТОГО К ОПЛАТЕ</span><strong>{money.format(totalMinor / 100)}</strong></div><fieldset className="checkout-payment"><legend>МЕТОД РАСЧЁТА</legend><label><input type="radio" name="payment" value="wire_vat" checked={paymentMethod === 'wire_vat'} onChange={(event) => setPaymentMethod(event.target.value)} /> Безналичный расчёт / счёт</label><label className="payment-unavailable"><input type="radio" name="payment" value="escrow" disabled /> Эскроу безопасной сделки <small>скоро</small></label><label className="payment-unavailable"><input type="radio" name="payment" value="card_online" disabled /> Оплата картой онлайн <small>PSP не подключён</small></label></fieldset><small className="checkout-secure-note">▣ TLS 1.3 · Escrow secured · WCAG AA</small></aside>
    </div>
  </section>;
}

type CheckoutStep = 1 | 2 | 3 | 4 | 5;

function CheckoutView({ lines, cart, totalMinor, pending, unknown, addresses, addressesLoading, onBack, onClear, onRemove, onQuantity, maxQuantity, onSubmit }: {
  lines: ProductCardDto[];
  cart: Record<string, number>;
  totalMinor: number;
  pending: boolean;
  unknown: boolean;
  addresses: BuyerAddress[];
  addressesLoading: boolean;
  onBack: () => void;
  onClear: () => void;
  onRemove: (productId: string) => void;
  onQuantity: (productId: string, quantity: number) => void;
  maxQuantity: (productId: string) => number;
  onSubmit: (input?: { addressId?: string; deliveryMethod?: string; paymentMethod?: string; legalConsents?: Array<{ type: string; version: string; acceptedAt: string }> }) => void;
}) {
  const [selectedAddressId, setSelectedAddressId] = useState('');
  const [deliveryMethod, setDeliveryMethod] = useState('STANDARD');
  const [paymentMethod, setPaymentMethod] = useState('wire_vat');
  const [paymentAccepted, setPaymentAccepted] = useState(false);
  const [stepError, setStepError] = useState('');

  useEffect(() => {
    if (!selectedAddressId && addresses[0]) setSelectedAddressId(addresses[0].id);
    if (selectedAddressId && !addresses.some((address) => address.id === selectedAddressId)) setSelectedAddressId('');
  }, [addresses, selectedAddressId]);

  const addressReady = Boolean(selectedAddressId && addresses.some((address) => address.id === selectedAddressId));
  // The B2C contract accepts a delivery_method label but has no carrier quote/provider.
  const deliveryReady = false;
  const paymentReady = paymentMethod === 'wire_vat' && paymentAccepted;
  const stepCompletion = [lines.length > 0, addressReady, deliveryReady, paymentReady];
  const currentStep = (stepCompletion.findIndex((complete) => !complete) + 1) || 5;
  const stepClass = (target: CheckoutStep) => stepCompletion[target - 1] ? 'done' : target === currentStep ? 'current' : '';

  return <section className="checkout-brutalist" aria-busy={pending} data-checkout-step={currentStep}>
    <div className="checkout-stepper"><span className="checkout-ref">CHECKOUT FLOW / NM-CHK</span><ol aria-label="Этапы оформления">
      <li className={stepClass(1)} aria-current={currentStep === 1 ? 'step' : undefined}><a href="#checkout-cart">01. Корзина {stepCompletion[0] ? '✓' : ''}</a></li><li className={stepClass(2)} data-testid="checkout-step-address" aria-current={currentStep === 2 ? 'step' : undefined}><a href="#checkout-address">02. Адрес доставки {stepCompletion[1] ? '✓' : ''}</a></li><li className={stepClass(3)} data-testid="checkout-step-delivery" aria-current={currentStep === 3 ? 'step' : undefined}><a href="#checkout-delivery">03. Получение {stepCompletion[2] ? '✓' : ''}</a></li><li className={stepClass(4)} data-testid="checkout-step-payment" aria-current={currentStep === 4 ? 'step' : undefined}><a href="#checkout-payment">04. Оплата {stepCompletion[3] ? '✓' : ''}</a></li><li className={stepClass(5)} aria-current={currentStep === 5 ? 'step' : undefined}><span>05. Подтверждение</span></li>
    </ol></div>
    <div className="checkout-brutalist-grid">
      <div className="checkout-brutalist-main">
        <div className="checkout-lock"><span className="checkout-lock-icon material-symbols-outlined" aria-hidden="true">inventory_2</span><div><b>АКТУАЛЬНОСТЬ КОРЗИНЫ</b><strong>Цена и наличие будут повторно проверены сервером перед заказом</strong><small>Резерв товара и срок его действия пока не подтверждаются.</small></div><span className="checkout-lock-status">ПРОВЕРКА ПЕРЕД ЗАКАЗОМ</span></div>
        <h1 className="checkout-visually-hidden">Оформление заказа</h1>
        <section id="checkout-cart" className="checkout-items" aria-labelledby="checkout-items-heading"><div className="checkout-subheading"><div className="checkout-subheading-title"><h2 id="checkout-items-heading">Активные позиции корзины</h2><span>[{lines.length} ПОЗИЦИИ]</span></div><button type="button" className="checkout-clear" onClick={onClear} disabled={pending || lines.length === 0}>[ОЧИСТИТЬ ВСЕ]</button></div>{lines.length === 0 ? <p className="checkout-empty-items">Корзина пуста. <a href="/catalog">Вернуться в каталог →</a></p> : <div className="checkout-item-list">{lines.map((line) => { const quantity = cart[line.id] ?? 0; const available = line.availability === 'available'; const maximum = Math.max(1, maxQuantity(line.id)); return <article className={`checkout-item${available ? '' : ' unavailable'}`} key={line.id} data-product-id={line.id}><div className="checkout-item-image">{line.imageUrl ? <img src={line.imageUrl} alt="" /> : <div className="checkout-item-image-missing" role="img" aria-label={`Фото товара «${line.title}» отсутствует в каталоге`}><span className="material-symbols-outlined" aria-hidden="true">image</span><small>Фото не предоставлено</small></div>}<span>{available ? 'IN STOCK' : 'UNAVAILABLE'}</span></div><div className="checkout-item-main"><div className="checkout-item-meta">{line.skuArticle && <span>[{line.skuArticle}]</span>}<span>{line.category}</span><span>{line.stockLabel}</span></div><h3>{line.title}</h3><div className="checkout-item-controls"><span className="checkout-item-qty">КОЛ-ВО: {quantity} ШТ</span><div className="checkout-quantity-control" role="group" aria-label={`Количество для ${line.title}`}><button type="button" aria-label={`Уменьшить количество ${line.title}`} disabled={pending || quantity <= 1} onClick={() => onQuantity(line.id, quantity - 1)}>−</button><output aria-label={`Количество ${line.title}`}>{quantity}</output><button type="button" aria-label={`Увеличить количество ${line.title}`} disabled={!available || pending || quantity >= maximum} onClick={() => onQuantity(line.id, quantity + 1)}>+</button></div></div></div><strong>{money.format((line.priceMinor * quantity) / 100)}</strong><button className="checkout-item-remove" type="button" aria-label={`Удалить ${line.title} из корзины`} title="Удалить из корзины" disabled={pending} onClick={() => onRemove(line.id)}><span className="material-symbols-outlined" aria-hidden="true">delete</span></button></article>; })}</div>}</section>
        <section id="checkout-address" aria-labelledby="checkout-address-heading"><div className="checkout-section-heading"><span>STEP 02</span><h2 id="checkout-address-heading">Адрес доставки и разгрузки</h2><a href="/account/addresses" className="checkout-add-address">+ ДОБАВИТЬ НОВЫЙ АДРЕС</a></div><p className="checkout-copy">Адрес принадлежит текущему buyer-профилю и загружен через owner-scoped API.</p>{addressesLoading && <p className="inline-state" role="status">Загружаем адреса…</p>}{!addressesLoading && addresses.length === 0 && <div className="checkout-empty-address"><b>Адресов пока нет</b><a href="/account/addresses">Добавить адрес →</a></div>}{addresses.length > 0 && <div className="checkout-address-grid" role="radiogroup" aria-label="Сохранённые адреса">{addresses.map((address) => <label key={address.id} className={`checkout-address-card${selectedAddressId === address.id ? ' selected' : ''}`}><input type="radio" name="checkout-address" value={address.id} checked={selectedAddressId === address.id} onChange={() => { setSelectedAddressId(address.id); setStepError(''); }} /><span className="checkout-address-tag">{address.label}</span><strong>{address.addressLine}</strong><span>{selectedAddressId === address.id ? '✓ Выбрано' : 'Выбрать адрес'}</span><small>КОНТАКТ: buyer-профиль · owner-scoped</small></label>)}</div>}<div className="checkout-carrier"><span className="checkout-delivery-icon material-symbols-outlined" aria-hidden="true">local_shipping</span><div><b>Доставка по адресу</b><small>Провайдер, стоимость и срок пока не подтверждены сервисом доставки.</small></div></div></section>
        <section id="checkout-delivery" aria-labelledby="checkout-delivery-heading"><div className="checkout-section-heading"><span>STEP 03</span><h2 id="checkout-delivery-heading">Получение заказа</h2></div><p className="checkout-copy">Доступные способы и тарифы должны поступать от сервиса доставки. Сейчас backend не возвращает подтверждённое предложение.</p><div className="checkout-delivery-blocked" role="status"><span className="material-symbols-outlined" aria-hidden="true">local_shipping</span><div><b>Расчёт доставки недоступен</b><p>Нельзя подтвердить стоимость и срок доставки, поэтому заказ пока нельзя отправить. Корзина и адрес сохранены.</p></div><span className="checkout-delivery-status is-unavailable">НЕТ ТАРИФА</span></div></section>
      </div>
      <aside className="checkout-brutalist-summary" aria-labelledby="summary-heading"><div className="checkout-summary-title"><h2 id="summary-heading">Итог заказа</h2><span>EST_CHECKOUT</span></div><div className="checkout-summary-row"><span>Сумма товаров</span><b>{money.format(totalMinor / 100)}</b></div><div className="checkout-summary-row"><span>Доставка</span><span>Не рассчитана</span></div><div className="checkout-summary-total"><span>СУММА БЕЗ ДОСТАВКИ</span><strong>{money.format(totalMinor / 100)}</strong></div>
        <fieldset id="checkout-payment" aria-labelledby="checkout-payment-heading" className="checkout-payment"><legend id="checkout-payment-heading">МЕТОД РАСЧЁТА И ОПЛАТЫ</legend><label><input type="radio" name="payment-method" value="wire_vat" checked={paymentMethod === 'wire_vat'} onChange={() => setPaymentMethod('wire_vat')} /><span>Безналичный расчёт / счёт с НДС</span><small>обрабатывается backend</small></label><label className="payment-unavailable"><input type="radio" disabled /><span>Оплата картой онлайн</span><small>PSP не подключён</small></label><label className="payment-unavailable"><input type="radio" disabled /><span>Эскроу</span><small>недоступно</small></label></fieldset>
        <label className="checkout-payment-confirm"><input type="checkbox" checked={paymentAccepted} onChange={(event) => setPaymentAccepted(event.target.checked)} /> Подтверждаю выбранный способ оплаты.</label>
        {stepError && <div className="checkout-warning" role="alert">{stepError}</div>}{unknown && <div className="checkout-warning" role="alert">Ответ checkout не подтверждён. Повтор используйте с тем же ключом идемпотентности.</div>}
        <div className="checkout-idempotency"><b>ЗАЩИТА ОТ ПОВТОРНЫХ СПИСАНИЙ</b><span>Финальный запрос использует durable UUID Idempotency-Key и серверную проверку корзины.</span></div>
        <button className="checkout-primary-cta" type="button" onClick={() => { if (!paymentReady) { setStepError('Подтвердите способ оплаты и реквизиты.'); return; } onSubmit({ addressId: selectedAddressId, deliveryMethod, paymentMethod, legalConsents: [{ type: 'order_creation', version: '2026-10-15', acceptedAt: new Date().toISOString() }] }); }} disabled={!totalMinor || pending || !addressReady || !deliveryReady}>{pending ? 'ПРОВЕРЯЕМ ДАННЫЕ НА СЕРВЕРЕ…' : unknown ? 'ПОВТОРИТЬ С ТЕМ ЖЕ КЛЮЧОМ' : 'ОФОРМИТЬ И ПЕРЕЙТИ К ПОДТВЕРЖДЕНИЮ'} <span>→</span></button>
        <small className="checkout-secure-note" role="note">Стоимость доставки пока не рассчитана. Оформление станет доступно после подтверждения серверного тарифа.</small></aside>
    </div>
  </section>;
}
