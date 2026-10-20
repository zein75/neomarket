'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type ReviewOperation = {
  operation_id: string;
  request_id: string;
  action: string;
  status: string;
  entity_type: string;
  resource_id: string;
  requested_by_staff_id: string;
  approved_by_staff_id: string | null;
  cancelled_by_staff_id: string | null;
  reason_code: string;
  created_at: string;
  updated_at: string;
  summary: Record<string, string | number | boolean | string[]>;
  approval_supported: boolean;
};
type OperationPage = { items: ReviewOperation[]; page: { has_more: boolean; next_cursor: string | null } };
type Principal = { staff_id: string; permissions: string[] };
type OperationDetail = { operation: ReviewOperation; etag: string };
type PendingKey = { key: string; signature: string };

const approvalPermission: Record<string, string> = {
  STAFF_PERMISSION_GRANT: 'iam.grant', STAFF_PERMISSION_REVOKE: 'iam.revoke', STAFF_SESSION_REVOKE: 'iam.revoke',
  BLOCKING_REASON_CREATE: 'policy.reason.write', BLOCKING_REASON_UPDATE: 'policy.reason.write', BLOCKING_REASON_ARCHIVE: 'policy.reason.write',
  POLICY_CREATE: 'policy.write', POLICY_PUBLISH: 'policy.publish', OUTBOX_RETRY: 'operations.events.retry',
  APPEAL_DECISION: 'appeal.decide', COMPLAINT_ACTION: 'complaint.decide', SELLER_RESTRICTION: 'seller.restrict',
  PRODUCT_SAFETY_HOLD: 'products.safety_hold', CATEGORY_CREATE: 'taxonomy.category.publish', CATEGORY_UPDATE: 'taxonomy.category.publish',
  CATEGORY_PUBLISH: 'taxonomy.category.publish', CATEGORY_MOVE: 'taxonomy.category.publish', CATEGORY_ARCHIVE: 'taxonomy.category.publish',
  ATTRIBUTE_RULES_PUBLISH: 'taxonomy.attribute.publish', ATTRIBUTE_CREATE: 'taxonomy.attribute.publish', ATTRIBUTE_UPDATE: 'taxonomy.attribute.publish',
  BRAND_MERGE: 'taxonomy.brand.publish',
};

async function apiError(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  const detail = body?.detail;
  if (typeof body?.code === 'string') return `${body.code}: ${typeof body.message === 'string' ? body.message : ''}`;
  if (typeof detail === 'object' && detail && 'code' in detail) {
    const code = typeof detail.code === 'string' ? detail.code : '';
    const message = 'message' in detail && typeof detail.message === 'string' ? detail.message : '';
    return `${code}${code && message ? ': ' : ''}${message}` || `HTTP ${response.status}`;
  }
  return typeof detail === 'string' ? detail : `HTTP ${response.status}`;
}

function time(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function actionLabel(value: string) {
  return value.toLowerCase().replaceAll('_', ' ');
}

export function OperationsReview() {
  const [items, setItems] = useState<ReviewOperation[]>([]);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [stepUpRequired, setStepUpRequired] = useState(false);
  const [notice, setNotice] = useState('');
  const [details, setDetails] = useState<Record<string, OperationDetail>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const keys = useRef(new Map<string, PendingKey>());

  const load = useCallback(async (append = false) => {
    setLoading(true); setError(''); setNotice(''); setStepUpRequired(false);
    const query = new URLSearchParams({ limit: '50' });
    if (append && cursor) query.set('cursor', cursor);
    try {
      const response = await fetch(`/api/admin/v1/operations?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiError(response));
      const page = await response.json() as OperationPage;
      setItems((current) => append ? [...current, ...page.items] : page.items);
      setCursor(page.page.next_cursor); setHasMore(page.page.has_more);
      if (!append) setDetails({});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить операции');
      if (!append) { setItems([]); setCursor(null); setHasMore(false); setDetails({}); }
    } finally { setLoading(false); }
  }, [cursor]);

  useEffect(() => {
    void load(false);
    void fetch('/api/admin/v1/me', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(async (response) => { if (response.ok) setPrincipal(await response.json() as Principal); })
      .catch(() => {});
  }, []);

  const inspect = async (operationId: string) => {
    if (details[operationId]) return;
    setBusyId(operationId); setError('');
    try {
      const response = await fetch(`/api/admin/v1/operations/${encodeURIComponent(operationId)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiError(response));
      const operation = await response.json() as ReviewOperation;
      const etag = response.headers.get('ETag');
      if (!etag) throw new Error('API did not return an operation version (ETag); review is unavailable.');
      setDetails((current) => ({ ...current, [operationId]: { operation, etag } }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось загрузить операцию'); }
    finally { setBusyId(''); }
  };

  const decide = async (operation: ReviewOperation, etag: string, decision: 'approve' | 'cancel') => {
    const id = operation.operation_id;
    if (decision === 'approve' && (!operation.approval_supported || operation.status !== 'WAITING_APPROVAL' || operation.requested_by_staff_id === principal?.staff_id)) return;
    if (decision === 'cancel' && operation.status !== 'WAITING_APPROVAL') return;
    const body = { reason_code: operation.reason_code, comment: comments[id]?.trim() || null };
    const keyId = `${decision}:${id}`;
    const signature = JSON.stringify({ body, etag });
    let pending = keys.current.get(keyId);
    if (pending && pending.signature !== signature) { setError('Предыдущий запрос не подтверждён. Сначала повторите его с теми же данными или обновите операцию.'); return; }
    if (!pending) { pending = { key: crypto.randomUUID(), signature }; keys.current.set(keyId, pending); }
    setBusyId(id); setError(''); setNotice(''); setStepUpRequired(false);
    try {
      const response = await fetch(`/api/admin/v1/operations/${encodeURIComponent(id)}/${decision}`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key, 'If-Match': etag },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const message = await apiError(response);
        if (response.status < 500) keys.current.delete(keyId);
        if (message.includes('STEP_UP_REQUIRED')) setStepUpRequired(true);
        throw new Error(message);
      }
      keys.current.delete(keyId);
      const result = await response.json() as { status?: string };
      await load(false);
      setNotice(`Решение ${decision === 'approve' ? 'одобрено' : 'отменено'}: ${result.status ?? 'статус ожидает подтверждения'}.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Результат решения не подтверждён'); }
    finally { setBusyId(''); }
  };

  const permissionSet = new Set(principal?.permissions ?? []);
  return <AdminShell section="/operations"><p className="eyebrow">ADMIN CONSOLE / OPERATIONS / MAKER-CHECKER</p>
    <div className="admin-heading-row"><div><h1>Очередь согласований</h1><p className="admin-intro">Операции загружаются из Admin API. До одобрения показываются только разрешённые для проверки поля; произвольные payload и комментарии скрыты.</p></div><button className="admin-button" onClick={() => void load(false)} disabled={loading}>Обновить</button></div>
    <div className="queue-toolbar"><span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} операций загружено`}</span><span className="privacy-note">Decision требует серверной проверки permissions, step-up и maker-checker.</span></div>
    {error && <div className="admin-alert" role="alert"><strong>Очередь недоступна</strong><span>{error}</span></div>}
    {stepUpRequired && <div className="admin-notice" role="status"><a href="/api/auth/step-up?returnTo=%2Foperations">Повторно подтвердить MFA для step-up</a>, затем откройте операцию и повторите решение.</div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Ожидающих операций нет</h2><p>API не вернул owned, reviewable или недавно рассмотренные операции.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Операция</th><th>Действие</th><th>Ресурс</th><th>Статус</th><th>Причина</th><th>Создано</th><th>Review</th></tr></thead><tbody>{items.map((item) => {
      const detail = details[item.operation_id];
      const operation = detail?.operation ?? item;
      const requiredPermission = approvalPermission[operation.action];
      const canApprove = Boolean(principal && requiredPermission && (permissionSet.has('*') || permissionSet.has(requiredPermission)) && operation.approval_supported && operation.action !== 'APPEAL_DECISION' && operation.status === 'WAITING_APPROVAL' && operation.requested_by_staff_id !== principal.staff_id);
      const canCancel = Boolean(principal && (permissionSet.has('*') || permissionSet.has('operations.cancel')) && operation.status === 'WAITING_APPROVAL');
      return <tr key={item.operation_id}><th scope="row"><code>{item.operation_id}</code><small>maker {item.requested_by_staff_id}</small></th><td>{actionLabel(item.action)}</td><td>{item.entity_type} · <code>{item.resource_id}</code></td><td><span className={`state-pill state-${item.status.toLowerCase()}`}>{item.status}</span></td><td>{item.reason_code}</td><td>{time(item.created_at)}</td><td><div className="retry-cell"><button className="admin-button" onClick={() => void inspect(item.operation_id)} disabled={busyId === item.operation_id}>{detail ? 'Обновить' : 'Открыть'}</button>{detail && <div className="admin-operation-review"><dl className="taxonomy-details"><div><dt>Последнее изменение</dt><dd>{time(operation.updated_at)}</dd></div><div><dt>Request ID</dt><dd><code>{operation.request_id}</code></dd></div>{Object.entries(operation.summary).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{Array.isArray(value) ? value.join('\n') : String(value)}</dd></div>)}</dl>{!operation.approval_supported && operation.status === 'WAITING_APPROVAL' && <p className="form-hint">Безопасного review summary недостаточно; одобрение отключено до полного отображения деталей.</p>}{operation.action === 'APPEAL_DECISION' && <p className="form-hint">Решение заблокировано, пока не настроена доставка уведомлений.</p>}{operation.status === 'WAITING_APPROVAL' && <label>Комментарий к решению (необязательно)<textarea value={comments[item.operation_id] ?? ''} maxLength={3000} onChange={(event) => setComments((current) => ({ ...current, [item.operation_id]: event.target.value }))}/></label>}{operation.status === 'WAITING_APPROVAL' && <div className="admin-heading-row"><button className="admin-button admin-button-primary" disabled={busyId === item.operation_id || !canApprove} onClick={() => void decide(operation, detail.etag, 'approve')}>Одобрить</button><button className="admin-button" disabled={busyId === item.operation_id || !canCancel} onClick={() => void decide(operation, detail.etag, 'cancel')}>Отменить операцию</button></div>}{!canApprove && operation.status === 'WAITING_APPROVAL' && operation.action !== 'APPEAL_DECISION' && <p className="form-hint">Для одобрения нужны отдельное разрешение approver и сотрудник, отличный от автора.</p>}</div>}</div></td></tr>;
    })}</tbody></table></div>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>Загрузить ещё</button></div>}
  </AdminShell>;
}
