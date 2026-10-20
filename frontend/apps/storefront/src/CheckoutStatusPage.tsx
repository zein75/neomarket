'use client';

import { useEffect, useState } from 'react';

type Operation = { operation_id?: string; state?: 'COMPLETED' | 'FAILED' | 'RECONCILE_REQUIRED' | 'PENDING'; order_id?: string | null; updated_at?: string };

const terminalStates = new Set<Operation['state']>(['COMPLETED', 'FAILED']);

export function CheckoutStatusPage({ operationId }: { operationId: string }) {
  const [operation, setOperation] = useState<Operation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reconcile, setReconcile] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const response = await fetch(`/api/storefront/checkout/attempts/${encodeURIComponent(operationId)}`, { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!response.ok) throw new Error('operation');
      const next = await response.json() as Operation;
      setOperation(next); setError(false); return next;
    } catch { setError(true); return null; } finally { setLoading(false); }
  }

  useEffect(() => {
    if (!/^[0-9a-f-]{36}$/i.test(operationId)) { setLoading(false); setError(true); return; }
    let stopped = false; let attempts = 0; let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (stopped) return;
      const next = await load(); attempts += 1;
      if (!stopped && next && !terminalStates.has(next.state) && attempts < 15) timer = setTimeout(() => { void poll(); }, 2000);
      else if (!stopped && next && !terminalStates.has(next.state) && attempts >= 15) setReconcile(true);
    };
    void poll();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [operationId]);

  const state = operation?.state ?? (error ? 'UNAVAILABLE' : reconcile ? 'RECONCILE_REQUIRED' : 'PENDING');
  const orderId = operation?.order_id ?? null;
  return <main className="content-section"><p className="eyebrow">SF-08 / CHECKOUT STATUS</p><h1>Статус checkout</h1><div className="empty-state" role="status" aria-live="polite"><p className="eyebrow">OPERATION {operationId.slice(0, 8)}</p>{loading ? <h3>Проверяем authoritative API…</h3> : <><h3>{state === 'COMPLETED' ? 'Заказ подтверждён' : state === 'FAILED' ? 'Checkout завершился отказом' : state === 'RECONCILE_REQUIRED' ? 'Нужна сверка операции' : state === 'UNAVAILABLE' ? 'Статус временно недоступен' : 'Операция ещё выполняется'}</h3><p>{state === 'RECONCILE_REQUIRED' ? 'Не создавайте новый заказ и не повторяйте POST с новым ключом. Сохраните идентификатор операции и обратитесь в поддержку.' : operation?.updated_at ? `Последнее обновление: ${new Date(operation.updated_at).toLocaleString('ru-RU')}` : 'Сервер ещё не подтвердил финальный результат.'}</p>{orderId && <a className="button button-primary" href={`/account/orders/${orderId}`}>Открыть заказ</a>}{state !== 'COMPLETED' && state !== 'FAILED' && !reconcile && <button className="button button-secondary" type="button" onClick={() => void load()}>Обновить статус</button>}{error && <button className="button button-secondary" type="button" onClick={() => void load()}>Повторить запрос</button>}</>}</div><a className="button button-primary" href="/account/orders">Мои заказы</a></main>;
}
