'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import {
  sellerApiRequest,
  sellerArray,
  sellerInteger,
  sellerObject,
  sellerString,
} from './lib/seller-api';

import { type ChangeEvent, useEffect, useState } from 'react';

type ImportRow = { row_number: number; seller_article: string; target_on_hand: number; before_on_hand: number | null; delta: number | null; state: 'VALID' | 'INVALID' | 'UNCHANGED' | 'APPLIED' | 'CONFLICT'; error_code: string | null; error_message: string | null; result_on_hand: number | null };
type ImportJob = { id: string; mode: string; source_sha256: string; state: 'PREVIEWED' | 'COMMITTED' | 'PARTIAL'; total_rows: number; valid_rows: number; error_rows: number; applied_rows: number; committed_at: string | null; rows: ImportRow[] };

function nullableInteger(value: unknown, path: string): number | null {
  return value === null ? null : sellerInteger(value, path);
}

function decodeImportJob(value: unknown): ImportJob {
  const item = sellerObject(value, 'inventory import');
  const state = sellerString(item.state, 'inventory import.state');
  if (state !== 'PREVIEWED' && state !== 'COMMITTED' && state !== 'PARTIAL') throw new TypeError('inventory import.state is invalid');
  const committedAt = item.committed_at === null ? null : sellerString(item.committed_at, 'inventory import.committed_at');
  const rows = sellerArray(item.rows, 'inventory import.rows', (value) => {
    const row = sellerObject(value, 'inventory import row');
    const rowState = sellerString(row.state, 'inventory import row.state');
    if (!['VALID', 'INVALID', 'UNCHANGED', 'APPLIED', 'CONFLICT'].includes(rowState)) throw new TypeError('inventory import row.state is invalid');
    return {
      row_number: sellerInteger(row.row_number, 'inventory import row.row_number'),
      seller_article: sellerString(row.seller_article, 'inventory import row.seller_article'),
      target_on_hand: sellerInteger(row.target_on_hand, 'inventory import row.target_on_hand'),
      before_on_hand: nullableInteger(row.before_on_hand, 'inventory import row.before_on_hand'),
      delta: nullableInteger(row.delta, 'inventory import row.delta'),
      state: rowState as ImportRow['state'],
      error_code: row.error_code === null ? null : sellerString(row.error_code, 'inventory import row.error_code'),
      error_message: row.error_message === null ? null : sellerString(row.error_message, 'inventory import row.error_message'),
      result_on_hand: nullableInteger(row.result_on_hand, 'inventory import row.result_on_hand'),
    };
  });
  return {
    id: sellerString(item.id, 'inventory import.id'),
    mode: sellerString(item.mode, 'inventory import.mode'),
    source_sha256: sellerString(item.source_sha256, 'inventory import.source_sha256'),
    state,
    total_rows: sellerInteger(item.total_rows, 'inventory import.total_rows'),
    valid_rows: sellerInteger(item.valid_rows, 'inventory import.valid_rows'),
    error_rows: sellerInteger(item.error_rows, 'inventory import.error_rows'),
    applied_rows: sellerInteger(item.applied_rows, 'inventory import.applied_rows'),
    committed_at: committedAt,
    rows,
  };
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { cell += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else cell += character;
    } else if (character === '"' && cell.length === 0) quoted = true;
    else if (character === ',') { row.push(cell); cell = ''; }
    else if (character === '\n' || character === '\r') {
      if (character === '\r' && text[index + 1] === '\n') index += 1;
      row.push(cell); cell = '';
      if (row.some((value) => value.trim() !== '')) rows.push(row);
      row = [];
    } else cell += character;
  }
  if (quoted) throw new Error('CSV has an unfinished quoted field');
  row.push(cell);
  if (row.some((value) => value.trim() !== '')) rows.push(row);
  return rows;
}

async function filePayload(file: File, reason: string) {
  if (file.size > 1_000_000) throw new Error('CSV must be 1 MB or smaller');
  const bytes = await file.arrayBuffer();
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
  const parsed = parseCsv(text);
  if (parsed.length < 2) throw new Error('CSV needs a header and at least one data row');
  const headers = (parsed[0] ?? []).map((value) => value.trim().toLowerCase());
  if (headers.length !== 2 || headers[0] !== 'seller_article' || headers[1] !== 'on_hand') {
    throw new Error('Expected exactly two columns: seller_article,on_hand');
  }
  const dataRows = parsed.slice(1);
  if (dataRows.length > 500) throw new Error('Import is limited to 500 rows');
  const rows = dataRows.map((values, index) => {
    const article = values[0]?.trim() ?? '';
    const count = values[1]?.trim() ?? '';
    if (values.length !== 2 || !article || !/^\d+$/.test(count)) throw new Error(`Row ${index + 2} must contain an article and a whole-number count`);
    const on_hand = Number(count);
    if (!Number.isSafeInteger(on_hand) || on_hand < 0) throw new Error(`Row ${index + 2} has an invalid on_hand value`);
    return { seller_article: article, on_hand };
  });
  const source_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map((value) => value.toString(16).padStart(2, '0')).join('');
  return { mode: 'COUNT', source_sha256, reason: reason.trim(), rows };
}

export function InventoryImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState('Physical stock count');
  const [job, setJob] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [previewKey, setPreviewKey] = useState('');
  const [commitKey, setCommitKey] = useState('');

  useEffect(() => {
    const jobId = sessionStorage.getItem('seller.inventoryImportJobId');
    if (!jobId) return;
    setPreviewKey(sessionStorage.getItem('seller.inventoryImportPreviewKey') ?? '');
    setCommitKey(sessionStorage.getItem('seller.inventoryImportCommitKey') ?? '');
    sellerApiRequest(`/api/seller/imports/${jobId}`, { cache: 'no-store' }, decodeImportJob)
      .then(setJob)
      .catch(() => setError('Saved import status is unavailable. Start a new preview if this import is no longer accessible.'));
  }, []);

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setJob(null); setError(''); setPreviewKey(''); setCommitKey('');
    sessionStorage.removeItem('seller.inventoryImportJobId');
    sessionStorage.removeItem('seller.inventoryImportPreviewKey');
    sessionStorage.removeItem('seller.inventoryImportCommitKey');
  }

  function startNewImport() {
    setFile(null); setJob(null); setError(''); setPreviewKey(''); setCommitKey('');
    sessionStorage.removeItem('seller.inventoryImportJobId');
    sessionStorage.removeItem('seller.inventoryImportPreviewKey');
    sessionStorage.removeItem('seller.inventoryImportCommitKey');
  }

  async function csrfToken() {
    return sellerApiRequest('/api/seller/auth/csrf', { cache: 'no-store' }, (value) =>
      sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
    );
  }

  async function preview() {
    if (!file) return;
    setBusy(true); setError('');
    try {
      const body = await filePayload(file, reason);
      const key = previewKey || crypto.randomUUID();
      setPreviewKey(key);
      sessionStorage.setItem('seller.inventoryImportPreviewKey', key);
      const value = await sellerApiRequest('/api/seller/imports', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': await csrfToken(), 'Idempotency-Key': key }, body: JSON.stringify(body) }, decodeImportJob);
      setJob(value);
      sessionStorage.setItem('seller.inventoryImportJobId', value.id);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Import preview could not be confirmed. Retry to resolve its status.'));
    } finally { setBusy(false); }
  }

  async function commit() {
    if (!job) return;
    const key = commitKey || crypto.randomUUID();
    setCommitKey(key); setBusy(true); setError('');
    sessionStorage.setItem('seller.inventoryImportCommitKey', key);
    try {
      const value = await sellerApiRequest(`/api/seller/imports/${job.id}`, { method: 'POST', headers: { 'X-CSRF-Token': await csrfToken(), 'Idempotency-Key': key } }, decodeImportJob);
      setJob(value);
    } catch (cause) {
      try {
        const current = await sellerApiRequest(`/api/seller/imports/${job.id}`, { cache: 'no-store' }, decodeImportJob);
        setJob(current);
        if (current.state !== 'PREVIEWED') return;
      } catch { /* The same idempotency key remains available for retry. */ }
      setError(sellerErrorMessage(cause, 'Commit status is unknown. Retry safely with the same key.'));
    } finally { setBusy(false); }
  }

  return <main className="seller-app" id="main-content">
    <SellerSidebar variant="inventory" activePath="/imports" badge="OWNER-SCOPED API" />
    <section className="seller-content"><div className="private-bar"><span>SELLER / INVENTORY IMPORT</span><span>DRY-RUN BEFORE WRITE</span></div><p className="eyebrow">SELLER HUB / SE-08</p><div className="page-heading"><div><h1>Import stock counts</h1><p className="seller-intro">Upload a UTF-8 CSV with `seller_article,on_hand`. Preview does not change stock.</p></div><a className="seller-product-link" href="/inventory">Back to inventory</a></div>
      <section className="seller-section"><div className="seller-form"><label>Stock count CSV<input key={job?.id ?? 'new-import'} type="file" accept=".csv,text/csv" onChange={onFileChange} disabled={busy || job?.state !== undefined} /></label><label>Reason for this count<input value={reason} maxLength={64} onChange={(event) => setReason(event.target.value)} disabled={busy || !!job} /></label><p className="seller-muted">Maximum 500 rows and 1 MB. Every article must identify exactly one of your SKUs. Rows below reserved stock are rejected.</p><button className="seller-submit" type="button" onClick={() => void preview()} disabled={busy || !file || !!job}>{busy ? 'Checking…' : 'Preview import'}</button></div></section>
      {error && <p className="seller-state seller-error" role="alert">{error}</p>}
      {job && <section className="seller-section" aria-label="Import preview"><div className="detail-heading"><div><h2>{job.state === 'PREVIEWED' ? 'Dry-run preview' : 'Import result'}</h2><p className="seller-muted">Job {job.id} · SHA-256 {job.source_sha256}</p></div><span className="status-badge">{job.state}</span></div><p role="status">{job.total_rows} rows · {job.valid_rows} valid/unchanged · {job.error_rows} errors · {job.applied_rows} applied</p><div className="seller-table-wrap" tabIndex={0}><table className="seller-table"><caption className="sr-only">Inventory import row results</caption><thead><tr><th>CSV row</th><th>Article</th><th>Current</th><th>Target</th><th>Delta</th><th>Result</th></tr></thead><tbody>{job.rows.map((row) => <tr key={row.row_number}><th scope="row">{row.row_number + 1}</th><td>{row.seller_article}</td><td>{row.before_on_hand ?? '—'}</td><td>{row.target_on_hand}</td><td>{row.delta ?? '—'}</td><td><span className="status-badge">{row.state}</span>{row.error_message && <div role="alert">{row.error_message}</div>}</td></tr>)}</tbody></table></div>{job.state === 'PREVIEWED' ? <button className="seller-submit" type="button" onClick={() => void commit()} disabled={busy || job.valid_rows === 0}>{busy ? 'Applying…' : 'Commit valid rows'}</button> : <button className="seller-submit" type="button" onClick={startNewImport}>Start a new import</button>}</section>}
    </section>
  </main>;
}
