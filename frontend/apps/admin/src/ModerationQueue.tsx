'use client';

import { useCallback, useEffect, useState } from 'react';

type Ticket = {
  id: string; product_id: string; seller_id?: string | null;
  kind: string; status: string; priority: number; assigned_to?: string | null;
  created_at: string; submitted_revision: number; snapshot_hash: string; version: number;
  lease_expires_at?: string | null; deadline_at?: string | null;
};
type TicketPage = { items: Ticket[]; page: { has_more: boolean; next_cursor: string | null } };

const statusLabels: Record<string, string> = {
  NEW: 'Новая', IN_REVIEW: 'В работе', WAITING_SELLER: 'Ожидает продавца',
  ESCALATED: 'Эскалация', DECISION_PENDING: 'Решение обрабатывается',
  DECIDED: 'Решена', STALE: 'Устарела', CANCELLED: 'Отменена',
};
const kindLabels: Record<string, string> = {
  CREATE: 'Новая карточка', UPDATE: 'Изменение', MEDIA_UPDATE: 'Медиа',
  CATEGORY_CHANGE: 'Смена категории', RECHECK: 'Повторная проверка', REPORT: 'Жалоба', APPEAL: 'Апелляция',
};

function messageFrom(body: unknown, status: number) {
  if (body && typeof body === 'object') {
    const value = body as { detail?: unknown; code?: unknown; message?: unknown };
    if (typeof value.message === 'string') return value.message;
    if (typeof value.code === 'string') return `${value.code} (${status})`;
    if (typeof value.detail === 'string') return value.detail;
    if (value.detail && typeof value.detail === 'object') {
      const detail = value.detail as { code?: unknown; message?: unknown };
      if (typeof detail.message === 'string') return detail.message;
      if (typeof detail.code === 'string') return `${detail.code} (${status})`;
    }
  }
  return `Запрос не выполнен (${status})`;
}

function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function ModerationQueue() {
  const [items, setItems] = useState<Ticket[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (append = false) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '30' });
    if (append && cursor) query.set('cursor', cursor);
    if (status) query.set('status', status);
    if (priority) query.set('priority', priority);
    try {
      const response = await fetch(`/api/admin/v1/moderation/tickets?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(messageFrom(data, response.status));
      const result = data as TicketPage;
      setItems((current) => append ? [...current, ...result.items] : result.items);
      setCursor(result.page.next_cursor); setHasMore(result.page.has_more);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить очередь');
      if (!append) { setItems([]); setCursor(null); setHasMore(false); }
    } finally { setLoading(false); }
  }, [cursor, priority, status]);

  useEffect(() => { void load(false); }, [status, priority]);

  return <>
    <p className="eyebrow">ADMIN CONSOLE / MODERATION</p>
    <div className="admin-heading-row"><div><h1>Очередь модерации</h1><p className="admin-intro">Заявки загружаются из Admin API. Решения применяются только после проверки актуальной версии и блокировки заявки.</p></div><button className="admin-button" onClick={() => void load(false)} disabled={loading}>Обновить</button></div>
    <div className="queue-toolbar">
      <label>Статус<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Все статусы</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Приоритет<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="">Любой</option>{[5, 4, 3, 2, 1, 0].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} заявок на странице`}</span>
    </div>
    {error && <div className="admin-alert" role="alert"><strong>Очередь недоступна</strong><span>{error}</span><p>Проверьте сессию и доступность Admin API. Записи не подменяются демонстрационными данными.</p></div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Заявок нет</h2><p>Для выбранных фильтров API не вернул заявок.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table queue-table"><thead><tr><th>Заявка</th><th>Тип</th><th>Статус</th><th>Приоритет</th><th>Версия</th><th>Создана</th><th></th></tr></thead><tbody>
      {items.map((ticket) => <tr key={ticket.id}><th scope="row"><a className="ticket-link" href={`/moderation/${encodeURIComponent(ticket.id)}`}>{ticket.product_id.slice(0, 8)}…</a><small>{ticket.id}</small></th><td>{kindLabels[ticket.kind] ?? ticket.kind}</td><td><span className={`state-pill state-${ticket.status.toLowerCase()}`}>{statusLabels[ticket.status] ?? ticket.status}</span></td><td><span className="priority-value">{ticket.priority}</span></td><td>v{ticket.version} · rev {ticket.submitted_revision}</td><td>{dateTime(ticket.created_at)}{ticket.deadline_at && <small>Срок: {dateTime(ticket.deadline_at)}</small>}</td><td><a className="text-link" href={`/moderation/${encodeURIComponent(ticket.id)}`}>Открыть →</a></td></tr>)}
    </tbody></table></div>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>{loading ? 'Загрузка…' : 'Загрузить ещё'}</button></div>}
  </>;
}
