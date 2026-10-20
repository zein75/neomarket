'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type AuditEvent = { id: string; action: string; actor_id?: string | null; entity_type: string; entity_id: string; created_at: string; request_id?: string | null; redacted_details?: Record<string, unknown> | null };
type AuditPage = { items: AuditEvent[]; page: { has_more: boolean; next_cursor: string | null } };
type Operation = { operation_id: string; status: string; resource_id?: string | null; request_id?: string };

async function apiError(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  if (typeof body?.code === 'string') return `${body.code} (${response.status})`;
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.detail === 'string') return body.detail;
  return `Запрос не выполнен (${response.status})`;
}
function time(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : `${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC' }).format(date)} UTC`;
}
function hex(bytes: ArrayBuffer) { return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join(''); }

export function AuditEvents() {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const cursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [reasonCode, setReasonCode] = useState('');
  const [exporting, setExporting] = useState(false);
  const exportRetry = useRef<{ key: string; body: object; signature: string; resourceId?: string } | null>(null);

  const load = useCallback(async (append = false) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '30' });
    if (append && cursorRef.current) query.set('cursor', cursorRef.current);
    try {
      const response = await fetch(`/api/admin/v1/audit-events?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiError(response));
      const page = await response.json() as AuditPage;
      setItems((current) => append ? [...current, ...page.items] : page.items);
      cursorRef.current = page.page.next_cursor; setCursor(page.page.next_cursor); setHasMore(page.page.has_more);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить audit log');
      if (!append) { setItems([]); cursorRef.current = null; setCursor(null); setHasMore(false); }
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(false); }, [load]);

  const createExport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setNotice('');
    if (!startAt || !endAt || !/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode.trim())) { setError('Укажите временной диапазон в UTC и reason code из внутренней политики.'); return; }
    const body = { start_at: new Date(`${startAt}:00Z`).toISOString(), end_at: new Date(`${endAt}:00Z`).toISOString(), reason_code: reasonCode.trim().toUpperCase() };
    if (Date.parse(body.end_at) <= Date.parse(body.start_at)) { setError('Конец диапазона должен быть позже начала.'); return; }
    const signature = JSON.stringify(body);
    if (exportRetry.current && exportRetry.current.signature !== signature) { setError('Предыдущий запрос экспорта не подтверждён. Повторите его с теми же полями.'); return; }
    if (!exportRetry.current) exportRetry.current = { key: crypto.randomUUID(), body, signature };
    setExporting(true);
    try {
      let operation: Operation | null = null;
      if (!exportRetry.current.resourceId) {
        const response = await fetch('/api/admin/v1/audit-events/export', { method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': exportRetry.current.key }, body: JSON.stringify(exportRetry.current.body) });
        if (!response.ok) { exportRetry.current = null; throw new Error(await apiError(response)); }
        operation = await response.json() as Operation;
        if (!operation.resource_id) throw new Error(`Операция ${operation.operation_id} принята со статусом ${operation.status}, но export resource_id отсутствует.`);
        exportRetry.current.resourceId = operation.resource_id;
      }
      const exportId = exportRetry.current.resourceId;
      const fileResponse = await fetch(`/api/admin/v1/audit-events/exports/${encodeURIComponent(exportId)}`, { cache: 'no-store', headers: { Accept: 'application/zip' } });
      if (!fileResponse.ok) throw new Error(await apiError(fileResponse));
      const expectedDigest = fileResponse.headers.get('x-content-sha256')?.toLowerCase();
      if (!expectedDigest || !/^[a-f0-9]{64}$/.test(expectedDigest)) throw new Error('Export download не содержит SHA-256 заголовок; файл не сохранён.');
      const blob = await fileResponse.blob();
      const actualDigest = hex(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()));
      if (actualDigest !== expectedDigest) throw new Error('SHA-256 export не совпадает с integrity header; файл не сохранён.');
      const disposition = fileResponse.headers.get('content-disposition') ?? '';
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? `neomarket-audit-${exportId}.zip`;
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = filename; anchor.click(); URL.revokeObjectURL(objectUrl);
      const operationId = operation?.operation_id ?? 'повторная загрузка';
      const operationStatus = operation?.status ?? 'повторная загрузка';
      exportRetry.current = null;
      setNotice(`Audit export сохранён после проверки SHA-256 · ${expectedDigest} · operation ${operationId} (${operationStatus}). Details редактированы в архиве.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Экспорт не подтверждён; повторяйте только с тем же диапазоном и reason code.'); }
    finally { setExporting(false); }
  };

  return <AdminShell section="/audit">
    <p className="eyebrow">ADMIN CONSOLE / SECURITY / AUDIT</p>
    <div className="admin-heading-row"><div><h1>Журнал аудита</h1><p className="admin-intro">Append-only события и защищённый export. В таблице показаны только метаданные; приватные детали не загружаются.</p></div><button className="admin-button" onClick={() => void load(false)} disabled={loading}>Обновить</button></div>
    {error && <div className="admin-alert" role="alert"><strong>Audit действие не подтверждено</strong><span>{error}</span><p>Экспорт проверяется по SHA-256 до сохранения файла.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    <details className="admin-panel audit-export-panel"><summary>Заказать проверяемый audit export</summary><form onSubmit={createExport}>
      <label>Начало диапазона (UTC)<input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} required disabled={exporting || Boolean(exportRetry.current)}/></label>
      <label>Конец диапазона (UTC)<input type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} required disabled={exporting || Boolean(exportRetry.current)}/></label>
      <label>Reason code<input value={reasonCode} onChange={(event) => setReasonCode(event.target.value.toUpperCase())} maxLength={64} placeholder="КОД_ИЗ_ПОЛИТИКИ" required disabled={exporting || Boolean(exportRetry.current)}/></label>
      <p className="form-hint">Архив содержит CSV метаданных и chain hashes; поле details редактировано. Размер ограничен сервером 25 000 событий. Artefact временный и доступен только создавшему его сотруднику.</p>
      <button className="admin-button admin-button-primary" disabled={exporting || !startAt || !endAt || !reasonCode.trim()}>{exporting ? 'Проверка и скачивание…' : exportRetry.current ? 'Повторить тот же запрос' : 'Создать и проверить export'}</button>
    </form></details>
    <div className="queue-toolbar"><span className="queue-count">{loading ? 'Загрузка…' : error ? 'Данные не получены' : `${items.length} событий загружено`}</span></div>
    {loading && <div className="admin-empty" role="status">Загрузка событий аудита…</div>}
    {!error && !loading && items.length === 0 && <div className="admin-empty"><h2>Событий нет</h2><p>Audit API не вернул записи.</p></div>}
    {items.length > 0 && <div className="admin-table-wrap"><table className="admin-table audit-table"><thead><tr><th>UTC время</th><th>Действие</th><th>Actor</th><th>Entity</th><th>Request ID</th><th>Event ID</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{time(item.created_at)}</td><td><strong>{item.action}</strong></td><td>{item.actor_id ?? 'system'}</td><td>{item.entity_type}<small>{item.entity_id}</small></td><td><code>{item.request_id ?? '—'}</code></td><td><code>{item.id}</code></td></tr>)}</tbody></table></div>}
    {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void load(true)} disabled={loading}>{loading ? 'Загрузка…' : 'Загрузить ещё'}</button></div>}
    <p className="form-hint audit-note">Raw audit details and chain verification are not exposed by the current list contract. The export embeds the immutable chain hashes and is logged on download.</p>
  </AdminShell>;
}
