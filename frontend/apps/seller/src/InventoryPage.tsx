'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { SellerApiError, sellerApiRequest, sellerBoolean, sellerInteger, sellerNullableString, sellerObject, sellerOptionalNullableString, sellerString } from './lib/seller-api';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';

type InventoryItem = {
  sku_id: string;
  product_id: string;
  product_title: string;
  sku_name: string;
  seller_article: string | null;
  stock_quantity: number;
  reserved_quantity: number;
  active_quantity: number;
  is_active: boolean;
  revision: number;
};

type InventoryPayload = {
  items: InventoryItem[];
  page: { has_more: boolean; next_cursor?: string | null };
};
type InventoryMetrics = {
  as_of: string;
  metrics: { sku_count: number; total_on_hand: number; reserved_stock: number; available_stock: number };
};
type InventoryStatus = '' | 'available' | 'reserved' | 'unavailable' | 'inactive';
type InventoryExportJob = {
  id: string;
  state: 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED' | 'EXPIRED';
  row_count: number;
  failure_code?: string | null;
  download_url?: string | null;
  expires_at?: string | null;
};

type StockAdjustmentStatus = {
  status: 'COMMITTED';
  sku_id: string;
  delta: number;
  on_hand: number;
  reserved: number;
  available: number;
  ledger_entry_id: string | null;
};

type AdjustedSkuStock = { id: string; stock_quantity: number; reserved_quantity: number; active_quantity: number };

function decodeInventory(value: unknown): InventoryPayload {
  const payload = sellerObject(value, 'inventory');
  const page = sellerObject(payload.page, 'inventory.page');
  const next = page.next_cursor;
  if (next !== undefined && next !== null && typeof next !== 'string') throw new TypeError('inventory.page.next_cursor must be a string or null');
  const items = Array.isArray(payload.items) ? payload.items.map((value) => {
    const item = sellerObject(value, 'inventory item');
    return {
      sku_id: sellerString(item.sku_id, 'inventory.sku_id'), product_id: sellerString(item.product_id, 'inventory.product_id'),
      product_title: sellerString(item.product_title, 'inventory.product_title'), sku_name: sellerString(item.sku_name, 'inventory.sku_name'),
      seller_article: sellerNullableString(item.seller_article, 'inventory.seller_article'), stock_quantity: sellerInteger(item.stock_quantity, 'inventory.stock_quantity'),
      reserved_quantity: sellerInteger(item.reserved_quantity, 'inventory.reserved_quantity'), active_quantity: sellerInteger(item.active_quantity, 'inventory.active_quantity'),
      is_active: sellerBoolean(item.is_active, 'inventory.is_active'), revision: sellerInteger(item.revision, 'inventory.revision'),
    };
  }) : (() => { throw new TypeError('inventory.items must be an array'); })();
  return { items, page: { has_more: sellerBoolean(page.has_more, 'inventory.page.has_more'), ...(next !== undefined ? { next_cursor: next as string | null } : {}) } };
}

function decodeInventoryMetrics(value: unknown): InventoryMetrics {
  const payload = sellerObject(value, 'inventory summary');
  const metrics = sellerObject(payload.metrics, 'inventory summary metrics');
  return {
    as_of: sellerString(payload.as_of, 'inventory summary.as_of'),
    metrics: {
      sku_count: sellerInteger(metrics.sku_count, 'metrics.sku_count'), total_on_hand: sellerInteger(metrics.total_on_hand, 'metrics.total_on_hand'),
      reserved_stock: sellerInteger(metrics.reserved_stock, 'metrics.reserved_stock'), available_stock: sellerInteger(metrics.available_stock, 'metrics.available_stock'),
    },
  };
}

function decodeExportJob(value: unknown): InventoryExportJob {
  const job = sellerObject(value, 'inventory export');
  const state = sellerString(job.state, 'export.state');
  if (!['PENDING', 'PROCESSING', 'READY', 'FAILED', 'EXPIRED'].includes(state)) throw new TypeError('export.state is invalid');
  const failureCode = sellerOptionalNullableString(job.failure_code, 'export.failure_code');
  const downloadUrl = sellerOptionalNullableString(job.download_url, 'export.download_url');
  const expiresAt = sellerOptionalNullableString(job.expires_at, 'export.expires_at');
  return {
    id: sellerString(job.id, 'export.id'), state: state as InventoryExportJob['state'], row_count: sellerInteger(job.row_count, 'export.row_count'),
    ...(failureCode !== undefined ? { failure_code: failureCode } : {}), ...(downloadUrl !== undefined ? { download_url: downloadUrl } : {}),
    ...(expiresAt !== undefined ? { expires_at: expiresAt } : {}),
  };
}

function decodeCsrf(value: unknown): { token: string } {
  const payload = sellerObject(value, 'csrf');
  return { token: sellerString(payload.token, 'csrf.token') };
}

function decodeAdjustmentStatus(value: unknown): StockAdjustmentStatus {
  const operation = sellerObject(value, 'stock adjustment');
  if (operation.status !== 'COMMITTED') throw new TypeError('adjustment.status is invalid');
  return {
    status: 'COMMITTED', sku_id: sellerString(operation.sku_id, 'adjustment.sku_id'),
    delta: sellerInteger(operation.delta, 'adjustment.delta'), on_hand: sellerInteger(operation.on_hand, 'adjustment.on_hand'),
    reserved: sellerInteger(operation.reserved, 'adjustment.reserved'), available: sellerInteger(operation.available, 'adjustment.available'),
    ledger_entry_id: sellerNullableString(operation.ledger_entry_id, 'adjustment.ledger_entry_id'),
  };
}

function decodeAdjustedSku(value: unknown): AdjustedSkuStock {
  const sku = sellerObject(value, 'adjusted SKU');
  return {
    id: sellerString(sku.id, 'adjusted SKU.id'), stock_quantity: sellerInteger(sku.stock_quantity, 'adjusted SKU.stock_quantity'),
    reserved_quantity: sellerInteger(sku.reserved_quantity, 'adjusted SKU.reserved_quantity'), active_quantity: sellerInteger(sku.active_quantity, 'adjusted SKU.active_quantity'),
  };
}

function adjustmentMatches(operation: StockAdjustmentStatus, item: InventoryItem, delta: number): boolean {
  return operation.status === 'COMMITTED' && operation.sku_id === item.sku_id && operation.delta === delta
    && operation.available === operation.on_hand - operation.reserved && Boolean(operation.ledger_entry_id);
}

export function InventoryPage() {
  const [data, setData] = useState<InventoryPayload | null>(null);
  const [summary, setSummary] = useState<InventoryMetrics | null>(null);
  const [pageCursors, setPageCursors] = useState(['']);
  const [pageIndex, setPageIndex] = useState(0);
  const [query, setQuery] = useState('');
  const [queryInput, setQueryInput] = useState('');
  const [status, setStatus] = useState<InventoryStatus>('');
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [adjustmentError, setAdjustmentError] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [exportJob, setExportJob] = useState<InventoryExportJob | null>(null);
  const [exportError, setExportError] = useState('');
  const [exportPending, setExportPending] = useState(false);
  const exportKey = useRef<string | null>(null);

  const load = useCallback(async (cursor = '', search = '', statusFilter: InventoryStatus = '') => {
    setPending(true);
    setError('');
    try {
      const query = new URLSearchParams({ limit: '50' });
      if (cursor) query.set('cursor', cursor);
      if (search.trim()) query.set('query', search.trim());
      if (statusFilter) query.set('status', statusFilter);
      setData(await sellerApiRequest(`/api/seller/inventory?${query}`, { cache: 'no-store' }, decodeInventory));
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Unable to load inventory'));
    } finally {
      setPending(false);
    }
  }, []);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await sellerApiRequest('/api/seller/dashboard/metrics', { cache: 'no-store' }, decodeInventoryMetrics));
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Unable to load inventory summary'));
    }
  }, []);

  useEffect(() => { void load(); void loadSummary(); }, [load, loadSummary]);

  useEffect(() => {
    const savedJobId = sessionStorage.getItem('seller.inventoryExportJobId');
    if (savedJobId) setExportJob({ id: savedJobId, state: 'PROCESSING', row_count: 0 });
    exportKey.current = sessionStorage.getItem('seller.inventoryExportIdempotencyKey');
  }, []);

  useEffect(() => {
    if (!exportJob || !['PENDING', 'PROCESSING'].includes(exportJob.state)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const body = await sellerApiRequest(`/api/seller/inventory/exports/${exportJob.id}`, { cache: 'no-store' }, decodeExportJob);
        if (stopped) return;
        setExportError('');
        setExportJob(body);
        if (body.state === 'EXPIRED') sessionStorage.removeItem('seller.inventoryExportJobId');
        if (body.state === 'PENDING' || body.state === 'PROCESSING') timer = setTimeout(() => { void poll(); }, 1500);
      } catch (cause) {
        if (stopped) return;
        setExportError(sellerErrorMessage(cause, 'Не удалось проверить состояние экспорта. Повторяем запрос…'));
        timer = setTimeout(() => { void poll(); }, 3000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [exportJob?.id, exportJob?.state]);

  async function startExport() {
    setExportPending(true);
    setExportError('');
    const key = exportKey.current ?? sessionStorage.getItem('seller.inventoryExportIdempotencyKey') ?? crypto.randomUUID();
    exportKey.current = key;
    sessionStorage.setItem('seller.inventoryExportIdempotencyKey', key);
    try {
      const csrf = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, decodeCsrf);
      const body = await sellerApiRequest('/api/seller/inventory/exports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token, 'Idempotency-Key': key },
        body: JSON.stringify({ format: 'CSV', query: query || null, status: status || null }),
      }, decodeExportJob);
      exportKey.current = null;
      sessionStorage.removeItem('seller.inventoryExportIdempotencyKey');
      sessionStorage.setItem('seller.inventoryExportJobId', body.id);
      setExportJob(body);
    } catch (cause) {
      if (cause instanceof SellerApiError && cause.status < 500) {
        exportKey.current = null;
        sessionStorage.removeItem('seller.inventoryExportIdempotencyKey');
      }
      setExportError(sellerErrorMessage(cause, 'Экспорт не подтверждён сервером. Повторите тот же запрос.'));
    } finally {
      setExportPending(false);
    }
  }

  async function adjust(item: InventoryItem, form: HTMLFormElement) {
    const formData = new FormData(form);
    const delta = Number(formData.get('delta'));
    const reason = String(formData.get('reason') || '').trim();
    if (!Number.isInteger(delta) || delta === 0 || reason.length < 3 || reason.length > 64) {
      setAdjustmentError('Enter a nonzero stock change and a reason between 3 and 64 characters.');
      return;
    }

    setBusy(item.sku_id);
    setError('');
    setAdjustmentError('');
    setNotice('');
    const storageKey = `neomarket.stock-adjustment.${item.sku_id}.${delta}.${encodeURIComponent(reason).slice(0, 600)}`;
    let idempotencyKey = window.localStorage.getItem(storageKey) ?? '';
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(idempotencyKey)) {
      idempotencyKey = crypto.randomUUID();
      window.localStorage.setItem(storageKey, idempotencyKey);
    }

    try {
      const csrf = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, decodeCsrf);
      const adjustedSku = await sellerApiRequest(`/api/seller/skus/${item.sku_id}/stock-adjustments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token, 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ delta, reason }),
      }, decodeAdjustedSku);
      if (adjustedSku.id !== item.sku_id || adjustedSku.stock_quantity !== item.stock_quantity + delta
        || adjustedSku.reserved_quantity !== item.reserved_quantity || adjustedSku.active_quantity !== adjustedSku.stock_quantity - adjustedSku.reserved_quantity) {
        throw new Error('Stock adjustment response did not match the requested operation');
      }
      window.localStorage.removeItem(storageKey);
      setNotice(`Server confirmed stock for ${item.sku_name}.`);
      form.reset();
      await Promise.all([load(pageCursors[pageIndex] ?? '', query, status), loadSummary()]);
    } catch {
      try {
        const operation = await sellerApiRequest(`/api/seller/inventory/adjustments/${idempotencyKey}`, { cache: 'no-store' }, decodeAdjustmentStatus);
        if (adjustmentMatches(operation, item, delta)) {
          window.localStorage.removeItem(storageKey);
          setNotice(`Server confirmed stock for ${item.sku_name}.`);
          form.reset();
          await Promise.all([load(pageCursors[pageIndex] ?? '', query, status), loadSummary()]);
          return;
        }
        setAdjustmentError('The server has not confirmed this stock change. Retry the same adjustment later; the same operation key will be reused.');
      } catch {
        setAdjustmentError('The stock change response was lost and its status is unavailable. Retry the same adjustment later; the same operation key will be reused.');
      }
    } finally {
      setBusy('');
    }
  }
  function nextPage() {
    const nextCursor = data?.page.next_cursor;
    if (!nextCursor) return;
    const nextIndex = pageIndex + 1;
    setPageCursors((current) => [...current.slice(0, nextIndex), nextCursor]);
    setPageIndex(nextIndex);
    void load(nextCursor, query, status);
  }

  function previousPage() {
    if (pageIndex === 0) return;
    const previousIndex = pageIndex - 1;
    setPageIndex(previousIndex);
    void load(pageCursors[previousIndex] ?? '', query, status);
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageCursors(['']);
    setPageIndex(0);
    setQuery(queryInput.trim());
    void load('', queryInput.trim(), status);
  }

  function updateStatus(value: InventoryStatus) {
    setStatus(value);
    setPageCursors(['']);
    setPageIndex(0);
    void load('', query, value);
  }

  const asOf = summary ? new Date(summary.as_of).toLocaleString('ru-RU') : '';

  return (
    <main className="seller-app" id="main-content">
      <SellerSidebar variant="inventory" activePath="/inventory" badge="CONFIRMED API" />
      <section className="seller-content">
        <div className="private-bar"><span>SELLER / INVENTORY</span><span>SERVER CONFIRMED</span></div>
        <p className="eyebrow">SELLER HUB / SE-09</p>
        <div className="page-heading"><h1>Остатки</h1><a className="seller-product-link" href="/imports">Импорт CSV</a></div>
        <p className="seller-intro">Изменение остатка подтверждается сервером и защищено ключом идемпотентности.</p>
        <form className="seller-search" onSubmit={applyFilters}>
          <label htmlFor="inventory-search">Товар или SKU
            <input id="inventory-search" value={queryInput} maxLength={120} onChange={(event) => setQueryInput(event.target.value)} placeholder="Название или вариант" />
          </label>
          <label htmlFor="inventory-status">Наличие
            <select id="inventory-status" value={status} onChange={(event) => updateStatus(event.target.value as InventoryStatus)}>
              <option value="">Все позиции</option><option value="available">Доступно</option>
              <option value="reserved">Есть резерв</option><option value="unavailable">Нет доступного остатка</option>
              <option value="inactive">Неактивные SKU</option>
            </select>
          </label>
          <button className="seller-submit" type="submit" disabled={pending}>Найти</button>
        </form>
        <button className="seller-submit" type="button" onClick={() => void startExport()} disabled={exportPending || pending}>
          {exportPending ? 'Запрашиваем экспорт…' : 'Сформировать полный CSV'}
        </button>
        {exportJob && ['PENDING', 'PROCESSING'].includes(exportJob.state) && <p className="seller-state" role="status">Формируем CSV на сервере…</p>}
        {exportError && <p className="seller-state seller-error" role="alert">{exportError}</p>}
        {exportJob?.state === 'READY' && exportJob.download_url && <p className="seller-notice" role="status">
          Экспорт готов: {exportJob.row_count.toLocaleString('ru-RU')} SKU. <a className="seller-product-link" href={exportJob.download_url}>Скачать CSV</a>
        </p>}
        {exportJob?.state === 'FAILED' && <p className="seller-state seller-error" role="alert">
          Не удалось сформировать экспорт ({exportJob.failure_code ?? 'EXPORT_FAILED'}). Уточните фильтр или повторите запрос.
        </p>}
        {summary && <>
          <div className="seller-inventory-summary" aria-label="Сводка остатков">
            <div><span>SKU</span><strong>{summary.metrics.sku_count}</strong></div>
            <div><span>На складе</span><strong>{summary.metrics.total_on_hand}</strong></div>
            <div><span>В резерве</span><strong>{summary.metrics.reserved_stock}</strong></div>
            <div><span>Доступно</span><strong>{summary.metrics.available_stock}</strong></div>
          </div>
          <p className="seller-muted">Сводка на {asOf}</p>
        </>}
        {pending && <p className="seller-state" role="status">Загружаем остатки…</p>}
        {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => { void load(pageCursors[pageIndex] ?? '', query, status); void loadSummary(); }}>Повторить</button></div>}
        {notice && <p className="seller-notice" role="status">{notice}</p>}
        {adjustmentError && <div className="seller-state seller-error" role="alert">{adjustmentError}</div>}
        {!pending && !error && data?.items.length === 0 && <div className="seller-state"><h2>SKU для управления нет</h2><p>Добавьте товар и его вариант, чтобы управлять остатками.</p></div>}
        {!pending && !error && !!data?.items.length && <>
          <div className="inventory-grid">
            {data.items.map((item) => <article className="inventory-card" key={item.sku_id}>
              <div><p className="eyebrow">{item.product_title}</p><h2>{item.sku_name}</h2><p className="mono">Артикул: {item.seller_article || 'не задан'} · SKU {item.sku_id.slice(0, 8)}</p></div>
              <dl>
                <div><dt>На складе</dt><dd>{item.stock_quantity}</dd></div>
                <div><dt>Доступно</dt><dd>{item.active_quantity}</dd></div>
                <div><dt>Резерв</dt><dd>{item.reserved_quantity}</dd></div>
              </dl>
              <form onSubmit={(event) => { event.preventDefault(); void adjust(item, event.currentTarget); }}>
                <label>Изменение<input name="delta" type="number" step="1" required placeholder="+10 или -2" /></label>
                <label>Причина<input name="reason" minLength={3} maxLength={64} required placeholder="Приёмка, списание…" /></label>
                <button className="seller-submit" type="submit" disabled={busy === item.sku_id}>{busy === item.sku_id ? 'Сохраняем…' : 'Изменить остаток'}</button>
              </form>
            </article>)}
          </div>
          <div className="seller-pagination" aria-label="Страницы остатков">
            <button className="seller-submit" type="button" onClick={previousPage} disabled={pending || pageIndex === 0}>Назад</button>
            <span>Страница {pageIndex + 1} · по 50 SKU</span>
            <button className="seller-submit" type="button" onClick={nextPage} disabled={pending || !data.page.has_more}>Дальше</button>
          </div>
        </>}
      </section>
    </main>
  );
}
