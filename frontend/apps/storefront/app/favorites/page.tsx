'use client';

import { useEffect, useMemo, useState } from 'react';
import { StorefrontHeader } from '../../src/StorefrontHeader';

type ProductSku = { id: string; article?: string | null; price_minor?: number | null; price?: number | null; active_quantity?: number | null; is_active?: boolean };
type Product = {
  id: string; title?: string; description?: string | null; category?: string | null;
  image?: string | null; images?: Array<{ url?: string; ordering?: number }>;
  price_minor?: number | null; min_price_minor?: number | null; price?: number | null; status?: string; deleted?: boolean; skus?: ProductSku[];
};
type Favorite = { id: string; product_id: string; added_at: string; product?: Product | null };
type FavoritesPayload = { items?: unknown };
type LoadState = 'loading' | 'ready' | 'guest' | 'error';
type SortMode = 'newest' | 'title' | 'price-asc' | 'price-desc' | 'stock';

const titleOf = (item: Favorite) => item.product?.title?.trim() || `Товар ${item.product_id}`;

function activeSku(item: Favorite) {
  const skus = item.product?.skus ?? [];
  return skus.find((sku) => sku.is_active === true && Number(sku.active_quantity) > 0)
    ?? skus.find((sku) => sku.is_active === true);
}

function stockOf(item: Favorite) {
  return (item.product?.skus ?? []).reduce((sum, sku) => (
    sku.is_active ? sum + Math.max(0, Number(sku.active_quantity) || 0) : sum
  ), 0);
}

function isAvailable(item: Favorite) {
  return Boolean(item.product && item.product.deleted !== true && item.product.status !== 'DELETED' && activeSku(item) && stockOf(item) > 0);
}

function priceOf(item: Favorite) {
  const sku = activeSku(item);
  const price = sku?.price_minor ?? item.product?.min_price_minor ?? item.product?.price_minor ?? sku?.price ?? item.product?.price;
  return typeof price === 'number' && Number.isFinite(price) && price >= 0 ? price : null;
}

function formatPrice(minor: number | null) {
  if (minor === null) return 'Цена уточняется';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(minor / 100);
}

function productImage(item: Favorite) {
  const candidate = item.product?.images?.slice().sort((a, b) => (a.ordering ?? 0) - (b.ordering ?? 0))[0]?.url ?? item.product?.image;
  if (typeof candidate !== 'string') return null;
  if (candidate.startsWith('/')) return candidate;
  try { return new URL(candidate).protocol === 'https:' ? candidate : null; } catch { return null; }
}

function errorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === 'object' && 'title' in payload && typeof payload.title === 'string') return payload.title;
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message;
  }
  return fallback;
}

export default function FavoritesPage() {
  const [state, setState] = useState<LoadState>('loading');
  const [items, setItems] = useState<Favorite[]>([]);
  const [retry, setRetry] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<string[]>([]);
  const [cartPending, setCartPending] = useState(false);
  const [cartCount, setCartCount] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [stockFilter, setStockFilter] = useState<'all' | 'available' | 'unavailable'>('all');
  const [sort, setSort] = useState<SortMode>('newest');
  const [view, setView] = useState<'grid' | 'table'>('grid');
  const [selected, setSelected] = useState<string[]>([]);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [notice, setNotice] = useState('');

  async function loadFavorites(signal?: AbortSignal) {
    const response = await fetch('/api/storefront/favorites?limit=100', {
      ...(signal ? { signal } : {}), credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store',
    });
    if (response.status === 401) { setState('guest'); return; }
    if (!response.ok) throw new Error('Не удалось загрузить избранное.');
    const payload = await response.json() as FavoritesPayload;
    const next = Array.isArray(payload.items) ? payload.items.filter((value): value is Favorite => Boolean(
      value && typeof value === 'object' && typeof (value as Favorite).id === 'string' && typeof (value as Favorite).product_id === 'string',
    )) : [];
    setItems(next);
    setSelected((current) => current.filter((id) => next.some((item) => item.product_id === id)));
    setState('ready');
  }

  useEffect(() => {
    const controller = new AbortController();
    setState('loading');
    loadFavorites(controller.signal).catch((error: unknown) => {
      if (!(error instanceof DOMException && error.name === 'AbortError')) setState('error');
    });
    return () => controller.abort();
    // retry is the explicit refresh trigger for this resource.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retry]);

  const visible = useMemo(() => {
    const term = query.trim().toLocaleLowerCase('ru-RU');
    return items.filter((item) => {
      const sku = activeSku(item);
      const matchText = `${titleOf(item)} ${sku?.article ?? ''} ${item.product?.category ?? ''}`.toLocaleLowerCase('ru-RU');
      const matchStock = stockFilter === 'all' || (stockFilter === 'available' ? isAvailable(item) : !isAvailable(item));
      return (!term || matchText.includes(term)) && matchStock;
    }).sort((a, b) => {
      if (sort === 'title') return titleOf(a).localeCompare(titleOf(b), 'ru');
      if (sort === 'price-asc') return (priceOf(a) ?? Number.MAX_SAFE_INTEGER) - (priceOf(b) ?? Number.MAX_SAFE_INTEGER);
      if (sort === 'price-desc') return (priceOf(b) ?? -1) - (priceOf(a) ?? -1);
      if (sort === 'stock') return Number(isAvailable(b)) - Number(isAvailable(a));
      return new Date(b.added_at).getTime() - new Date(a.added_at).getTime();
    });
  }, [items, query, sort, stockFilter]);

  async function csrfToken() {
    const response = await fetch('/api/auth/csrf', { credentials: 'include', cache: 'no-store' });
    if (!response.ok) throw new Error('Не удалось подготовить защищённый запрос. Обновите страницу и повторите.');
    const payload = await response.json() as { token?: unknown };
    if (typeof payload.token !== 'string' || !payload.token) throw new Error('Защитный токен недоступен. Обновите страницу и повторите.');
    return payload.token;
  }

  async function removeFavorite(productId: string) {
    if (pending.includes(productId)) return false;
    setPending((current) => [...current, productId]);
    try {
      const token = await csrfToken();
      const response = await fetch(`/api/storefront/favorites/${encodeURIComponent(productId)}`, {
        method: 'DELETE', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': token }, cache: 'no-store',
      });
      if (!response.ok) throw new Error(errorMessage(await response.json().catch(() => null), 'Не удалось удалить товар из избранного.'));
      setItems((current) => current.filter((item) => item.product_id !== productId));
      setSelected((current) => current.filter((id) => id !== productId));
      return true;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Не удалось удалить товар из избранного.');
      return false;
    } finally { setPending((current) => current.filter((id) => id !== productId)); }
  }

  async function addFavoriteToCart(item: Favorite, quantity: number) {
    const sku = activeSku(item);
    if (!sku || !isAvailable(item)) return false;
    const token = await csrfToken();
    const response = await fetch('/api/storefront/cart/items', {
      method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify({ sku_id: sku.id, quantity }), cache: 'no-store',
    });
    const payload = await response.json().catch(() => null) as { items?: Array<{ quantity?: unknown }> } | null;
    if (!response.ok) throw new Error(errorMessage(payload, 'Не удалось добавить товар. Корзина не изменена.'));
    if (Array.isArray(payload?.items)) setCartCount(payload.items.reduce((sum, line) => sum + (typeof line.quantity === 'number' ? line.quantity : 0), 0));
    return true;
  }

  async function addOne(item: Favorite) {
    setCartPending(true);
    try {
      const count = quantities[item.product_id] ?? 1;
      const added = await addFavoriteToCart(item, count);
      setNotice(added ? `${titleOf(item)} добавлен в корзину.` : 'Товар сейчас недоступен для заказа.');
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Не удалось добавить товар.'); }
    finally { setCartPending(false); }
  }

  async function addSelected() {
    const chosen = visible.filter((item) => selected.includes(item.product_id));
    if (!chosen.length || cartPending) return;
    setCartPending(true);
    let added = 0; let failed = 0;
    try {
      for (const item of chosen) {
        try { if (await addFavoriteToCart(item, quantities[item.product_id] ?? 1)) added++; else failed++; }
        catch { failed++; }
      }
      setNotice(failed ? `Добавлено товаров: ${added}. Не добавлено: ${failed}; проверьте наличие и повторите.` : `В корзину добавлено товаров: ${added}.`);
    } finally { setCartPending(false); }
  }

  async function removeSelected() {
    const chosen = visible.filter((item) => selected.includes(item.product_id));
    let removed = 0;
    for (const item of chosen) if (await removeFavorite(item.product_id)) removed++;
    if (removed) setNotice(`Удалено товаров из избранного: ${removed}.`);
  }

  async function refresh() {
    setRefreshing(true);
    try { await loadFavorites(); setNotice('Список избранного обновлён из аккаунта.'); }
    catch (error) { setNotice(error instanceof Error ? error.message : 'Не удалось обновить список.'); }
    finally { setRefreshing(false); }
  }

  function exportSelection() {
    const rows = (selected.length ? items.filter((item) => selected.includes(item.product_id)) : visible).map((item) => [
      titleOf(item), item.product?.category ?? '', activeSku(item)?.article ?? '',
      formatPrice(priceOf(item)), isAvailable(item) ? 'В наличии' : 'Нет в наличии',
    ]);
    if (!rows.length) { setNotice('Нет товаров для экспорта.'); return; }
    const csv = [['Название', 'Категория', 'SKU', 'Цена', 'Доступность'], ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(';')).join('\r\n');
    const url = URL.createObjectURL(new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'neomarket-favorites.csv'; anchor.click(); URL.revokeObjectURL(url);
    setNotice('Файл избранного подготовлен.');
  }

  if (state === 'loading') return <><StorefrontHeader active="favorites" favoriteCount={null} cartCount={cartCount} status="ИЗБРАННОЕ: ЗАГРУЗКА" /><main className="favorites-state-page"><div className="favorites-state" role="status">Загружаем избранное…</div></main></>;
  if (state === 'guest') return <><StorefrontHeader active="favorites" favoriteCount={0} cartCount={cartCount} accountAuthenticated={false} status="ИЗБРАННОЕ: ВОЙДИТЕ В АККАУНТ" /><main className="favorites-state-page"><p className="eyebrow">АККАУНТ / ИЗБРАННОЕ</p><h1>Избранное</h1><div className="empty-state"><h3>Войдите, чтобы открыть список</h3><p>Избранное хранится в вашем аккаунте.</p><a className="button button-primary" href="/login">Войти</a></div></main></>;
  if (state === 'error') return <><StorefrontHeader active="favorites" favoriteCount={null} cartCount={cartCount} status="ИЗБРАННОЕ: ОШИБКА ЗАГРУЗКИ" /><main className="favorites-state-page"><p className="eyebrow">АККАУНТ / ИЗБРАННОЕ</p><h1>Избранное</h1><div className="empty-state"><h3>Не удалось загрузить избранное</h3><p>Повторите запрос. Сохранённые товары не удалены.</p><button className="button button-secondary" type="button" onClick={() => { setState('loading'); setRetry((value) => value + 1); }}>Повторить</button></div></main></>;

  const availableCount = items.filter(isAvailable).length;
  const allVisibleSelected = visible.length > 0 && visible.every((item) => selected.includes(item.product_id));

  return <main className="favorites-page" id="content">
    <a className="skip-link" href="#favorites-content">К содержимому</a>
    <StorefrontHeader
      active="favorites"
      favoriteCount={state === 'ready' ? items.length : null}
      cartCount={cartCount}
      accountAuthenticated={true}
      status={state === 'ready' ? `ИЗБРАННОЕ: ${items.length} ТОВАРОВ` : state === 'error' ? 'ИЗБРАННОЕ: ОШИБКА ЗАГРУЗКИ' : 'ИЗБРАННОЕ: ЗАГРУЗКА'}
      searchValue={query}
      searchLabel="Поиск в избранном"
      searchPlaceholder="Поиск по сохранённым товарам"
      onSearchChange={setQuery}
    />
    <div className="favorites-meta"><span><a href="/catalog">ГЛАВНАЯ</a><span aria-hidden="true"> / </span><b>ИЗБРАННОЕ</b></span><span className="favorites-meta-status">{refreshing ? 'ОБНОВЛЕНИЕ…' : 'ДАННЫЕ АККАУНТА ЗАГРУЖЕНЫ'}</span></div>
    <header className="favorites-header">
      <div><div className="favorites-title-row"><h1>Избранное</h1><span>{items.length} {items.length === 1 ? 'ТОВАР' : 'ТОВАРОВ'}</span></div><p>Сохранённые товары вашего аккаунта. Описание, изображение, цена и доступность получены из каталога; окончательные условия подтверждаются сервером.</p></div>
      <div className="favorites-actions"><button type="button" onClick={() => window.location.assign('/catalog')}>Открыть каталог</button><button type="button" onClick={exportSelection}>Экспортировать список</button></div>
    </header>
    <section className="favorites-alert" aria-label="Состояние списка"><strong>КАТАЛОГ СИНХРОНИЗИРОВАН</strong><span>Доступно к заказу сейчас: <b>{availableCount} из {items.length}</b>. Цена и остаток проверяются повторно при добавлении в корзину.</span><button type="button" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? 'Обновляем…' : 'Обновить данные'}</button></section>
    <nav className="favorites-tabs" aria-label="Разделы избранного"><button className="active" type="button" aria-current="page">Все сохранённые <b>{items.length}</b></button></nav>
    <section className="favorites-controls" aria-label="Управление избранным">
      <div className="favorites-control-row"><div className="favorites-bulk">
        <label><input type="checkbox" checked={allVisibleSelected} onChange={(event) => setSelected((current) => event.target.checked ? Array.from(new Set([...current, ...visible.map((item) => item.product_id)])) : current.filter((id) => !visible.some((item) => item.product_id === id)))} /> Выбрать все ({visible.length})</label>
        <button type="button" disabled={!selected.length || cartPending} onClick={() => void addSelected()}>Добавить в корзину</button><button type="button" disabled={!selected.length || pending.length > 0} onClick={() => void removeSelected()}>Удалить выбранные</button><button type="button" onClick={exportSelection}>Экспортировать CSV</button>
      </div><div className="catalog-view-switch favorites-view-switch" role="group" aria-label="Вид избранного"><button type="button" className={view === 'grid' ? 'is-active' : ''} aria-pressed={view === 'grid'} onClick={() => setView('grid')}><span className="material-symbols-outlined" aria-hidden="true">grid_view</span><span>Сетка</span></button><button type="button" className={view === 'table' ? 'is-active' : ''} aria-pressed={view === 'table'} onClick={() => setView('table')}><span className="material-symbols-outlined" aria-hidden="true">table_rows</span><span>Спецификация</span></button></div></div>
      <div className="favorites-control-row favorites-filter-row"><div className="favorites-bulk" role="group" aria-label="Фильтр наличия"><span className="favorites-control-label">Наличие:</span><button className={stockFilter === 'all' ? 'active' : ''} type="button" aria-pressed={stockFilter === 'all'} onClick={() => setStockFilter('all')}>Все ({items.length})</button><button className={stockFilter === 'available' ? 'active' : ''} type="button" aria-pressed={stockFilter === 'available'} onClick={() => setStockFilter('available')}>В наличии ({availableCount})</button><button className={stockFilter === 'unavailable' ? 'active' : ''} type="button" aria-pressed={stockFilter === 'unavailable'} onClick={() => setStockFilter('unavailable')}>Нет в наличии ({items.length - availableCount})</button></div>
        <label className="favorites-sort"><span>Сортировка:</span><select value={sort} onChange={(event) => setSort(event.target.value as SortMode)}><option value="newest">Сначала добавленные</option><option value="title">По названию</option><option value="price-asc">Сначала дешевле</option><option value="price-desc">Сначала дороже</option><option value="stock">Сначала в наличии</option></select></label>
      </div>
    </section>
    {notice && <div className="favorites-notice" role="status" aria-live="polite">{notice}<button type="button" aria-label="Закрыть уведомление" onClick={() => setNotice('')}>×</button></div>}
    <section className={`favorites-list${view === 'table' ? ' is-table' : ''}`} id="favorites-content" aria-label="Сохранённые товары">
      {visible.length === 0 ? <div className="empty-state"><h3>{items.length === 0 ? 'В избранном пока нет товаров' : 'Ничего не найдено'}</h3><p>{items.length === 0 ? 'Сохраните товар в каталоге — он появится здесь.' : 'Измените запрос или фильтр наличия.'}</p>{items.length === 0 && <a className="button button-primary" href="/catalog">Открыть каталог</a>}</div> : visible.map((item) => {
        const product = item.product; const sku = activeSku(item); const available = isAvailable(item); const quantity = quantities[item.product_id] ?? 1; const image = productImage(item);
        return <article className="favorite-supply-card" key={item.id} data-product-id={item.product_id}>
          <div className="favorite-card-head"><label><input type="checkbox" checked={selected.includes(item.product_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.product_id] : current.filter((id) => id !== item.product_id))} /><span className={available ? 'favorite-stock-badge' : 'favorite-stock-badge is-unavailable'}>{available ? `В НАЛИЧИИ: ${stockOf(item)} ШТ` : 'НЕТ В НАЛИЧИИ'}</span>{sku?.article?.trim() && <span className="favorite-sku-label">SKU: {sku.article.trim()}</span>}</label><button className="favorite-remove" type="button" title="Удалить из избранного" aria-label={`Удалить ${titleOf(item)} из избранного`} disabled={pending.includes(item.product_id)} onClick={() => void removeFavorite(item.product_id)}><span className="material-symbols-outlined" aria-hidden="true">delete</span></button></div>
          <div className="favorite-card-body"><a className="favorite-image" href={`/product/${encodeURIComponent(item.product_id)}`} aria-label={`Открыть товар: ${titleOf(item)}`}>{image ? <img src={image} alt={titleOf(item)} loading="lazy" /> : <span className="favorite-image-empty">Изображение не предоставлено</span>}</a>
            <div className="favorite-card-content"><div className="favorite-card-meta"><span>{product?.category || 'Категория не указана'}</span><span>Добавлен: {new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium' }).format(new Date(item.added_at))}</span></div><h2><a href={`/product/${encodeURIComponent(item.product_id)}`}>{titleOf(item)}</a></h2>{product?.description && <p>{product.description}</p>}
              <div className="favorite-price"><strong>{formatPrice(priceOf(item))}</strong><span>{available ? `ДОСТУПНО ${stockOf(item)} ШТ` : 'Проверьте наличие на странице товара'}</span></div>
              <div className="favorite-card-actions"><div className="favorite-quantity" aria-label={`Количество для ${titleOf(item)}`}><button type="button" aria-label={`Уменьшить количество ${titleOf(item)}`} disabled={quantity <= 1 || cartPending} onClick={() => setQuantities((current) => ({ ...current, [item.product_id]: Math.max(1, quantity - 1) }))}>−</button><input aria-label={`Количество ${titleOf(item)}`} inputMode="numeric" value={quantity} onChange={(event) => { const parsed = Number(event.target.value.replace(/\D/g, '')); setQuantities((current) => ({ ...current, [item.product_id]: Math.min(Math.max(1, stockOf(item)), Math.max(1, parsed || 1)) })); }} /><button type="button" aria-label={`Увеличить количество ${titleOf(item)}`} disabled={!available || quantity >= stockOf(item) || cartPending} onClick={() => setQuantities((current) => ({ ...current, [item.product_id]: Math.min(stockOf(item), quantity + 1) }))}>+</button></div><a className="favorite-product-link" href={`/product/${encodeURIComponent(item.product_id)}`}>Открыть товар</a><button className="favorite-add-cart" type="button" disabled={!available || !sku || cartPending} onClick={() => void addOne(item)}>{cartPending ? 'Добавляем…' : 'В корзину'}</button></div>
            </div>
          </div>
        </article>;
      })}
    </section>
    <footer className="favorites-footer"><span>Избранное синхронизировано с buyer-аккаунтом.</span><span>Условия продажи: <a href="/legal/terms">правила</a> · <a href="/legal/privacy">конфиденциальность</a></span></footer>
  </main>;
}
