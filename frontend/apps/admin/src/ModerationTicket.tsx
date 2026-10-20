'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type Ticket = {
  id: string; product_id: string; seller_id?: string | null; kind: string; status: string;
  priority: number; assigned_to?: string | null; created_at: string; submitted_revision: number;
  snapshot_hash: string; version: number; lease_expires_at?: string | null; deadline_at?: string | null;
};
type Snapshot = {
  product_id: string; seller_id?: string | null; revision: number; snapshot_hash: string;
  title?: string | null; description?: string | null; category_id?: string | null;
  images: { media_id?: string | null; url: string; status?: string | null }[];
  skus: { sku_id?: string | null; name?: string | null; price_minor?: number | null; currency?: string | null; attributes?: Record<string, unknown> | null; images: { url: string }[] }[];
  attributes: Record<string, unknown>; policy_version: number;
};
type Detail = {
  ticket: Ticket; snapshot: Snapshot; published_revision?: number | null;
  field_diff?: { path?: string | null; before?: unknown; after?: unknown }[] | null;
  checklist: { code?: string | null; passed?: boolean | null; message?: string | null }[];
  history?: { action?: string | null; actor_id?: string | null; occurred_at?: string | null }[] | null;
};
type Reason = { id: string; code: string; title: string; description?: string | null; severity: string; active: boolean; policy_version?: number | null };
type Lease = { ticket: Ticket; claim_token: string; lease_expires_at: string; fencing_version: number };

async function responseError(response: Response) {
  const body = await response.json().catch(() => null) as { detail?: unknown; code?: unknown; message?: unknown } | null;
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.code === 'string') return `${body.code} (${response.status})`;
  if (typeof body?.detail === 'string') return body.detail;
  if (body?.detail && typeof body.detail === 'object') {
    const detail = body.detail as { code?: unknown; message?: unknown };
    if (typeof detail.message === 'string') return detail.message;
    if (typeof detail.code === 'string') return `${detail.code} (${response.status})`;
  }
  return `Запрос не выполнен (${response.status})`;
}
function formatTime(value?: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}
function json(value: unknown) { return value === undefined ? '—' : JSON.stringify(value, null, 2); }

export function ModerationTicket({ ticketId }: { ticketId: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [lease, setLease] = useState<Lease | null>(null);
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [action, setAction] = useState<'APPROVE' | 'CHANGES_REQUESTED' | 'REJECT' | 'ESCALATE'>('CHANGES_REQUESTED');
  const [selectedReasons, setSelectedReasons] = useState<string[]>([]);
  const [passedRules, setPassedRules] = useState('');
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const errorRef = useRef<HTMLDivElement>(null);
  const retryKeys = useRef(new Map<string, string>());

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await fetch(`/api/admin/v1/moderation/tickets/${encodeURIComponent(ticketId)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json() as Detail;
      setDetail(data);
    } catch (caught) { setDetail(null); setError(caught instanceof Error ? caught.message : 'Не удалось загрузить заявку'); }
    finally { setLoading(false); }
  }, [ticketId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const mutation = async (operation: string, path: string, body?: unknown, currentTicket = detail?.ticket) => {
    if (!currentTicket) return null;
    setBusy(true); setError(''); setNotice('');
    const idempotencyKey = retryKeys.current.get(operation) ?? crypto.randomUUID();
    retryKeys.current.set(operation, idempotencyKey);
    try {
      const init: RequestInit = {
        method: 'POST', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey, 'If-Match': `v${currentTicket.version}` },
      };
      if (body !== undefined) init.body = JSON.stringify(body);
      const response = await fetch(path, init);
      if (!response.ok) throw new Error(await responseError(response));
      retryKeys.current.delete(operation);
      return await response.json().catch(() => ({}));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось выполнить действие');
      return null;
    } finally { setBusy(false); }
  };

  const claim = async () => {
    const result = await mutation('claim', `/api/admin/v1/moderation/tickets/${encodeURIComponent(ticketId)}/claim`);
    if (result) { setLease(result as Lease); await load(); setNotice('Заявка закреплена за вами; токен claim хранится только в памяти текущей страницы.'); }
  };
  const release = async () => {
    if (!lease || !detail) return;
    const result = await mutation('release', `/api/admin/v1/moderation/tickets/${encodeURIComponent(ticketId)}/release`, { claim_token: lease.claim_token, fencing_version: lease.fencing_version });
    if (result) { setLease(null); await load(); setNotice('Claim освобождён.'); }
  };
  const heartbeat = async () => {
    if (!lease || !detail) return;
    const result = await mutation('heartbeat', `/api/admin/v1/moderation/tickets/${encodeURIComponent(ticketId)}/heartbeat`, { claim_token: lease.claim_token, fencing_version: lease.fencing_version });
    if (result) { setLease(result as Lease); await load(); setNotice(`Lease продлён до ${formatTime((result as Lease).lease_expires_at)}.`); }
  };

  const submitDecision = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!lease || !detail) return;
    if (action === 'APPROVE' && !passedRules.trim()) { setError('Для APPROVE укажите хотя бы одно проверенное правило.'); return; }
    if (action !== 'APPROVE' && !selectedReasons.length) { setError('Выберите причину для этого решения.'); return; }
    const payload = {
      action,
      claim_token: lease.claim_token,
      product_revision: detail.snapshot.revision,
      snapshot_hash: detail.snapshot.snapshot_hash,
      reason_codes: selectedReasons,
      passed_rules: action === 'APPROVE' ? passedRules.split(',').map((value) => value.trim()).filter(Boolean) : [],
      field_reports: [],
      comment: comment.trim() || null,
      policy_version: detail.snapshot.policy_version,
    };
    const result = await mutation('decision', `/api/admin/v1/moderation/tickets/${encodeURIComponent(ticketId)}/decisions`, payload);
    if (result) {
      const decision = result as { status?: string; operation_id?: string };
      setLease(null); await load();
      setNotice(`Решение принято API со статусом ${decision.status ?? 'неизвестен'}${decision.operation_id ? ` · операция ${decision.operation_id}` : ''}. Это не подтверждает публикацию товара.`);
    }
  };

  useEffect(() => {
    if (!detail) return;
    let active = true;
    void fetch('/api/admin/v1/blocking-reasons?limit=100', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json(); })
      .then((data: { items?: Reason[] }) => { if (active) setReasons((data.items ?? []).filter((reason) => reason.active)); })
      .catch(() => { if (active) setReasons([]); });
    return () => { active = false; };
  }, [detail?.ticket.id]);

  return <AdminShell section="/moderation">
    <p className="eyebrow">ADMIN CONSOLE / MODERATION / ЗАЯВКА</p>
    <div className="admin-heading-row ticket-heading"><div><a className="text-link back-link" href="/moderation">← К очереди</a><h1>Проверка заявки</h1><p className="admin-intro">Снимок товара проверяется по сохранённой ревизии и хешу. Доступность решения зависит от серверных прав и активного claim.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading || busy}>Обновить</button></div>
    {loading && <div className="admin-empty" role="status">Загрузка заявки из Admin API…</div>}
    {error && <div id="moderation-operation-error" ref={errorRef} className="admin-alert" role="alert" aria-live="assertive" tabIndex={-1}><strong>Операция не подтверждена</strong><span>{error}</span><p>Обновите данные и проверьте состояние заявки перед повторным действием.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    {detail && <>
      <div className="ticket-meta-grid">
        <div><span>Ticket</span><strong>{detail.ticket.id}</strong></div><div><span>Статус</span><strong>{detail.ticket.status}</strong></div>
        <div><span>Приоритет</span><strong>{detail.ticket.priority}</strong></div><div><span>Версия заявки</span><strong>v{detail.ticket.version}</strong></div>
        <div><span>Ревизия товара</span><strong>{detail.snapshot.revision}</strong></div><div><span>Опубликованная ревизия</span><strong>{detail.published_revision ?? 'Нет данных'}</strong></div>
        <div className="hash-cell"><span>Хеш снимка</span><code>{detail.snapshot.snapshot_hash}</code></div>
      </div>
      {lease ? <div className="claim-bar"><div><strong>Claim активен</strong><span>До {formatTime(lease.lease_expires_at)} · fencing {lease.fencing_version}</span></div><button className="admin-button" onClick={() => void heartbeat()} disabled={busy}>Продлить claim</button><button className="admin-button admin-button-quiet" onClick={() => void release()} disabled={busy}>Освободить</button></div> : <div className="claim-bar"><div><strong>Заявка не закреплена в этой сессии</strong><span>Для решения сначала получите claim с текущей версией заявки.</span></div><button className="admin-button admin-button-primary" onClick={() => void claim()} disabled={busy || detail.ticket.status === 'DECIDED' || detail.ticket.status === 'CANCELLED'}>{busy ? 'Выполняется…' : 'Взять в работу'}</button></div>}
      <div className="ticket-workspace">
        <article className="ticket-inspection">
          <section className="admin-panel"><p className="eyebrow">СНИМОК ТОВАРА · REV {detail.snapshot.revision}</p><h2>{detail.snapshot.title || 'Без названия'}</h2><p className="snapshot-description">{detail.snapshot.description || 'Описание отсутствует в снимке.'}</p><dl className="snapshot-details"><div><dt>Product ID</dt><dd>{detail.snapshot.product_id}</dd></div><div><dt>Seller ID</dt><dd>{detail.snapshot.seller_id ?? '—'}</dd></div><div><dt>Категория ID</dt><dd>{detail.snapshot.category_id ?? '—'}</dd></div></dl></section>
          <section className="admin-panel"><h2>Изображения</h2>{detail.snapshot.images.length ? <ul className="media-list">{detail.snapshot.images.map((image, index) => <li key={`${image.media_id ?? image.url}-${index}`}><span>{image.status ?? 'Медиа'} · {image.media_id ?? 'без ID'}</span><a href={image.url} target="_blank" rel="noreferrer">Открыть оригинал ↗</a></li>)}</ul> : <p>В снимке нет изображений.</p>}</section>
          <section className="admin-panel"><h2>SKU и цены</h2>{detail.snapshot.skus.length ? <div className="sku-list">{detail.snapshot.skus.map((sku, index) => <div className="sku-card" key={sku.sku_id ?? index}><strong>{sku.name || `SKU ${index + 1}`}</strong><span>{sku.price_minor == null ? 'Цена не задана' : `${(sku.price_minor / 100).toFixed(2)} ${sku.currency ?? ''}`}</span><small>{sku.sku_id ?? 'ID отсутствует'}</small><pre>{json(sku.attributes)}</pre>{sku.images.map((image, imageIndex) => <a key={image.url + imageIndex} href={image.url} target="_blank" rel="noreferrer">Изображение {imageIndex + 1} ↗</a>)}</div>)}</div> : <p>Снимок не содержит SKU.</p>}</section>
          <section className="admin-panel"><h2>Атрибуты</h2><pre>{json(detail.snapshot.attributes)}</pre></section>
          <section className="admin-panel"><h2>Изменения и проверки</h2>{detail.field_diff?.length ? <ul className="diff-list">{detail.field_diff.map((diff, index) => <li key={`${diff.path}-${index}`}><strong>{diff.path ?? 'Поле'}</strong><div><span>До</span><pre>{json(diff.before)}</pre></div><div><span>После</span><pre>{json(diff.after)}</pre></div></li>)}</ul> : <p>Сравнение с опубликованной версией не предоставлено API.</p>}{detail.checklist.length > 0 && <ul className="checklist">{detail.checklist.map((item, index) => <li key={`${item.code}-${index}`}><span className={item.passed ? 'check-pass' : 'check-fail'}>{item.passed ? 'ПРОЙДЕНО' : item.passed === false ? 'НЕ ПРОЙДЕНО' : 'БЕЗ СТАТУСА'}</span><strong>{item.code ?? 'Проверка'}</strong><span>{item.message ?? 'Сообщение отсутствует'}</span></li>)}</ul>}</section>
          {detail.history && <section className="admin-panel"><h2>История заявки</h2><ul className="history-list">{detail.history.map((item, index) => <li key={`${item.action}-${index}`}><strong>{item.action ?? 'Событие'}</strong><span>{formatTime(item.occurred_at)} · {item.actor_id ?? 'системное событие'}</span></li>)}</ul></section>}
        </article>
        <aside className="decision-column"><section className="admin-panel decision-panel"><p className="eyebrow">ОБРАБОТКА ЗАЯВКИ</p><h2>Решение</h2>{lease ? <form onSubmit={submitDecision}>
          <label>Действие<select value={action} onChange={(event) => setAction(event.target.value as typeof action)}><option value="CHANGES_REQUESTED">Запросить изменения</option><option value="REJECT">Отклонить</option><option value="ESCALATE">Эскалировать</option><option value="APPROVE">Одобрить</option></select></label>
          {action !== 'APPROVE' ? <fieldset><legend>Причины</legend>{reasons.length ? reasons.map((reason) => <label className="reason-option" key={reason.id}><input type="checkbox" checked={selectedReasons.includes(reason.code)} onChange={(event) => setSelectedReasons((current) => event.target.checked ? [...current, reason.code] : current.filter((code) => code !== reason.code))}/><span><strong>{reason.title}</strong><small>{reason.code} · {reason.severity}</small></span></label>) : <p className="form-hint">Активные причины не загружены. Проверьте доступ к списку причин.</p>}</fieldset> : <label>Пройденные правила <input value={passedRules} onChange={(event) => setPassedRules(event.target.value)} placeholder="Например: PRODUCT_TITLE_VALID"/><small>Введите коды через запятую. Нужен минимум один код.</small></label>}
          <label>Комментарий <textarea rows={5} maxLength={3000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Комментарий к решению"/></label>
          <p className="form-hint">Решение будет связано с ревизией {detail.snapshot.revision}, хешем снимка и политикой v{detail.snapshot.policy_version}. Ответ API 202 означает, что решение принято в обработку.</p>
          <button className="admin-button admin-button-primary decision-submit" disabled={busy || (action === 'APPROVE' ? !passedRules.trim() : !selectedReasons.length)}>{busy ? 'Отправка…' : 'Отправить решение'}</button>
          <p className="step-up-note">HARD_BLOCK скрыт: MFA step-up claims в Keycloak пока не настроены.</p>
        </form> : <p className="form-hint">Чтобы отправить решение, сначала закрепите заявку за собой. Сервер повторно проверит права, MFA и актуальность версии.</p>}</section></aside>
      </div>
    </>}
  </AdminShell>;
}
