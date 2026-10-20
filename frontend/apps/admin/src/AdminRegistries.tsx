'use client';
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type Row = Record<string, unknown>;
type Column = { key: string; label: string; render?: (row: Row) => string };
type Config = { section: string; title: string; intro: string; endpoint: string; columns: Column[]; idKey: string; detailBase?: string; serverSearch?: boolean; unavailable: string };
type Page = { items: Row[]; page: { has_more: boolean; next_cursor: string | null } };
type RestrictionAction = 'RESTRICT' | 'SUSPEND' | 'REINSTATE';
type PendingRestriction = { key: string; signature: string };
type PendingProductAction = { key: string; signature: string };
const configs: Record<string, Config> = {
  products: { section: '/products', title: 'Products', intro: 'Search products and inspect publication state from the Admin B2B API.', endpoint: '/api/admin/v1/products', idKey: 'id', detailBase: '/products', serverSearch: true, columns: [
    { key: 'id', label: 'Product ID' }, { key: 'seller_id', label: 'Seller ID' },
    { key: 'visible', label: 'Visible', render: (r) => r.visible === true ? 'Yes' : r.visible === false ? 'No' : 'Not provided' },
    { key: 'current_revision', label: 'Current revision' }, { key: 'published_revision', label: 'Published revision' },
    { key: 'visibility_reasons', label: 'Visibility reasons', render: (r) => Array.isArray(r.visibility_reasons) ? r.visibility_reasons.join(', ') || 'None' : 'Not provided' },
  ], unavailable: 'Product registry unavailable from the Admin B2B API.' },
  sellers: { section: '/sellers', title: 'Sellers', intro: 'Seller review queue and restriction status.', endpoint: '/api/admin/v1/sellers', idKey: 'seller_id', detailBase: '/sellers', columns: [
    { key: 'seller_id', label: 'Seller ID' }, { key: 'status', label: 'Status' }, { key: 'reason_code', label: 'Reason' }, { key: 'version', label: 'Version' },
    { key: 'updated_at', label: 'Updated', render: (r) => typeof r.updated_at === 'string' ? new Date(r.updated_at).toLocaleString() : 'Not provided' },
  ], unavailable: 'Seller registry unavailable from the B2B API.' },
  brands: { section: '/taxonomy/brands', title: 'Brands', intro: 'Brand registry, aliases, and safe catalog reference merging.', endpoint: '/api/admin/v1/taxonomy/brands', idKey: 'id', columns: [
    { key: 'name', label: 'Brand' }, { key: 'aliases', label: 'Aliases', render: (r) => Array.isArray(r.aliases) ? r.aliases.join(', ') : 'Not provided' }, { key: 'status', label: 'Status' }, { key: 'version', label: 'Version' },
  ], unavailable: 'Brand registry unavailable from the verified B2B taxonomy API.' },
};
async function errorText(response: Response) {
  const data = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: { code?: unknown; message?: unknown } | string } | null;
  const detail = data?.detail;
  const code = typeof data?.code === 'string' ? data.code : typeof detail === 'object' && typeof detail.code === 'string' ? detail.code : '';
  const message = typeof data?.message === 'string' ? data.message : typeof detail === 'object' && typeof detail.message === 'string' ? detail.message : typeof detail === 'string' ? detail : '';
  return [code, message, `HTTP ${response.status}`].filter(Boolean).join(' ? ');
}
function display(value: unknown) {
  if (value == null || value === '') return '?';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value) && value.every((v) => ['string', 'number'].includes(typeof v))) return value.join(', ') || '?';
  return 'Value is available from the API but is not displayed here';
}
export function AdminRegistry({ kind, recordId }: { kind: 'products' | 'sellers' | 'brands'; recordId?: string }) {
  const config = configs[kind]!;
  const [items, setItems] = useState<Row[]>([]); const [record, setRecord] = useState<Row | null>(null);
  const [cursor, setCursor] = useState<string | null>(null); const cursorRef = useRef<string | null>(null);
  const [hasMore, setHasMore] = useState(false); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [query, setQuery] = useState('');
  const [sellerHistory, setSellerHistory] = useState<Row[]>([]); const [sellerHistoryError, setSellerHistoryError] = useState('');
  const [restrictionAction, setRestrictionAction] = useState<RestrictionAction>('SUSPEND');
  const [restrictionReason, setRestrictionReason] = useState(''); const [restrictionComment, setRestrictionComment] = useState('');
  const [restrictionExpiry, setRestrictionExpiry] = useState(''); const [restrictionBusy, setRestrictionBusy] = useState(false); const [restrictionMessage, setRestrictionMessage] = useState('');
  const pendingRestriction = useRef<PendingRestriction | null>(null);
  const [recheckReason, setRecheckReason] = useState(''); const [recheckComment, setRecheckComment] = useState('');
  const [holdReason, setHoldReason] = useState(''); const [holdComment, setHoldComment] = useState('');
  const [holdExpiry, setHoldExpiry] = useState(''); const [productBusy, setProductBusy] = useState(false); const [productMessage, setProductMessage] = useState('');
  const pendingRecheck = useRef<PendingProductAction | null>(null); const pendingSafetyHold = useRef<PendingProductAction | null>(null);
  const loadList = useCallback(async (append = false) => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (append && cursorRef.current) params.set('cursor', cursorRef.current);
      if (config.serverSearch && query.trim()) params.set('search', query.trim());
      const response = await fetch(`${config.endpoint}?${params}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await errorText(response));
      const data = await response.json() as Page;
      if (!Array.isArray(data.items) || !data.page) throw new Error('API response does not match the list contract.');
      setItems((current) => append ? [...current, ...data.items] : data.items);
      cursorRef.current = data.page.next_cursor; setCursor(data.page.next_cursor); setHasMore(data.page.has_more);
    } catch (caught) { setItems([]); setError(caught instanceof Error ? caught.message : config.unavailable); }
    finally { setLoading(false); }
  }, [config, query]);
  const loadRecord = useCallback(async () => {
    if (!recordId || kind === 'brands') return;
    setLoading(true); setError('');
    try {
      const response = await fetch(`${config.endpoint}/${encodeURIComponent(recordId)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await errorText(response));
      setRecord(await response.json() as Row);
    } catch (caught) { setRecord(null); setError(caught instanceof Error ? caught.message : config.unavailable); }
    finally { setLoading(false); }
  }, [config, kind, recordId]);
  const loadSellerHistory = useCallback(async () => {
    if (kind !== 'sellers' || !recordId) return;
    setSellerHistoryError('');
    try {
      const response = await fetch(`${config.endpoint}/${encodeURIComponent(recordId)}/history?limit=50`, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await errorText(response));
      const data = await response.json() as { items?: Row[] };
      if (!Array.isArray(data.items)) throw new Error('Seller history response does not match the API contract.');
      setSellerHistory(data.items);
    } catch (caught) { setSellerHistory([]); setSellerHistoryError(caught instanceof Error ? caught.message : 'Seller history unavailable.'); }
  }, [config, kind, recordId]);
  const proposeRestriction = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (kind !== 'sellers' || !recordId || !record) return;
    const sellerId = typeof record.seller_id === 'string' ? record.seller_id : recordId;
    const version = typeof record.version === 'number' ? record.version : Number(record.version);
    const reasonCode = restrictionReason.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode)) { setRestrictionMessage('Reason code is required: A-Z, 0-9 and _.'); return; }
    if (restrictionAction === 'SUSPEND' && !restrictionExpiry) { setRestrictionMessage('Suspension expiry is required.'); return; }
    if (!Number.isInteger(version) || version < 1) { setRestrictionMessage('Seller version is unavailable; reload the record before proposing a restriction.'); return; }
    let effectiveUntil: string | null = null;
    if (restrictionExpiry) {
      const parsed = new Date(restrictionExpiry);
      if (Number.isNaN(parsed.getTime())) { setRestrictionMessage('Suspension expiry is invalid.'); return; }
      effectiveUntil = parsed.toISOString();
    }
    const body = { action: restrictionAction, reason_code: reasonCode, comment: restrictionComment.trim() || null, effective_until: effectiveUntil };
    const signature = JSON.stringify({ sellerId, version, body });
    if (pendingRestriction.current && pendingRestriction.current.signature !== signature) { setRestrictionMessage('The previous request is unresolved. Retry with the same fields or inspect the operation queue.'); return; }
    const pending = pendingRestriction.current ?? { key: crypto.randomUUID(), signature };
    pendingRestriction.current = pending;
    setRestrictionBusy(true); setRestrictionMessage('');
    try {
      const response = await fetch(`/api/admin/v1/sellers/${encodeURIComponent(sellerId)}/restrictions`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key, 'If-Match': `v${version}` }, body: JSON.stringify(body),
      });
      if (!response.ok) { if (response.status < 500) pendingRestriction.current = null; throw new Error(await errorText(response)); }
      const result = await response.json() as { operation_id?: string; status?: string };
      pendingRestriction.current = null;
      setRestrictionMessage(`Proposal created: ${result.status ?? 'status pending'}${result.operation_id ? ` · ${result.operation_id}` : ''}. Independent approval is required; the seller state remains unchanged until B2B confirms the command.`);
      setRestrictionComment(''); setRestrictionReason(''); setRestrictionExpiry('');
    } catch (caught) { setRestrictionMessage(caught instanceof Error ? caught.message : 'The proposal was not confirmed. Retry with the same fields.'); }
    finally { setRestrictionBusy(false); }
  };
  const requestProductRecheck = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (kind !== 'products' || !recordId || !record) return;
    const productId = typeof record.id === 'string' ? record.id : recordId;
    const reasonCode = recheckReason.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode)) { setProductMessage('Reason code is required: A-Z, 0-9 and _.'); return; }
    const body = { reason_code: reasonCode, comment: recheckComment.trim() || null };
    const signature = JSON.stringify({ productId, body });
    if (pendingRecheck.current && pendingRecheck.current.signature !== signature) { setProductMessage('The previous recheck is unresolved. Retry with the same fields or inspect the operation queue.'); return; }
    const pending = pendingRecheck.current ?? { key: crypto.randomUUID(), signature };
    pendingRecheck.current = pending; setProductBusy(true); setProductMessage('');
    try {
      const response = await fetch(`/api/admin/v1/products/${encodeURIComponent(productId)}/recheck`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key }, body: JSON.stringify(body),
      });
      if (!response.ok) { if (response.status < 500) pendingRecheck.current = null; throw new Error(await errorText(response)); }
      const result = await response.json() as { operation_id?: string; status?: string };
      pendingRecheck.current = null;
      setProductMessage(`Recheck created: ${result.status ?? 'status pending'}${result.operation_id ? ` · ${result.operation_id}` : ''}. The product remains unchanged until the review result is confirmed.`);
      setRecheckReason(''); setRecheckComment('');
    } catch (caught) { setProductMessage(caught instanceof Error ? caught.message : 'The recheck was not confirmed. Retry with the same fields.'); }
    finally { setProductBusy(false); }
  };
  const requestSafetyHold = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (kind !== 'products' || !recordId || !record) return;
    const productId = typeof record.id === 'string' ? record.id : recordId;
    const revision = typeof record.current_revision === 'number' ? record.current_revision : Number(record.current_revision);
    const reasonCode = holdReason.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(reasonCode)) { setProductMessage('Reason code is required: A-Z, 0-9 and _.'); return; }
    if (!Number.isInteger(revision) || revision < 1) { setProductMessage('Current product revision is unavailable; reload before requesting a safety hold.'); return; }
    if (!holdExpiry) { setProductMessage('Safety hold expiry is required.'); return; }
    const parsedExpiry = new Date(holdExpiry);
    if (Number.isNaN(parsedExpiry.getTime()) || parsedExpiry.getTime() <= Date.now()) { setProductMessage('Safety hold expiry must be in the future.'); return; }
    const body = { reason_code: reasonCode, expires_at: parsedExpiry.toISOString(), comment: holdComment.trim() || null };
    const signature = JSON.stringify({ productId, revision, body });
    if (pendingSafetyHold.current && pendingSafetyHold.current.signature !== signature) { setProductMessage('The previous safety hold is unresolved. Retry with the same fields or inspect the operation queue.'); return; }
    const pending = pendingSafetyHold.current ?? { key: crypto.randomUUID(), signature };
    pendingSafetyHold.current = pending; setProductBusy(true); setProductMessage('');
    try {
      const response = await fetch(`/api/admin/v1/products/${encodeURIComponent(productId)}/safety-hold`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key, 'If-Match': `v${revision}` }, body: JSON.stringify(body),
      });
      if (!response.ok) { if (response.status < 500) pendingSafetyHold.current = null; throw new Error(await errorText(response)); }
      const result = await response.json() as { operation_id?: string; status?: string };
      pendingSafetyHold.current = null;
      setProductMessage(`Safety hold proposal created: ${result.status ?? 'status pending'}${result.operation_id ? ` · ${result.operation_id}` : ''}. Visibility changes only after B2B confirms the command.`);
      setHoldReason(''); setHoldComment(''); setHoldExpiry('');
    } catch (caught) { setProductMessage(caught instanceof Error ? caught.message : 'The safety hold was not confirmed. Retry with the same fields.'); }
    finally { setProductBusy(false); }
  };
  useEffect(() => {
    const timer = setTimeout(() => { if (recordId && kind !== 'brands') { void loadRecord(); if (kind === 'sellers') void loadSellerHistory(); } else void loadList(); }, config.serverSearch ? 250 : 0);
    return () => clearTimeout(timer);
  }, [kind, recordId, loadList, loadRecord, loadSellerHistory, config.serverSearch]);
  const visible = useMemo(() => config.serverSearch ? items : items.filter((row) => config.columns.map((c) => c.render ? c.render(row) : display(row[c.key])).join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())), [items, query, config]);
  return <AdminShell section={config.section}>
    {recordId && kind !== 'brands' && <a className="back-link" href={config.section}>? Back to list</a>}
    <p className="eyebrow">ADMIN CONSOLE / {config.section.replace(/^\//, '').toUpperCase()}</p>
    <div className="admin-heading-row"><div><h1>{recordId ? `${config.title}: record` : config.title}</h1><p className="admin-intro">{config.intro}</p></div><button className="admin-button" onClick={() => recordId ? void loadRecord() : void loadList(false)} disabled={loading}>Refresh</button></div>
    {error && <div className="admin-alert" role="alert"><strong>Data unavailable</strong><span>{error}</span><p>{config.unavailable} Check integrations in <a href="/settings">settings</a>.</p></div>}
    {loading && <div className="admin-empty" role="status"><h2>Loading from Admin API...</h2></div>}
    {record && <div className="admin-panel registry-detail"><p className="eyebrow">API RECORD ? READ ONLY</p><dl className="taxonomy-details">{config.columns.map((c) => <div key={c.key}><dt>{c.label}</dt><dd>{c.render ? c.render(record) : display(record[c.key])}</dd></div>)}</dl><p className="form-hint">Revision history, open complaints, and actions use verified API contracts.</p></div>}
    {record && kind === 'products' && <section className="admin-panel" aria-labelledby="product-actions-title">
      <p className="eyebrow">PRODUCT SAFETY / VERSION-BOUND ACTIONS</p><h2 id="product-actions-title">Review and safety actions</h2>
      <p className="admin-intro">Each action is reasoned and idempotent. The current revision is checked by the server; this screen never changes publication state optimistically.</p>
      <div className="admin-form-grid">
        <form className="admin-form" onSubmit={(event) => void requestProductRecheck(event)}>
          <h3>Start a new review</h3>
          <label>Reason code<input value={recheckReason} onChange={(event) => setRecheckReason(event.target.value.toUpperCase())} maxLength={64} pattern="[A-Z][A-Z0-9_]*" required disabled={productBusy} placeholder="RECHECK_REQUESTED" /></label>
          <label>Comment (optional)<textarea value={recheckComment} onChange={(event) => setRecheckComment(event.target.value)} maxLength={3000} disabled={productBusy} /></label>
          <button className="admin-button admin-button-primary" type="submit" disabled={productBusy}>{productBusy ? 'Submitting…' : 'Request recheck'}</button>
        </form>
        <form className="admin-form" onSubmit={(event) => void requestSafetyHold(event)}>
          <h3>Request a safety hold</h3>
          <label>Reason code<input value={holdReason} onChange={(event) => setHoldReason(event.target.value.toUpperCase())} maxLength={64} pattern="[A-Z][A-Z0-9_]*" required disabled={productBusy} placeholder="SAFETY_REVIEW" /></label>
          <label>Expires at (required)<input type="datetime-local" value={holdExpiry} onChange={(event) => setHoldExpiry(event.target.value)} required disabled={productBusy} /></label>
          <label>Comment (optional)<textarea value={holdComment} onChange={(event) => setHoldComment(event.target.value)} maxLength={3000} disabled={productBusy} /></label>
          <button className="admin-button admin-button-primary" type="submit" disabled={productBusy}>{productBusy ? 'Submitting…' : 'Create safety-hold proposal'}</button>
        </form>
      </div>
      {productMessage && <p className="form-hint" role="status">{productMessage} <a href="/operations">Review operations</a>.</p>}
    </section>}
    {record && kind === 'sellers' && <section className="admin-panel" aria-labelledby="seller-history-title">
      <p className="eyebrow">SELLER CASE TIMELINE</p><h2 id="seller-history-title">History</h2>
      {sellerHistoryError && <p className="form-hint" role="alert">{sellerHistoryError}</p>}
      {!sellerHistoryError && (sellerHistory.length ? <ol className="history-list">{sellerHistory.map((event, index) => <li key={String(event.id ?? index)}><strong>{display(event.action)}</strong><span>{typeof event.created_at === 'string' ? new Date(event.created_at).toLocaleString() : 'Timestamp unavailable'}</span>{typeof event.request_id === 'string' && <code>{event.request_id}</code>}</li>)}</ol> : <p className="form-hint">No seller history events were returned.</p>)}
    </section>}
    {record && kind === 'sellers' && <section className="admin-panel" aria-labelledby="seller-restriction-title">
      <p className="eyebrow">SELLER COMPLIANCE / MAKER-CHECKER</p><h2 id="seller-restriction-title">Propose a seller restriction</h2>
      <p className="admin-intro">This creates a reasoned proposal. A different authorized reviewer must approve it, then B2B applies the version-bound command. Open orders are not cancelled by this form.</p>
      <form className="admin-form" onSubmit={(event) => void proposeRestriction(event)}>
        <label>Action<select value={restrictionAction} onChange={(event) => setRestrictionAction(event.target.value as RestrictionAction)} disabled={restrictionBusy}><option value="SUSPEND">Suspend</option><option value="RESTRICT">Restrict new listings</option><option value="REINSTATE">Reinstate</option></select></label>
        <label>Reason code<input value={restrictionReason} onChange={(event) => setRestrictionReason(event.target.value.toUpperCase())} maxLength={64} pattern="[A-Z][A-Z0-9_]*" required disabled={restrictionBusy} placeholder="COMPLIANCE_REVIEW" /></label>
        <label>Effective until {restrictionAction === 'SUSPEND' ? '(required)' : '(optional)'}<input type="datetime-local" value={restrictionExpiry} onChange={(event) => setRestrictionExpiry(event.target.value)} disabled={restrictionBusy} required={restrictionAction === 'SUSPEND'} /></label>
        <label>Case comment (optional)<textarea value={restrictionComment} onChange={(event) => setRestrictionComment(event.target.value)} maxLength={3000} disabled={restrictionBusy} /></label>
        <button className="admin-button admin-button-primary" type="submit" disabled={restrictionBusy}>{restrictionBusy ? 'Submitting proposal…' : 'Create proposal'}</button>
      </form>
      {restrictionMessage && <p className="form-hint" role="status">{restrictionMessage} <a href="/operations">Review operations</a>.</p>}
    </section>}
    {!recordId && !loading && !error && <>
      <div className="taxonomy-toolbar"><label>Search {config.serverSearch ? 'using the API' : 'loaded rows'}<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={config.serverSearch ? 'Search products' : 'Search loaded pages'} /></label><span>Loaded: {items.length}</span></div>
      {visible.length ? <div className="admin-table-wrap"><table className="admin-table registry-table"><thead><tr>{config.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead><tbody>{visible.map((row, i) => <tr key={String(row[config.idKey] ?? i)}>{config.columns.map((c) => <td key={c.key}>{config.detailBase && c.key === config.idKey && typeof row[c.key] === 'string' ? <a className="ticket-link" href={`${config.detailBase}/${encodeURIComponent(String(row[c.key]))}`}>{String(row[c.key])}</a> : c.render ? c.render(row) : display(row[c.key])}</td>)}</tr>)}</tbody></table></div> : <div className="admin-empty"><h2>{items.length ? 'No matches' : 'No records'}</h2><p>{items.length ? 'Change the search query.' : 'The API returned an empty list.'}</p></div>}
      {hasMore && <div className="queue-more"><button className="admin-button" onClick={() => void loadList(true)} disabled={loading}>Load more</button></div>}
    </>}
  </AdminShell>;
}
