'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerBoolean, sellerNullableString, sellerNumber, sellerObject, sellerString } from './lib/seller-api';

import { useCallback, useEffect, useState } from 'react';

type SellerOrder = {
  id: string;
  currency: string;
  status: string;
  total_minor: number;
  revision: number;
  allocated_at: string;
  seller_accepted_at: string | null;
  items: { id: string; product_title: string; sku_name: string; quantity: number }[];
};
type Payload = { items: SellerOrder[]; page: { has_more: boolean; next_cursor?: string | null }; as_of: string };

function decodeSellerOrder(value: unknown): SellerOrder {
  const order = sellerObject(value, 'order');
  return {
    id: sellerString(order.id, 'order.id'), currency: sellerString(order.currency, 'order.currency'), status: sellerString(order.status, 'order.status'),
    total_minor: sellerNumber(order.total_minor, 'order.total_minor'), revision: sellerNumber(order.revision, 'order.revision'),
    allocated_at: sellerString(order.allocated_at, 'order.allocated_at'), seller_accepted_at: sellerNullableString(order.seller_accepted_at, 'order.seller_accepted_at'),
    items: sellerArray(order.items, 'order.items', (value) => {
      const item = sellerObject(value, 'order item');
      return { id: sellerString(item.id, 'item.id'), product_title: sellerString(item.product_title, 'item.product_title'), sku_name: sellerString(item.sku_name, 'item.sku_name'), quantity: sellerNumber(item.quantity, 'item.quantity') };
    }),
  };
}

function decodeOrdersPayload(value: unknown): Payload {
  const payload = sellerObject(value, 'orders');
  const page = sellerObject(payload.page, 'orders.page');
  const next = page.next_cursor;
  if (next !== undefined && next !== null && typeof next !== 'string') throw new TypeError('orders.page.next_cursor must be a string or null');
  return { items: sellerArray(payload.items, 'orders.items', decodeSellerOrder), page: { has_more: sellerBoolean(page.has_more, 'orders.page.has_more'), ...(next !== undefined ? { next_cursor: next as string | null } : {}) }, as_of: sellerString(payload.as_of, 'orders.as_of') };
}

function money(amountMinor: number, currency: string) {
  const digits = new Intl.NumberFormat('ru-RU', { style: 'currency', currency }).resolvedOptions().maximumFractionDigits ?? 2;
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency }).format(amountMinor / (10 ** digits));
}

export function OrdersPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [cursor, setCursor] = useState('');
  const [previousCursors, setPreviousCursors] = useState<string[]>([]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const limit = 50;
  const load = useCallback(async (nextCursor = '') => {
    setPending(true); setError('');
    try {
      const query = new URLSearchParams({ limit: String(limit) }); if (nextCursor) query.set('cursor', nextCursor);
      const payload = await sellerApiRequest(`/api/seller/orders?${query}`, { cache: 'no-store' }, decodeOrdersPayload);
      setData(payload); setCursor(nextCursor);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось загрузить заказы'));
    } finally { setPending(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const hasNext = Boolean(data?.page.has_more && data.page.next_cursor);
  return (
    <main className="seller-app" id="main-content">
      <SellerSidebar variant="orders" activePath="/orders" badge="B2B API" />
      <section className="seller-content seller-orders-content">
        <div className="private-bar"><span>SELLER / ORDERS</span><span>ALLOCATIONS · SERVER DATA</span></div>
        <p className="eyebrow">SELLER HUB / SE-12</p>
        <div className="page-heading"><h1>Заказы</h1><span className="seller-order-count">{data?.items.length ?? '—'} НА ЭТОЙ СТРАНИЦЕ</span></div>
        <p className="seller-intro">Показаны только позиции, распределённые вашему аккаунту. Оплата и доставка появятся после подтверждения соответствующими сервисами.</p>
        {pending && <p className="seller-state" role="status">Загружаем распределённые заказы…</p>}
        {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => void load(cursor)}>Повторить</button></div>}
        {!pending && !error && data?.items.length === 0 && <div className="seller-state seller-order-empty"><div><p className="eyebrow">ALLOCATIONS / 0</p><h2>Пока нет распределённых заказов</h2><p>Список обновится, когда B2C передаст заказ в seller-проекцию.</p></div><span className="seller-order-empty-mark" aria-hidden="true">—</span></div>}
        {!pending && !error && !!data?.items.length && <>
          <div className="seller-table-wrap" tabIndex={0}><table className="seller-table seller-orders-table">
            <caption className="sr-only">Заказы и allocations продавца</caption>
            <thead><tr><th scope="col">Allocation</th><th scope="col">Создан</th><th scope="col">Позиции</th><th scope="col">Сумма</th><th scope="col">Состояние</th></tr></thead>
            <tbody>{data.items.map((order) => <tr key={order.id}>
              <th scope="row"><a className="seller-product-link" href={`/orders/${order.id}`}>{order.id.slice(0, 8).toUpperCase()}</a></th>
              <td>{new Date(order.allocated_at).toLocaleString('ru-RU')}</td>
              <td>{order.items.reduce((count, item) => count + item.quantity, 0)} шт. · {order.items.length} SKU</td>
              <td>{money(order.total_minor, order.currency)}</td>
              <td><span className="seller-order-status">{order.status}</span><small className="seller-order-status-note">{order.seller_accepted_at ? 'Получение подтверждено' : 'Ожидает подтверждения получения'}</small></td>
            </tr>)}</tbody>
          </table></div>
          <div className="seller-order-pagination"><span>Срез данных {new Date(data.as_of).toLocaleString('ru-RU')}</span><div><button className="seller-product-link" type="button" disabled={previousCursors.length === 0 || pending} onClick={() => { const history = [...previousCursors]; const previous = history.pop() || ''; setPreviousCursors(history); void load(previous); }}>Назад</button><button className="seller-submit" type="button" disabled={!hasNext || pending} onClick={() => { setPreviousCursors((history) => [...history, cursor]); void load(data.page.next_cursor || ''); }}>Далее</button></div></div>
        </>}
      </section>
    </main>
  );
}
