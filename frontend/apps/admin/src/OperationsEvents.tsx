'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type EventRow = { id: string; event_type: string; status: string; attempts?: number | null; last_error?: string | null; created_at?: string | null };
type EventPage = { items: EventRow[]; page: { has_more: boolean; next_cursor: string | null } };

async function apiError(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  if (typeof body?.code === 'string') return `${body.code} (${response.status})`;
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.detail === 'string') return body.detail;
  return `Запрос не выполнен (${response.status})`;
}
function time(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : `${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`;
}

export function OperationsEvents() {
  const [items, setItems] = useState<EventRow[]>([]);
  const cursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const retryKeys = useRef(new Map<string, string>());

  const load = useCallback(async (append = false) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '30' });
    if (append && cursorRef.current) query.set('cursor', cursorRef.current);
    try {
      const response = await fetch(`/api/admin/v1/operations/events?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiError(response));
      const page = await response.json() as EventPage;
      setItems((current) => append ? [...current, ...page.items] : page.items);
      cursorRef.current = page.page.next_cursor; setHasMore(page.page.has_more);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить события');
      if (!append) { setItems([]); cursorRef.current = null; setHasMore(false); }
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(false); }, []);

  const proposeRetry = async (event: EventRow) => {
    const reasonCode = reasons[event.id]?.trim() ?? '';
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode)) { setError('Укажите reason code в формате A-Z, 0-9, _.'); return; }
    setBusyId(event.id); setError(''); setNotice('');
    const key = retryKeys.current.get(event.id) ?? crypto.randomUUID(); retryKeys.current.set(event.id, key);
    try {
      const response = await fetch(`/api/admin/v1/operations/events/${encodeURIComponent(event.id)}/retry`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify({ reason_code: reasonCode, comment: null }),
      });
      if (!response.ok) { retryKeys.current.delete(event.id); throw new Error(await apiError(response)); }
      retryKeys.current.delete(event.id);
      const operation = await response.json() as { operation_id?: string; status?: string };
      setNotice(`Повторная доставка предложена: ${operation.status ?? 'статус не указан'}${operation.operation_id ? ` · операция ${operation.operation_id}` : ''}. Maker-checker approval и подтверждение доставки выполняются отдельно.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Результат предложения не подтверждён'); }
    finally { setBusyId(''); }
  };

  return <AdminShell section="/operations/events">
    <p className="eyebrow">ADMIN CONSOLE / OPERATIONS / OUTBOX</p>
    <div className="admin-heading-row"><div><h1>События outbox</h1><p className="admin-intro">События и попытки доставки загружаются из Admin API. Текст ошибок намеренно редактируется сервером.</p></div><button className="admin-button" onClick={() => void load(false)} disabled={loading}>Обновить</button></div>
    <div className="queue-toolbar"><span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} событий загружено`}</span><span className="privacy-note">Raw payload не раскрывается.</span></div>
    {error && <div className="admin-alert" role="alert"><strong>События недоступны</strong><span>{error}</span><p>Проверьте Admin-сессию и разрешение operations.events.read.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Событий нет</h2><p>Admin API не вернул события outbox.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table event-table"><thead><tr><th>Event ID</th><th>Тип</th><th>Статус</th><th>Попытки</th><th>Последняя ошибка</th><th>Создано</th><th>Команда</th></tr></thead><tbody>{items.map((event) => { const requestPending = retryKeys.current.has(event.id); return <tr key={event.id}><th scope="row"><code>{event.id}</code></th><td>{event.event_type}</td><td><span className={`state-pill state-${event.status.toLowerCase()}`}>{event.status}</span></td><td>{event.attempts ?? '—'}</td><td>{event.last_error ?? '—'}</td><td>{time(event.created_at)}</td><td>{['DEAD', 'RETRY'].includes(event.status) ? <div className="retry-cell"><label className="visually-hidden" htmlFor={`reason-${event.id}`}>Reason code for {event.id}</label><input id={`reason-${event.id}`} value={reasons[event.id] ?? ''} disabled={busyId === event.id || requestPending} onChange={(change) => setReasons((current) => ({ ...current, [event.id]: change.target.value.toUpperCase() }))} placeholder="КОД_ПРИЧИНЫ" maxLength={64}/><button className="admin-button" onClick={() => void proposeRetry(event)} disabled={busyId === event.id || !reasons[event.id]?.trim()}>{busyId === event.id ? 'Отправка…' : requestPending ? 'Повторить запрос' : 'Предложить повтор'}</button></div> : <span className="form-hint">Нет разрешённого повтора</span>}</td></tr>; })}</tbody></table></div>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>{loading ? 'Загрузка…' : 'Загрузить ещё'}</button></div>}
    <p className="form-hint operations-footnote">Повтор события создаёт операцию со статусом ожидания одобрения. Событие не считается доставленным до подтверждённого результата.</p>
  </AdminShell>;
}
