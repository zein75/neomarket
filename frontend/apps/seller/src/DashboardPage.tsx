'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerBoolean, sellerNumber, sellerObject, sellerOptionalBoolean, sellerOptionalNullableString, sellerOptionalNumber, sellerOptionalString, sellerString } from './lib/seller-api';

import { useEffect, useMemo, useState } from 'react';

type Sku = {
  id: string;
  product_id: string;
  name: string;
  article?: string | null;
  images?: Array<{ id?: string; url: string; ordering?: number }> | null;
  stock_quantity: number;
  active_quantity: number;
  reserved_quantity: number;
  is_active: boolean;
};

type Product = {
  id: string;
  title: string;
  category?: string | null;
  images?: Array<{ id?: string; url: string; ordering?: number }> | null;
  status: string;
  deleted?: boolean;
  is_active?: boolean;
  skus_count: number;
  total_active_quantity: number;
  skus?: Sku[] | null;
};

type InventoryRow = { product: Product; sku: Sku };
type InventoryFilter = 'all' | 'available' | 'reserved' | 'unavailable';
type DashboardMetrics = {
  as_of: string;
  metrics: { live_products: number; sku_count: number; available_stock: number; pending_moderation: number; reserved_stock: number };
};

function decodeImages(value: unknown, path: string): Array<{ id?: string; url: string; ordering?: number }> | null {
  if (value === null) return null;
  return sellerArray(value, path, (entry) => {
    const image = sellerObject(entry, 'image');
    const id = sellerOptionalString(image.id, 'image.id');
    const ordering = sellerOptionalNumber(image.ordering, 'image.ordering');
    return { ...(id !== undefined ? { id } : {}), url: sellerString(image.url, 'image.url'), ...(ordering !== undefined ? { ordering } : {}) };
  });
}

function decodeDashboardSku(value: unknown): Sku {
  const sku = sellerObject(value, 'sku');
  const article = sellerOptionalNullableString(sku.article, 'sku.article');
  const images = sku.images === undefined ? undefined : decodeImages(sku.images, 'sku.images');
  return {
    id: sellerString(sku.id, 'sku.id'), product_id: sellerString(sku.product_id, 'sku.product_id'), name: sellerString(sku.name, 'sku.name'),
    ...(article !== undefined ? { article } : {}), ...(images !== undefined ? { images } : {}),
    stock_quantity: sellerNumber(sku.stock_quantity, 'sku.stock_quantity'), active_quantity: sellerNumber(sku.active_quantity, 'sku.active_quantity'),
    reserved_quantity: sellerNumber(sku.reserved_quantity, 'sku.reserved_quantity'), is_active: sellerBoolean(sku.is_active, 'sku.is_active'),
  };
}

function decodeDashboardProduct(value: unknown): Product {
  const product = sellerObject(value, 'product');
  const category = sellerOptionalNullableString(product.category, 'product.category');
  const images = product.images === undefined ? undefined : decodeImages(product.images, 'product.images');
  const skus = product.skus === undefined || product.skus === null ? product.skus : sellerArray(product.skus, 'product.skus', decodeDashboardSku);
  const deleted = sellerOptionalBoolean(product.deleted, 'product.deleted');
  const active = sellerOptionalBoolean(product.is_active, 'product.is_active');
  return {
    id: sellerString(product.id, 'product.id'), title: sellerString(product.title, 'product.title'), status: sellerString(product.status, 'product.status'),
    skus_count: sellerNumber(product.skus_count, 'product.skus_count'), total_active_quantity: sellerNumber(product.total_active_quantity, 'product.total_active_quantity'),
    ...(category !== undefined ? { category } : {}), ...(images !== undefined ? { images } : {}), ...(skus !== undefined ? { skus } : {}),
    ...(deleted !== undefined ? { deleted } : {}), ...(active !== undefined ? { is_active: active } : {}),
  };
}

function decodeDashboardProducts(value: unknown): { items: Product[]; has_more: boolean } {
  const payload = sellerObject(value, 'products');
  const items = sellerArray(payload.items, 'products.items', decodeDashboardProduct);
  if (payload.page !== undefined) {
    const page = sellerObject(payload.page, 'products.page');
    return { items, has_more: sellerBoolean(page.has_more, 'products.page.has_more') };
  }
  const total = sellerNumber(payload.total_count, 'products.total_count');
  return { items, has_more: total > items.length };
}

function decodeDashboardMetrics(value: unknown): DashboardMetrics {
  const payload = sellerObject(value, 'dashboard');
  const metrics = sellerObject(payload.metrics, 'dashboard.metrics');
  return {
    as_of: sellerString(payload.as_of, 'dashboard.as_of'),
    metrics: {
      live_products: sellerNumber(metrics.live_products, 'dashboard.metrics.live_products'),
      sku_count: sellerNumber(metrics.sku_count, 'dashboard.metrics.sku_count'),
      available_stock: sellerNumber(metrics.available_stock, 'dashboard.metrics.available_stock'),
      pending_moderation: sellerNumber(metrics.pending_moderation, 'dashboard.metrics.pending_moderation'),
      reserved_stock: sellerNumber(metrics.reserved_stock, 'dashboard.metrics.reserved_stock'),
    },
  };
}

function StockThumbnail({ title, url }: { title: string; url: string | undefined }) {
  const [failed, setFailed] = useState(false);
  const label = `Фото товара «${title}»`;

  return (
    <span className="seller-stock-thumb" role="img" aria-label={failed || !url ? `${label} не предоставлено` : label}>
      {url && !failed
        ? <img src={url} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : <svg className="seller-stock-thumb-empty" aria-hidden="true" viewBox="0 0 24 24" fill="none">
          <rect x="3.5" y="4.5" width="17" height="15" rx="1" />
          <circle cx="8.5" cy="9" r="1.5" />
          <path d="m5 17 4.5-4.5 3 3 2.5-2.5 4 4" />
        </svg>}
    </span>
  );
}

const errorMessage = 'Не удалось загрузить каталог и остатки продавца.';

export function DashboardPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [dashboardMetrics, setDashboardMetrics] = useState<DashboardMetrics | null>(null);
  const [hasMoreProducts, setHasMoreProducts] = useState(false);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<InventoryFilter>('all');
  const [sort, setSort] = useState<'product' | 'available' | 'on-hand'>('product');
  const [selectedSkuId, setSelectedSkuId] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 6;

  async function load() {
    setPending(true);
    setError('');
    try {
      const [payload, summary] = await Promise.all([
        sellerApiRequest('/api/seller/products?limit=100&include_skus=true', { cache: 'no-store' }, decodeDashboardProducts),
        sellerApiRequest('/api/seller/dashboard/metrics', { cache: 'no-store' }, decodeDashboardMetrics),
      ]);
      const items = payload.items;
      setProducts(items);
      setDashboardMetrics(summary);
      setHasMoreProducts(payload.has_more);
      setSelectedSkuId((current) => current || items.flatMap((product) => product.skus ?? [])[0]?.id || '');
    } catch (cause) {
      setError(sellerErrorMessage(cause, errorMessage));
    } finally {
      setPending(false);
    }
  }

  useEffect(() => { void load(); }, []);

  const rows = useMemo<InventoryRow[]>(() => products.flatMap((product) =>
    (product.skus ?? []).map((sku) => ({ product, sku }))), [products]);

  const metrics = useMemo(() => {
    return {
      products: dashboardMetrics?.metrics.live_products ?? 0,
      skus: dashboardMetrics?.metrics.sku_count ?? 0,
      available: dashboardMetrics?.metrics.available_stock ?? 0,
      reserved: dashboardMetrics?.metrics.reserved_stock ?? 0,
      unavailable: rows.filter((row) => row.sku.is_active && row.sku.active_quantity === 0).length,
      moderation: dashboardMetrics?.metrics.pending_moderation ?? 0,
    };
  }, [dashboardMetrics, rows]);

  const counts = useMemo(() => ({
    all: rows.length,
    available: rows.filter((row) => row.sku.is_active && row.sku.active_quantity > 0).length,
    reserved: rows.filter((row) => row.sku.reserved_quantity > 0).length,
    unavailable: rows.filter((row) => row.sku.is_active && row.sku.active_quantity === 0).length,
  }), [rows]);

  const visibleRows = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('ru');
    const result = rows.filter(({ product, sku }) => {
      const matchesFilter = filter === 'all'
        || (filter === 'available' && sku.is_active && sku.active_quantity > 0)
        || (filter === 'reserved' && sku.reserved_quantity > 0)
        || (filter === 'unavailable' && sku.is_active && sku.active_quantity === 0);
      const matchesQuery = !normalizedQuery || [product.title, sku.name, sku.article]
        .some((value) => value?.toLocaleLowerCase('ru').includes(normalizedQuery));
      return matchesFilter && matchesQuery;
    });
    return result.sort((left, right) => {
      if (sort === 'available') return right.sku.active_quantity - left.sku.active_quantity;
      if (sort === 'on-hand') return right.sku.stock_quantity - left.sku.stock_quantity;
      return left.product.title.localeCompare(right.product.title, 'ru')
        || left.sku.name.localeCompare(right.sku.name, 'ru');
    });
  }, [rows, query, filter, sort]);

  const pageCount = Math.max(1, Math.ceil(visibleRows.length / pageSize));
  const pageRows = visibleRows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => { setPage(1); }, [query, filter, sort]);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);

  const selected = rows.find((row) => row.sku.id === selectedSkuId) ?? visibleRows[0] ?? null;

  const filters: Array<{ id: InventoryFilter; label: string; count: number }> = [
    { id: 'all', label: 'Все SKU', count: counts.all },
    { id: 'available', label: 'В наличии', count: counts.available },
    { id: 'reserved', label: 'С резервом', count: counts.reserved },
    { id: 'unavailable', label: 'Нет доступного остатка', count: counts.unavailable },
  ];

  return (
    <main className="seller-app seller-dashboard" id="main-content">
      <SellerSidebar
        variant="dashboard" activePath="/dashboard"
        badge="ДАННЫЕ B2B API"
        ariaLabel="Навигация продавца"
        tenant={<label className="seller-tenant"><span>Аккаунт продавца</span><strong>Мой кабинет</strong></label>}
        footer={<div className="seller-sidebar-foot"><span>Доступные позиции</span><strong>{pending ? '—' : metrics.available.toLocaleString('ru-RU')}</strong></div>}
      />

      <section className="seller-content seller-dashboard-content">
        <div className="seller-topbar">
          <div><span className="eyebrow">NEOMARKET / SELLER HUB</span><strong>Склад и каталог</strong></div>
          <a className="seller-product-link" href="/products/new">Добавить товар</a>
        </div>

        <div className="seller-system-strip" role="status">
          <span><i aria-hidden="true" />Данные синхронизируются напрямую с кабинетом продавца</span>
          <span>Обновление при открытии страницы</span>
        </div>
        {dashboardMetrics && <p className="seller-muted">Сводка B2B API на {new Date(dashboardMetrics.as_of).toLocaleString('ru-RU')}</p>}
        {hasMoreProducts && <p className="seller-state">Обзор показывает первые 100 товаров. Полный список с поиском и страницами доступен в разделе «Остатки».</p>}

        <div className="seller-dashboard-actions">
          <span className="eyebrow">LIVE B2B STOCK</span>
          <a className="seller-stock-export" href="/inventory" aria-label="Полный экспорт остатков">Экспорт остатков</a>
        </div>

        <header className="seller-dashboard-heading">
          <div>
            <p className="eyebrow">SELLER / INVENTORY</p>
            <h1>Управление каталогом<br className="dashboard-title-break" /> и остатками</h1>
          </div>
          <a className="seller-submit" href="/products">Открыть товары</a>
        </header>

        {pending && <p className="seller-state" role="status">Загружаем подтверждённые товары и SKU…</p>}
        {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => void load()}>Повторить</button></div>}

        {!pending && !error && <>
          <section className="seller-dashboard-metrics" aria-label="Сводка по складу">
            <article><span>Активные товары</span><strong>{metrics.products.toLocaleString('ru-RU')}</strong><small>Server aggregate</small></article>
            <article><span>SKU в каталоге</span><strong>{metrics.skus.toLocaleString('ru-RU')}</strong><small>По полной owner-scoped выборке</small></article>
            <article><span>Доступный остаток</span><strong>{metrics.available.toLocaleString('ru-RU')}</strong><small>После учёта резерва</small></article>
            <article><span>Зарезервировано</span><strong>{metrics.reserved.toLocaleString('ru-RU')}</strong><small>По данным складского API</small></article>
            <article className={metrics.unavailable > 0 ? 'metric-warning' : ''}><span>SKU без остатка</span><strong>{metrics.unavailable.toLocaleString('ru-RU')}</strong><small>Только среди показанных товаров</small></article>
          </section>

          <section className="seller-stock-workspace" aria-label="Товары и складские остатки">
            <div className="seller-stock-main">
              <div className="seller-stock-toolbar">
                <div className="seller-stock-tabs" aria-label="Разделы продавца">
                  <a className="active" href="/dashboard" aria-current="page">Товары и SKU <span>{rows.length}</span></a>
                  <a href="/inventory">Остатки</a>
                  <a href="/finance">Финансы</a>
          <a href="/moderation">Статусы модерации <span>{metrics.moderation}</span></a>
                </div>
                <label className="seller-stock-search">Поиск по названию или артикулу
                  <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название товара, SKU…" />
                </label>
              </div>

              <div className="seller-stock-filters" role="group" aria-label="Фильтр складского статуса">
                <span className="eyebrow">Быстрый фильтр</span>
                {filters.map((item) => <button key={item.id} type="button" className={filter === item.id ? 'active' : ''} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>{item.label}<strong>{item.count}</strong></button>)}
              </div>

              <div className="seller-stock-table-head">
                <span>Показано: {visibleRows.length === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, visibleRows.length)} из {visibleRows.length}</span>
                <label>Сортировка
                  <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
                    <option value="product">По названию</option>
                    <option value="available">По доступному остатку</option>
                    <option value="on-hand">По остатку на складе</option>
                  </select>
                </label>
              </div>

                {visibleRows.length === 0 ? <div className="seller-state seller-stock-empty"><h2>{rows.length ? 'Совпадений нет' : 'SKU пока не добавлены'}</h2><p>{rows.length ? 'Измените поисковый запрос или фильтр.' : 'Когда в товарах появятся SKU, складские позиции отобразятся здесь.'}</p></div> : <div className="seller-table-wrap seller-stock-table-wrap" tabIndex={0}><table className="seller-table seller-stock-table">
                <caption className="sr-only">Товары, SKU и текущие складские остатки</caption>
                <thead><tr><th scope="col">Товар</th><th scope="col">Артикул / SKU</th><th scope="col">Категория</th><th scope="col">Статус</th><th scope="col">На складе</th><th scope="col">Резерв</th><th scope="col">Доступно</th><th scope="col"><span className="sr-only">Выбрать SKU</span></th></tr></thead>
                <tbody>{pageRows.map(({ product, sku }) => { const image = [...(sku.images ?? []), ...(product.images ?? [])].sort((left, right) => (left.ordering ?? 0) - (right.ordering ?? 0))[0]?.url; return <tr key={sku.id} className={selected?.sku.id === sku.id ? 'selected' : ''}>
                  <th scope="row"><div className="seller-stock-product-cell"><StockThumbnail title={product.title} url={image} /><span className="seller-stock-product-info"><span className="seller-stock-product">{product.title}</span><span className="seller-stock-variant">{sku.name}</span></span></div></th>
                  <td className="seller-stock-article">{sku.article || '—'}</td>
                  <td>{product.category || '—'}</td>
                  <td><span className={`seller-stock-state ${sku.is_active ? sku.active_quantity > 0 ? 'in-stock' : 'no-stock' : 'inactive'}`}>{!sku.is_active ? 'Отключён' : sku.active_quantity > 0 ? 'В наличии' : 'Нет остатка'}</span></td>
                  <td>{sku.stock_quantity.toLocaleString('ru-RU')}</td>
                  <td>{sku.reserved_quantity.toLocaleString('ru-RU')}</td>
                  <td className="seller-stock-available">{sku.active_quantity.toLocaleString('ru-RU')}</td>
                  <td><button className="seller-row-select" type="button" aria-label={`Выбрать SKU ${product.title}, ${sku.name}`} aria-pressed={selected?.sku.id === sku.id} onClick={() => setSelectedSkuId(sku.id)}>Выбрать</button></td>
                </tr>; })}</tbody>
              </table></div>}

              {visibleRows.length > 0 && <nav className="seller-stock-pagination" aria-label="Страницы складских позиций">
                <span>Выбрано позиций: 0</span>
                <div className="seller-stock-page-controls">
                  <button type="button" aria-label="Первая страница" disabled={page === 1} onClick={() => setPage(1)}>|‹</button>
                  <button type="button" aria-label="Предыдущая страница" disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>‹</button>
                  <span>{page} / {pageCount}</span>
                  <button type="button" aria-label="Следующая страница" disabled={page === pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>›</button>
                  <button type="button" aria-label="Последняя страница" disabled={page === pageCount} onClick={() => setPage(pageCount)}>›|</button>
                </div>
              </nav>}
            </div>

            <aside className="seller-stock-detail" aria-label="Сводка выбранного SKU">
              <div className="seller-stock-detail-title"><span>Выбранная позиция</span><strong>{selected ? 'B2B / SKU' : 'Нет выбранного SKU'}</strong></div>
              {selected ? <>
                <p className="eyebrow">{selected.product.title}</p>
                <h2>{selected.sku.name}</h2>
                <p className="seller-stock-detail-code">{selected.sku.article || 'Артикул не указан'}</p>
                <dl>
                  <div><dt>На складе</dt><dd>{selected.sku.stock_quantity.toLocaleString('ru-RU')}</dd></div>
                  <div><dt>В резерве</dt><dd>{selected.sku.reserved_quantity.toLocaleString('ru-RU')}</dd></div>
                  <div><dt>Доступно</dt><dd>{selected.sku.active_quantity.toLocaleString('ru-RU')}</dd></div>
                </dl>
                <div className="seller-stock-detail-status"><span>Модерация товара</span><strong>{selected.product.status}</strong></div>
                <a className="seller-submit seller-stock-detail-action" href="/inventory">Управлять остатками</a>
                <a className="seller-product-link" href={`/products/${selected.product.id}`}>Открыть карточку товара</a>
              </> : <p className="seller-muted">Выберите строку, чтобы увидеть подтверждённые данные SKU.</p>}
            </aside>
          </section>
        </>}
      </section>
    </main>
  );
}
