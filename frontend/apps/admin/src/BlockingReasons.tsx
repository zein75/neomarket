'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type Reason = { id: string; code: string; title: string; description?: string | null; severity: 'INFO' | 'FIX_REQUIRED' | 'REJECT' | 'HARD_BLOCK'; active: boolean; policy_version?: number | null };
type ReasonPage = { items: Reason[]; page: { has_more: boolean; next_cursor: string | null } };
type ReasonDraft = { code: string; title: string; description: string; severity: Reason['severity']; active: boolean };
type Retry = { key: string; body: unknown; signature: string };
const emptyDraft: ReasonDraft = { code: '', title: '', description: '', severity: 'FIX_REQUIRED', active: true };
const severities: Record<Reason['severity'], string> = { INFO: 'Информация', FIX_REQUIRED: 'Нужны исправления', REJECT: 'Отклонение', HARD_BLOCK: 'Жёсткая блокировка' };

async function apiError(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  if (typeof body?.code === 'string') return `${body.code} (${response.status})`;
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.detail === 'string') return body.detail;
  return `Запрос не выполнен (${response.status})`;
}

export function BlockingReasons() {
  const [items, setItems] = useState<Reason[]>([]);
  const cursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [draft, setDraft] = useState<ReasonDraft>(emptyDraft);
  const [editing, setEditing] = useState<Reason | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Reason | null>(null);
  const [archiveReason, setArchiveReason] = useState('');
  const [archiveComment, setArchiveComment] = useState('');
  const retry = useRef(new Map<string, Retry>());

  const load = useCallback(async (append = false) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '30' });
    if (append && cursorRef.current) query.set('cursor', cursorRef.current);
    try {
      const response = await fetch(`/api/admin/v1/blocking-reasons?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiError(response));
      const page = await response.json() as ReasonPage;
      setItems((current) => append ? [...current, ...page.items] : page.items);
      cursorRef.current = page.page.next_cursor; setHasMore(page.page.has_more);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить причины');
      if (!append) { setItems([]); cursorRef.current = null; setHasMore(false); }
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(false); }, [load]);

  const propose = async (operation: string, path: string, method: 'POST' | 'PATCH', body: unknown, etag?: string) => {
    setBusy(true); setError(''); setNotice('');
    const signature = JSON.stringify({ method, path, body, etag });
    let pending = retry.current.get(operation);
    if (pending && pending.signature !== signature) { setError('Предыдущий запрос не подтверждён. Повторите его с теми же полями.'); setBusy(false); return; }
    if (!pending) { pending = { key: crypto.randomUUID(), body, signature }; retry.current.set(operation, pending); }
    try {
      const response = await fetch(path, { method, cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key, ...(etag ? { 'If-Match': etag } : {}) }, body: JSON.stringify(pending.body) });
      retry.current.delete(operation);
      if (!response.ok) throw new Error(await apiError(response));
      const result = await response.json() as { operation_id?: string; status?: string };
      setNotice(`Изменение предложено: ${result.status ?? 'статус не указан'}${result.operation_id ? ` · операция ${result.operation_id}` : ''}. Причина изменится только после одобрения операции.`);
      if (operation === 'create' || operation === 'update') { setDraft(emptyDraft); setEditing(null); }
      if (operation === 'archive') { setArchiveTarget(null); setArchiveReason(''); setArchiveComment(''); }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Ответ сервера не получен; можно безопасно повторить ту же операцию.');
    } finally { setBusy(false); }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = { ...draft, code: draft.code.trim().toUpperCase(), title: draft.title.trim(), description: draft.description.trim() || null };
    if (!/^[A-Z][A-Z0-9_]{1,63}$/.test(body.code)) { setError('Code: от 2 до 64 символов A-Z, 0-9 и _.'); return; }
    if (body.title.length < 2) { setError('Название должно содержать не менее 2 символов.'); return; }
    if (editing) await propose('update', `/api/admin/v1/blocking-reasons/${encodeURIComponent(editing.id)}`, 'PATCH', body, `v${editing.policy_version ?? 1}`);
    else await propose('create', '/api/admin/v1/blocking-reasons', 'POST', body);
  };

  const archive = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!archiveTarget || !/^[A-Z][A-Z0-9_]{0,63}$/.test(archiveReason.trim())) { setError('Для архивации введите reason code из внутренней политики.'); return; }
    await propose('archive', `/api/admin/v1/blocking-reasons/${encodeURIComponent(archiveTarget.id)}/archive`, 'POST', { reason_code: archiveReason.trim().toUpperCase(), comment: archiveComment.trim() || null }, `v${archiveTarget.policy_version ?? 1}`);
  };

  const beginEdit = (item: Reason) => {
    setEditing(item); setArchiveTarget(null);
    setDraft({ code: item.code, title: item.title, description: item.description ?? '', severity: item.severity, active: item.active });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return <AdminShell section="/reasons">
    <p className="eyebrow">ADMIN CONSOLE / POLICY / REASONS</p>
    <div className="admin-heading-row"><div><h1>Причины блокировки</h1><p className="admin-intro">Справочник версионируется. Изменения и архивация создают maker-checker операции; исторические ссылки на причину не удаляются.</p></div><button className="admin-button" onClick={() => void load(false)} disabled={loading}>Обновить</button></div>
    {error && <div className="admin-alert" role="alert"><strong>Запрос не выполнен или не подтверждён</strong><span>{error}</span><p>Проверьте разрешения policy.reason.read/write и состояние операции перед повтором.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    <section className="admin-panel reason-editor"><p className="eyebrow">{editing ? 'UPDATE PROPOSAL' : 'NEW PROPOSAL'}</p><h2>{editing ? `Редактировать ${editing.code}` : 'Добавить причину'}</h2><form onSubmit={save}>
      <label>Code<input value={draft.code} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value.toUpperCase() }))} minLength={2} maxLength={64} required disabled={busy || retry.current.has(editing ? 'update' : 'create')}/></label>
      <label>Название<input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} minLength={2} maxLength={255} required disabled={busy || retry.current.has(editing ? 'update' : 'create')}/></label>
      <label>Описание<textarea rows={3} value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} maxLength={2000} disabled={busy || retry.current.has(editing ? 'update' : 'create')}/></label>
      <label>Severity<select value={draft.severity} onChange={(event) => setDraft((current) => ({ ...current, severity: event.target.value as Reason['severity'] }))} disabled={busy || retry.current.has(editing ? 'update' : 'create')}>{Object.entries(severities).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label className="reason-active"><input type="checkbox" checked={draft.active} onChange={(event) => setDraft((current) => ({ ...current, active: event.target.checked }))} disabled={busy || retry.current.has(editing ? 'update' : 'create')}/> Активна</label>
      <div className="reason-editor-actions"><button className="admin-button admin-button-primary" disabled={busy}>{busy ? 'Отправка…' : retry.current.has(editing ? 'update' : 'create') ? 'Повторить запрос' : 'Предложить изменение'}</button>{editing && <button type="button" className="admin-button" onClick={() => { setEditing(null); setDraft(emptyDraft); }} disabled={busy}>Отмена</button>}</div>
    </form></section>
    <div className="section-heading reason-list-heading"><div><p className="eyebrow">VERSIONED REGISTRY</p><h2>Список причин</h2></div><span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} причин загружено`}</span></div>
    {loading && <div className="admin-empty" role="status">Загрузка справочника…</div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Причин нет</h2><p>Admin API не вернул активных или архивных записей.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table reason-table"><thead><tr><th>Причина</th><th>Уровень</th><th>Статус</th><th>Версия политики</th><th>Команды</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><th scope="row"><strong>{item.title}</strong><small>{item.code}</small>{item.description && <p>{item.description}</p>}</th><td>{severities[item.severity]}</td><td><span className={`state-pill ${item.active ? 'state-decided' : ''}`}>{item.active ? 'Активна' : 'Архивирована'}</span></td><td>{item.policy_version ?? '—'}</td><td className="reason-actions">{item.active && <><button className="text-button" onClick={() => beginEdit(item)} disabled={busy}>Изменить</button><button className="text-button danger-link" onClick={() => { setArchiveTarget(item); setEditing(null); }} disabled={busy}>Архивировать</button></>}</td></tr>)}</tbody></table></div>}
    {archiveTarget && <section className="admin-panel archive-panel"><h2>Архивировать {archiveTarget.code}</h2><form onSubmit={archive}><label>Reason code<input value={archiveReason} onChange={(event) => setArchiveReason(event.target.value.toUpperCase())} maxLength={64} required placeholder="КОД_ИЗ_ПОЛИТИКИ"/></label><label>Комментарий<textarea rows={3} value={archiveComment} onChange={(event) => setArchiveComment(event.target.value)} maxLength={3000}/></label><div className="reason-editor-actions"><button className="admin-button admin-button-primary" disabled={busy || !archiveReason.trim()}>Предложить архивацию</button><button type="button" className="admin-button" onClick={() => setArchiveTarget(null)} disabled={busy}>Отмена</button></div></form></section>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>{loading ? 'Загрузка…' : 'Загрузить ещё'}</button></div>}
    <p className="form-hint reason-footer">Проведённые изменения будут видны после отдельного одобрения другим пользователем с необходимым разрешением и свежим step-up.</p>
  </AdminShell>;
}
