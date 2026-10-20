'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerBoolean, sellerNumber, sellerObject, sellerOptionalBoolean, sellerString } from './lib/seller-api';

import { useCallback, useEffect, useState } from 'react';

type Product = { id: string; title: string; status: string; category?: string | null; deleted?: boolean; skus_count: number; total_active_quantity: number; updated_at: string };
type Payload = { items: Product[]; page?: { has_more: boolean; next_cursor?: string | null } };

function decodeProduct(value: unknown): Product {
  const row = sellerObject(value, 'product');
  const category = row.category;
  if (category !== undefined && category !== null && typeof category !== 'string') throw new TypeError('product.category must be a string or null');
  return {
    id: sellerString(row.id, 'product.id'), title: sellerString(row.title, 'product.title'), status: sellerString(row.status, 'product.status'),
    ...(category !== undefined ? { category: category as string | null } : {}),
    ...(row.deleted !== undefined ? { deleted: sellerOptionalBoolean(row.deleted, 'product.deleted') as boolean } : {}),
    skus_count: sellerNumber(row.skus_count, 'product.skus_count'), total_active_quantity: sellerNumber(row.total_active_quantity, 'product.total_active_quantity'), updated_at: sellerString(row.updated_at, 'product.updated_at'),
  };
}

function decodePayload(value: unknown): Payload {
  const payload = sellerObject(value, 'products');
  if (!Array.isArray(payload.items)) throw new TypeError('products.items must be an array');
  let page: Payload['page'];
  if (payload.page !== undefined) {
    const row = sellerObject(payload.page, 'products.page');
    const next = row.next_cursor;
    if (next !== undefined && next !== null && typeof next !== 'string') throw new TypeError('products.page.next_cursor must be a string or null');
    page = { has_more: sellerBoolean(row.has_more, 'products.page.has_more'), ...(next !== undefined ? { next_cursor: next as string | null } : {}) };
  }
  return { items: payload.items.map(decodeProduct), ...(page ? { page } : {}) };
}

export function ProductsPage() {
  const [data, setData] = useState<Payload | null>(null); const [cursor, setCursor] = useState(''); const [search, setSearch] = useState(''); const [pending, setPending] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async (nextCursor = '', query = search) => { setPending(true); setError(''); try { const params = new URLSearchParams(); if (nextCursor) params.set('cursor', nextCursor); if (query.trim()) params.set('search', query.trim()); const payload = await sellerApiRequest(`/api/seller/products?${params}`, { cache: 'no-store' }, decodePayload); setData(payload); setCursor(nextCursor); } catch (cause) { setError(sellerErrorMessage(cause, 'Не удалось загрузить товары')); } finally { setPending(false); } }, [search]);
  useEffect(() => { void load(); }, [load]);
  return <main className="seller-app" id="main-content"><SellerSidebar variant="catalog" activePath="/products" badge="OWNER-SCOPED API" /><section className="seller-content"><div className="private-bar"><span>SELLER / PRODUCTS</span><span>SERVER DATA ONLY</span></div><p className="eyebrow">SELLER HUB / SE-04</p><div className="page-heading"><h1>Товары</h1><a className="seller-product-link" href="/products/new">Новая карточка</a></div><form className="seller-search" onSubmit={(event) => { event.preventDefault(); void load('', search); }}><label htmlFor="product-search">Поиск по своим товарам<input id="product-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название или SKU" /></label><button className="seller-submit" type="submit" disabled={pending}>Найти</button></form>{pending && <p className="seller-state" role="status">Загружаем подтверждённые данные…</p>}{error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => void load(cursor, search)}>Повторить</button></div>}{!pending && !error && data?.items.length === 0 && <div className="seller-state"><h2>Товаров пока нет</h2><p>Создание карточки появится после подключения проверенного upload-контракта.</p></div>}{!pending && !error && !!data?.items.length && <><div className="seller-table-wrap" tabIndex={0}><table className="seller-table"><caption className="sr-only">Товары продавца</caption><thead><tr><th>Название</th><th>Статус</th><th>Категория</th><th>SKU</th><th>Остаток</th><th>Обновлён</th></tr></thead><tbody>{data.items.map((product) => <tr key={product.id}><th scope="row"><a className="seller-product-link" href={`/products/${product.id}`}>{product.title}</a></th><td><span className="status-badge">{product.deleted ? 'DELETED' : product.status}</span></td><td>{product.category || '—'}</td><td>{product.skus_count}</td><td>{product.total_active_quantity}</td><td>{new Date(product.updated_at).toLocaleDateString('ru-RU')}</td></tr>)}</tbody></table></div>{data.page?.has_more && <button className="seller-submit seller-next" type="button" onClick={() => void load(data.page?.next_cursor || '', search)}>Следующая страница</button>}</>}</section></main>;
}
