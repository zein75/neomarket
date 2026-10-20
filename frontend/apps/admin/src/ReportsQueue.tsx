'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type Complaint = {
  id: string; entity_type: 'PRODUCT' | 'SELLER' | 'MEDIA'; entity_id: string; category?: string;
  status: 'NEW' | 'TRIAGED' | 'IN_REVIEW' | 'CLOSED' | 'ESCALATED'; priority?: number;
  assigned_to?: string | null; deadline_at?: string | null; created_at?: string;
};
type ComplaintDetail = Complaint & { timeline: { event_id: string; action: string; actor_id?: string | null; occurred_at: string; reason_code?: string | null; operation_id?: string | null; assigned_to?: string | null; outcome?: string | null }[] };
type Evidence = { complaint_id: string; evidence_refs: string[]; scan_status: 'NOT_CONFIGURED' };
type Page = { items: Complaint[]; page: { has_more: boolean; next_cursor: string | null } };

async function errorMessage(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  if (typeof body?.code === 'string') return `${body.code} (${response.status})`;
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.detail === 'string') return body.detail;
  if (body?.detail && typeof body.detail === 'object' && typeof (body.detail as { message?: unknown }).message === 'string') return (body.detail as { message: string }).message;
  return `Запрос не выполнен (${response.status})`;
}
function dateTime(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : `${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`;
}
const stateLabels: Record<Complaint['status'], string> = { NEW: 'Новая', TRIAGED: 'Разобрана', IN_REVIEW: 'В работе', CLOSED: 'Закрыта', ESCALATED: 'Эскалация' };
const entityLabels: Record<Complaint['entity_type'], string> = { PRODUCT: 'Товар', SELLER: 'Продавец', MEDIA: 'Медиа' };

export function ReportsQueue() {
  const [items, setItems] = useState<Complaint[]>([]);
  const cursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (append = false) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '30' });
    if (append && cursorRef.current) query.set('cursor', cursorRef.current);
    try {
      const response = await fetch(`/api/admin/v1/complaints?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(await errorMessage(new Response(JSON.stringify(body), { status: response.status })));
      const page = body as Page;
      setItems((current) => append ? [...current, ...page.items] : page.items);
      cursorRef.current = page.page.next_cursor;
      setHasMore(page.page.has_more);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить жалобы');
      if (!append) { setItems([]); cursorRef.current = null; setHasMore(false); }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, []);

  return <AdminShell section="/reports">
    <p className="eyebrow">ADMIN CONSOLE / TRUST & SAFETY</p>
    <div className="admin-heading-row"><div><h1>Жалобы</h1><p className="admin-intro">Очередь приходит из Admin API. Личность заявителя и закрытые данные в списке не раскрываются.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading}>Обновить</button></div>
    <div className="queue-toolbar"><span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} жалоб загружено`}</span></div>
    {error && <div className="admin-alert" role="alert"><strong>Очередь жалоб недоступна</strong><span>{error}</span><p>Проверьте сессию и разрешение complaint.read.</p></div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Жалоб нет</h2><p>Admin API не вернул доступных записей.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Жалоба</th><th>Объект</th><th>Категория</th><th>Статус</th><th>Приоритет</th><th>Исполнитель</th><th>Срок</th><th>Создана</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><th scope="row"><a className="ticket-link" href={`/reports/${encodeURIComponent(item.id)}`}>{item.id.slice(0, 8)}…</a><small>{item.id}</small></th><td>{entityLabels[item.entity_type]}<small>{item.entity_id}</small></td><td>{item.category ?? '—'}</td><td><span className={`state-pill state-${item.status.toLowerCase()}`}>{stateLabels[item.status]}</span></td><td><span className="priority-value">{item.priority ?? '—'}</span></td><td>{item.assigned_to ?? 'Не назначен'}</td><td>{dateTime(item.deadline_at)}</td><td>{dateTime(item.created_at)}</td></tr>)}</tbody></table></div>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>{loading ? 'Загрузка…' : 'Загрузить ещё'}</button></div>}
  </AdminShell>;
}

export function ReportDetail({ complaintId }: { complaintId: string }) {
  const [detail, setDetail] = useState<ComplaintDetail | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [etag, setEtag] = useState('');
  const [error, setError] = useState('');
  const [evidenceError, setEvidenceError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<'ASSIGN' | 'ESCALATE'>('ASSIGN');
  const [reasonCode, setReasonCode] = useState('');
  const [comment, setComment] = useState('');
  const [notice, setNotice] = useState('');
  const retryKey = useRef<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(''); setEvidenceError('');
    try {
      const response = await fetch(`/api/admin/v1/complaints/${encodeURIComponent(complaintId)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await errorMessage(response));
      const currentEtag = response.headers.get('etag');
      if (!currentEtag) throw new Error('API не вернул ETag версии; действия закрыты до восстановления concurrency-контракта.');
      const body = await response.json() as ComplaintDetail;
      setDetail(body); setEtag(currentEtag);
      try {
        const evidenceResponse = await fetch(`/api/admin/v1/complaints/${encodeURIComponent(complaintId)}/evidence`, { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!evidenceResponse.ok) throw new Error(await errorMessage(evidenceResponse));
        setEvidence(await evidenceResponse.json() as Evidence);
      } catch (caught) { setEvidence(null); setEvidenceError(caught instanceof Error ? caught.message : 'Доступ к evidence не подтверждён'); }
    } catch (caught) { setDetail(null); setError(caught instanceof Error ? caught.message : 'Не удалось загрузить жалобу'); }
    finally { setLoading(false); }
  }, [complaintId]);

  useEffect(() => { void load(); }, [load]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !etag || !/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode.trim())) { setError('Укажите reason code в формате A-Z, 0-9, _.'); return; }
    setBusy(true); setError(''); setNotice('');
    const key = retryKey.current ?? crypto.randomUUID(); retryKey.current = key;
    try {
      const response = await fetch(`/api/admin/v1/complaints/${encodeURIComponent(complaintId)}/actions`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': key, 'If-Match': etag },
        body: JSON.stringify({ action, reason_code: reasonCode.trim(), comment: comment.trim() || null }),
      });
      if (!response.ok) { retryKey.current = null; throw new Error(await errorMessage(response)); }
      retryKey.current = null;
      const operation = await response.json() as { operation_id?: string; status?: string; request_id?: string };
      setNotice(`API принял команду: ${operation.status ?? 'статус не указан'}${operation.operation_id ? ` · операция ${operation.operation_id}` : ''}. Это не подтверждает исполнение действия.`);
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Результат действия не подтверждён; повтор используйте с тем же содержимым.'); }
    finally { setBusy(false); }
  };

  return <AdminShell section="/reports">
    <p className="eyebrow">ADMIN CONSOLE / TRUST & SAFETY / CASE</p>
    <div className="admin-heading-row"><div><a className="text-link back-link" href="/reports">← К списку жалоб</a><h1>Карточка жалобы</h1><p className="admin-intro">Заявитель остаётся псевдонимизированным. Evidence показывается как digest и не считается безопасным до настроенного сканирования.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading || busy}>Обновить</button></div>
    {loading && <div className="admin-empty" role="status">Загрузка карточки…</div>}
    {error && <div className="admin-alert" role="alert"><strong>Операция недоступна или не подтверждена</strong><span>{error}</span><p>Обновите карточку перед повторным действием; введённые поля сохраняются.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    {detail && <>
      <div className="ticket-meta-grid report-meta"><div><span>Жалоба</span><strong>{detail.id}</strong></div><div><span>Статус</span><strong>{stateLabels[detail.status]}</strong></div><div><span>Приоритет</span><strong>{detail.priority ?? '—'}</strong></div><div><span>Версия</span><strong>{etag}</strong></div><div><span>Объект</span><strong>{entityLabels[detail.entity_type]} · {detail.entity_id}</strong></div><div><span>Категория</span><strong>{detail.category ?? '—'}</strong></div><div><span>Назначена</span><strong>{detail.assigned_to ?? 'Не назначена'}</strong></div><div><span>Срок</span><strong>{dateTime(detail.deadline_at)}</strong></div>
      </div>
      <div className="report-workspace"><section className="ticket-inspection">
        <article className="admin-panel"><h2>Сведения по обращению</h2><p>Created: {dateTime(detail.created_at)}</p><p>Reporter identity не предоставляется этому экрану.</p></article>
        <article className="admin-panel"><h2>Evidence</h2>{evidenceError && <div className="admin-alert" role="alert"><span>{evidenceError}</span></div>}{evidence && <><p>Состояние сканирования: <strong>{evidence.scan_status}</strong>. Содержимое не считается безопасным.</p>{evidence.evidence_refs.length ? <ul className="hash-list">{evidence.evidence_refs.map((digest) => <li key={digest}><code>{digest}</code></li>)}</ul> : <p>Digest evidence отсутствуют.</p>}</>}</article>
        <article className="admin-panel"><h2>История дела</h2>{detail.timeline.length ? <ol className="history-list">{detail.timeline.map((item) => <li key={item.event_id}><strong>{item.action}</strong><span>{dateTime(item.occurred_at)} · actor {item.actor_id ?? 'system'}{item.reason_code ? ` · ${item.reason_code}` : ''}{item.operation_id ? ` · operation ${item.operation_id}` : ''}</span></li>)}</ol> : <p>Событий в timeline нет.</p>}</article>
      </section><aside className="decision-column"><section className="admin-panel decision-panel"><p className="eyebrow">CASE ACTION</p><h2>Действие по жалобе</h2><form onSubmit={submit}>
        <label>Действие<select value={action} onChange={(event) => setAction(event.target.value as typeof action)}><option value="ASSIGN">Назначить себе</option><option value="ESCALATE">Эскалировать</option></select></label>
        <label>Reason code<input value={reasonCode} onChange={(event) => setReasonCode(event.target.value.toUpperCase())} maxLength={64} placeholder="КОД_ИЗ_ПОЛИТИКИ" required/><small>Код будет записан в аудит. Используйте код из внутренней политики.</small></label>
        <label>Комментарий<textarea rows={5} maxLength={3000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Контекст действия"/></label>
        <p className="form-hint">Каждое действие отправляется с ETag версии {etag} и idempotency key. Server permissions и optimistic concurrency остаются обязательными.</p>
        <button className="admin-button admin-button-primary decision-submit" disabled={busy || !reasonCode.trim()}>{busy ? 'Отправка…' : action === 'ASSIGN' ? 'Назначить себе' : 'Эскалировать'}</button>
        <p className="step-up-note">REQUEST_INFO, WARN, CLOSE требуют не настроенную доставку уведомлений. TEMP_HOLD и UNPUBLISH требуют настроенного MFA step-up; кнопки остаются закрытыми.</p>
      </form></section></aside></div>
    </>}
  </AdminShell>;
}
