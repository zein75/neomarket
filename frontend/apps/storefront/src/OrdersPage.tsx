'use client';

import { useEffect, useState } from 'react';
import { LogoutButton } from './LogoutButton';

type Order = { id: string; status: string; total?: number; created_at?: string; items?: Array<{ name?: string; quantity?: number }> };

export function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const response = await fetch('/api/storefront/orders', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!response.ok) throw new Error('orders');
      const payload = await response.json() as { items?: unknown[] };
      setOrders(Array.isArray(payload.items) ? payload.items.filter((item): item is Order => Boolean(item && typeof item === 'object' && typeof (item as Order).id === 'string')) : []);
    } catch { setMessage('Заказы доступны только после входа в buyer-сессию.'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function cancel(id: string) {
    if (typeof window !== 'undefined' && !window.confirm('Отменить заказ? Операция необратима после подтверждения сервера.')) return;
    setPending(id); setMessage('');
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { credentials: 'include', cache: 'no-store' });
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string') throw new Error('csrf');
      const keyStorage = `neomarket.order-cancel.${id}`;
      let idempotencyKey = typeof window !== 'undefined' ? window.localStorage.getItem(keyStorage) ?? '' : '';
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(idempotencyKey)) {
        idempotencyKey = crypto.randomUUID();
        if (typeof window !== 'undefined') window.localStorage.setItem(keyStorage, idempotencyKey);
      }
      const response = await fetch(`/api/storefront/orders/${encodeURIComponent(id)}`, { method: 'POST', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrf.token, 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ reason: 'Отмена покупателем' }) });
      if (!response.ok) throw new Error('cancel');
      if (typeof window !== 'undefined') window.localStorage.removeItem(keyStorage);
      await load();
    } catch { setMessage('Отмена не выполнена. Статус заказа не изменён.'); }
    finally { setPending(null); }
  }

  return <main className="content-section">
    <div className="section-heading"><div><p className="eyebrow">ACCOUNT / ORDERS</p><h1>Мои заказы</h1></div><LogoutButton /></div>
    <p className="section-copy">История загружается из B2C API с проверкой владельца на каждый заказ.</p>
    {message && <div className="cart-validation-warning" role="alert">{message}</div>}
    {loading ? <div className="inline-state" role="status">Загружаем заказы…</div> : orders.length === 0 ? <div className="empty-state"><h3>Заказов пока нет</h3><a className="button button-primary" href="/catalog">Открыть каталог</a></div> : <div className="cart-list">{orders.map((order) => <article className="cart-line" key={order.id}><div><p className="eyebrow">{order.status}</p><h3><a href={`/account/orders/${order.id}`}>Заказ {order.id.slice(0, 8)}</a></h3><span>{order.items?.map((item) => `${item.name ?? 'Позиция'} × ${item.quantity ?? 0}`).join(', ')}</span><small className="mono">{order.created_at ? new Date(order.created_at).toLocaleString('ru-RU') : ''}</small></div><div className="cart-line-actions"><strong>{typeof order.total === 'number' ? `${(order.total / 100).toLocaleString('ru-RU')} ₽` : '—'}</strong>{['CREATED', 'PAID', 'ASSEMBLING'].includes(order.status) && <button className="text-button" type="button" disabled={pending === order.id} onClick={() => void cancel(order.id)}>{pending === order.id ? 'Отменяем…' : 'Отменить'}</button>}</div></article>)}</div>}
  </main>;
}
