'use client';

import { useEffect, useMemo, useState } from 'react';
import { isProductDetailDto, normalizeProductDetail, type ProductDetailDto } from '@neomarket/api-types';
import { addGuestCartItem, getGuestCart } from '@neomarket/api-client';
import { announceCartChanged } from './cart-sync';
import { QuantityStepper } from '@neomarket/ui';
import { StorefrontHeader } from './StorefrontHeader';

type ProductState = 'loading' | 'ready' | 'error' | 'disabled';
type FavoriteResponse = { items?: Array<{ product_id?: unknown }> };

function formatMoney(amount: number, currency: string) {
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount / 100);
}

function getImageUrl(value: unknown): string | null {
  const candidate = typeof value === 'string' ? value : value && typeof value === 'object' && typeof (value as { url?: unknown }).url === 'string' ? (value as { url: string }).url : null;
  return candidate && (candidate.startsWith('/') || candidate.startsWith('https://')) ? candidate : null;
}

export function ProductDetail({ productId }: { productId: string }) {
  const [state, setState] = useState<ProductState>(process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG === 'true' ? 'loading' : 'disabled');
  const [product, setProduct] = useState<ProductDetailDto | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [cartItemCount, setCartItemCount] = useState<number | null>(null);
  const [cartState, setCartState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [favoriteItemCount, setFavoriteItemCount] = useState<number | null>(null);
  const [accountAuthenticated, setAccountAuthenticated] = useState<boolean | null>(null);

  const header = <StorefrontHeader favoriteCount={favoriteItemCount} cartCount={cartItemCount} accountAuthenticated={accountAuthenticated} status={state === 'ready' ? '????????: ?????? ?? ????????' : state === 'error' ? '???????: ???????? ??????????' : '???????: ????????'} />;

  useEffect(() => {
    const controller = new AbortController();
    getGuestCart(controller.signal)
      .then((cart) => { setCartItemCount(cart.itemsCount); setCartState('ready'); })
      .catch(() => { if (!controller.signal.aborted) setCartState('error'); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/auth/session', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal })
      .then(async (response) => response.ok ? response.json() as Promise<{ authenticated?: unknown }> : null)
      .then(async (session) => {
        const authenticated = session?.authenticated === true;
        setAccountAuthenticated(authenticated);
        if (!authenticated) return 0;
        const response = await fetch('/api/storefront/favorites?limit=100', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('favorites_unavailable');
        const payload = await response.json() as FavoriteResponse;
        return new Set(payload.items?.flatMap((item) => typeof item.product_id === 'string' ? [item.product_id] : []) ?? []).size;
      })
      .then(setFavoriteItemCount)
      .catch(() => { if (!controller.signal.aborted) setFavoriteItemCount(null); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG !== 'true') return;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 8000);
    fetch(`/api/storefront/products/${encodeURIComponent(productId)}`, { signal: controller.signal, credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(async (response) => { if (!response.ok) throw new Error(`product_${response.status}`); return response.json(); })
      .then((value: unknown) => {
        if (!isProductDetailDto(value)) throw new Error('invalid_product');
        const candidate = normalizeProductDetail(value);
        const skuId = candidate.skuId ?? candidate.skus?.find((sku) => typeof sku.id === 'string')?.id;
        setProduct({ ...candidate, ...(typeof skuId === 'string' ? { skuId } : {}) });
        setState('ready');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError' && !timedOut) return;
        setState('error');
      });
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [productId, retryNonce]);

  if (state === 'loading') return <>{header}<ProductDetailSkeleton /><ProductDetailFooter /></>;
  if (state === 'disabled') return <>{header}<main className="product-detail-page"><section className="product-state-panel"><h1>Карточка товара</h1><p>Каталог временно недоступен. Подключение к источнику товаров отключено.</p><a className="button button-secondary" href="/catalog">Вернуться в каталог</a></section></main><ProductDetailFooter /></>;
  if (state === 'error' || !product) return <>{header}<main className="product-detail-page"><section className="product-state-panel" role="alert"><h1>Не удалось загрузить товар</h1><p>Проверьте соединение и повторите запрос. Цена и наличие не заменяются демонстрационными данными.</p><div className="product-error-actions"><button className="button button-primary" type="button" onClick={() => { setState('loading'); setRetryNonce((value) => value + 1); }}>Повторить</button><a className="button button-secondary" href="/catalog">Вернуться в каталог</a></div></section></main><ProductDetailFooter /></>;
  return <>{header}<ProductDetailView product={product} cartLoading={cartState === 'loading'} onCartCountChange={setCartItemCount} onFavoriteCountChange={(difference) => setFavoriteItemCount((count) => count === null ? null : Math.max(0, count + difference))} /><ProductDetailFooter /></>;
}

function ProductDetailFooter() {
  return <footer className="product-detail-footer"><a href="/catalog">NEOMARKET</a><span>Сведения о товарах — из каталога</span><div><a href="/legal/terms">Условия продажи</a><a href="/legal/privacy">Конфиденциальность</a></div></footer>;
}

function ProductDetailSkeleton() {
  return <main className="product-detail-page" aria-busy="true" aria-label="Загрузка карточки товара"><section className="product-detail-skeleton" role="status"><span className="eyebrow">КАРТОЧКА ТОВАРА</span><div className="skeleton-stage" /><div className="skeleton-copy"><span /><span /><span /></div><p>Загружаем сведения из каталога…</p></section></main>;
}

function ProductDetailView({ product, cartLoading, onCartCountChange, onFavoriteCountChange }: { product: ProductDetailDto; cartLoading: boolean; onCartCountChange: (count: number) => void; onFavoriteCountChange: (difference: number) => void }) {
  const [activeImage, setActiveImage] = useState<string | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [notice, setNotice] = useState('');
  const [addPending, setAddPending] = useState(false);
  const [favorite, setFavorite] = useState(false);
  const [favoritePending, setFavoritePending] = useState(false);
  const selectedSku = product.skus?.find((sku) => typeof sku.id === 'string');
  const isSeedPreview = product.characteristics?.demo === true || product.characteristics?.source === 'seed';
  const skuId = product.skuId ?? (typeof selectedSku?.id === 'string' ? selectedSku.id : null);
  const article = typeof selectedSku?.article === 'string' && selectedSku.article.trim() ? selectedSku.article.trim() : null;
  const availableQuantity = typeof selectedSku?.available_quantity === 'number' ? Math.max(0, selectedSku.available_quantity) : null;
  const images = useMemo(() => isSeedPreview ? [] : Array.from(new Set([product.image, ...(product.images ?? []), ...(selectedSku?.images ?? [])].map(getImageUrl).filter((url): url is string => Boolean(url)))), [isSeedPreview, product.image, product.images, selectedSku?.images]);
  const primaryImage = images[0] ?? null;
  const selectedImage = activeImage ?? primaryImage;
  const available = product.availability ? product.availability === 'available' : product.in_stock !== false;
  const availabilityLabel = product.availability === 'removed' ? 'Снято с продажи' : available ? 'В наличии' : 'Нет в наличии';
  const statusTone = available ? 'status-good' : 'status-bad';
  const priceMinor = typeof product.price_minor === 'number' ? product.price_minor : typeof product.min_price_minor === 'number' ? product.min_price_minor : null;
  const currency = product.currency ?? 'RUB';
  const price = priceMinor !== null ? formatMoney(priceMinor, currency) : null;
  const total = priceMinor !== null ? formatMoney(priceMinor * quantity, currency) : null;
  const characteristics = isSeedPreview ? [] : Object.entries(product.characteristics ?? {}).filter(([key, value]) => !['demo', 'source', 'rating', 'reviews_count'].includes(key.toLowerCase()) && ['string', 'number', 'boolean'].includes(typeof value));

  useEffect(() => { setActiveImage(null); setImageFailed(false); }, [primaryImage]);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/auth/session', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal })
      .then(async (response) => response.ok ? response.json() as Promise<{ authenticated?: boolean }> : null)
      .then(async (session) => {
        if (!session?.authenticated) { setFavorite(false); return null; }
        const response = await fetch('/api/storefront/favorites?limit=100', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal });
        return response.ok ? response.json() as Promise<FavoriteResponse> : null;
      })
      .then((payload) => { if (payload) setFavorite(Boolean(payload.items?.some((item) => item.product_id === product.id))); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [product.id]);

  function changeQuantity(next: number) {
    const maximum = availableQuantity === null ? 99 : Math.max(1, Math.min(99, availableQuantity));
    setQuantity(Math.min(maximum, Math.max(1, Number.isFinite(next) ? Math.trunc(next) : 1)));
  }

  async function toggleFavorite() {
    if (favoritePending || !product.id) return;
    setFavoritePending(true);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error(csrfResponse.status === 401 ? 'Войдите, чтобы сохранить товар в избранное.' : 'Не удалось подготовить защищённый запрос.');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string' || !csrf.token) throw new Error('Защитный токен недоступен. Обновите страницу и повторите попытку.');
      const response = await fetch(`/api/storefront/favorites/${encodeURIComponent(product.id)}`, { method: favorite ? 'DELETE' : 'POST', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrf.token }, cache: 'no-store' });
      if (response.status === 401) throw new Error('Войдите, чтобы сохранить товар в избранное.');
      if (!response.ok) throw new Error('Не удалось изменить избранное. Повторите попытку.');
      setFavorite(!favorite);
      onFavoriteCountChange(favorite ? -1 : 1);
      setNotice(favorite ? 'Товар удалён из избранного.' : 'Товар сохранён в избранном.');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Не удалось изменить избранное.');
    } finally { setFavoritePending(false); }
  }

  async function addToCart() {
    if (!skuId || addPending) return;
    setAddPending(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { signal: controller.signal, credentials: 'include', cache: 'no-store' });
      if (!csrfResponse.ok) throw new Error('Не удалось подготовить защищённый запрос.');
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string' || !csrf.token) throw new Error('Защитный токен недоступен. Обновите страницу и повторите попытку.');
      const cart = await addGuestCartItem(skuId, quantity, csrf.token, controller.signal);
      onCartCountChange(cart.itemsCount);
      announceCartChanged();
      setNotice('Товар добавлен. Корзина обновлена.');
    } catch (error) {
      setNotice(error instanceof Error && error.name !== 'AbortError' ? 'Не удалось добавить товар. Серверная корзина не изменена.' : 'Время ожидания истекло. Проверьте корзину, прежде чем повторять запрос.');
    } finally { clearTimeout(timeout); setAddPending(false); }
  }

  return <main className="product-detail-page">
    <section className="product-crumbs" aria-label="Хлебные крошки"><a href="/">Главная</a><span aria-hidden="true">/</span><a href="/catalog">Каталог</a><span aria-hidden="true">/</span><strong>{product.title}</strong><div className="product-operational-tags"><span className={statusTone}>{availabilityLabel}</span>{article && <span>Артикул: {article}</span>}</div></section>
    <section className="product-detail-hero">
      <div className="product-gallery-column">
        <div className="product-stage"><div className="product-stage-badges"><span>{article ? `АРТИКУЛ ${article}` : 'КАРТОЧКА ТОВАРА'}</span><span>{available ? 'В НАЛИЧИИ' : 'НЕТ В НАЛИЧИИ'}</span></div>{selectedImage && !imageFailed ? <img src={selectedImage} alt={product.title} onError={() => setImageFailed(true)} /> : <div className="product-image-missing" role="img" aria-label={`Изображение товара «${product.title}» не предоставлено`}>Изображение товара не предоставлено</div>}<div className="product-stage-caption"><span>{product.category ?? 'Категория не указана'}</span><span>{availableQuantity !== null ? `ДОСТУПНО: ${availableQuantity}` : 'ОСТАТОК НЕ УКАЗАН'}</span></div></div>
        {images.length > 1 && <div className="product-thumbnails" role="group" aria-label="Галерея товара">{images.map((item, index) => <button key={`${item}-${index}`} className={selectedImage === item ? 'thumbnail active' : 'thumbnail'} type="button" aria-label={`Изображение ${index + 1}`} aria-pressed={selectedImage === item} onClick={() => { setActiveImage(item); setImageFailed(false); }}><img src={item} alt="" /></button>)}</div>}
      </div>
      <div className="product-commercial-column">
        <section className="product-panel product-identity"><div className="product-sku-row"><span>{article ? <>Артикул: <b>{article}</b></> : 'Артикул не указан'}</span><button className={`product-favorite-button${favorite ? ' is-favorite' : ''}`} type="button" aria-label={favorite ? 'Удалить из избранного' : 'Добавить в избранное'} aria-pressed={favorite} disabled={favoritePending} onClick={() => void toggleFavorite()}><span className="material-symbols-outlined" aria-hidden="true">{favorite ? 'favorite' : 'favorite_border'}</span></button></div><h1>{product.title}</h1>{!isSeedPreview && product.description && <p className="product-description">{product.description}</p>}<p className={`detail-availability ${statusTone}`} aria-live="polite">{availabilityLabel}</p></section>
        <section className="product-panel product-pricing"><div className="panel-heading"><span>Цена</span><span>По данным каталога</span></div>{price ? <><strong className="detail-price">{price}</strong><p className="product-muted">Итог зависит от количества и будет повторно проверен сервером.</p></> : <div className="product-data-missing">Цена не указана в карточке товара.</div>}<div className="product-buy-row"><QuantityStepper className="quantity-control" value={quantity} max={availableQuantity ?? 99} disabled={!available || availableQuantity === 0} onChange={changeQuantity} /><button className="button button-primary product-buy-button" type="button" disabled={!available || !price || !skuId || addPending || availableQuantity === 0 || cartLoading} aria-busy={addPending || cartLoading} onClick={() => void addToCart()}>{cartLoading ? 'Проверяем корзину…' : addPending ? 'Добавляем…' : <>В корзину{total ? ` — ${total}` : ''}</>}</button></div>{notice && <p className="product-notice" role="status" aria-live="polite">{notice}</p>}</section>
        <section className="product-panel product-trust"><div className="panel-heading"><span>Информация о покупке</span><span>Проверка перед заказом</span></div><ul><li>Цена и наличие предоставлены каталогом.</li><li>Сервер проверит остаток и сумму при добавлении в корзину.</li></ul></section>
      </div>
    </section>
    <nav className="product-tabs" aria-label="Разделы карточки"><a href="#description">О товаре</a><a href="#specifications">Характеристики</a><a href="#documents">Документация</a><a href="#reviews">Отзывы</a></nav>
    <section className="product-lower-grid"><article id="description" className="product-panel product-copy"><p className="eyebrow">О ТОВАРЕ</p><h2>{product.title}</h2><p>{!isSeedPreview && product.description ? product.description : 'Описание товара не предоставлено.'}</p></article><article id="specifications" className="product-panel product-ledger"><p className="eyebrow">ХАРАКТЕРИСТИКИ</p>{characteristics.length ? <dl className="product-characteristics">{characteristics.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl> : <div className="product-data-missing">Характеристики не указаны.</div>}</article><article id="documents" className="product-panel product-ledger"><p className="eyebrow">ДОКУМЕНТАЦИЯ</p><div className="product-data-missing">Документы не предоставлены.</div></article><article id="reviews" className="product-panel product-ledger"><p className="eyebrow">ОТЗЫВЫ</p><div className="product-data-missing">Отзывы не указаны.</div></article></section>
  </main>;
}
