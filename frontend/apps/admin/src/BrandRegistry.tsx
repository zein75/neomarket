'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { AdminShell } from './AdminPage';

type Brand = {
  id: string;
  name: string;
  aliases: string[];
  status: 'DRAFT' | 'VERIFIED' | 'RESTRICTED' | 'MERGED';
  evidence_ref: string | null;
  merged_into_id: string | null;
  version: number;
};
type BrandPage = { items: Brand[]; page: { has_more: boolean; next_cursor: string | null } };
type MergePreview = { change_id: string; source_brand_id: string; target_brand_id: string; affected_products: number; hash: string; expires_at: string };
type Draft = { name: string; aliases: string; evidence_ref: string };
const emptyDraft: Draft = { name: '', aliases: '', evidence_ref: '' };

async function errorMessage(response: Response): Promise<string> {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: { code?: unknown; message?: unknown } | string } | null;
  const detail = body?.detail;
  const code = typeof body?.code === 'string' ? body.code : typeof detail === 'object' && typeof detail?.code === 'string' ? detail.code : '';
  const message = typeof body?.message === 'string' ? body.message : typeof detail === 'object' && typeof detail?.message === 'string' ? detail.message : typeof detail === 'string' ? detail : '';
  return [code, message, `HTTP ${response.status}`].filter(Boolean).join(' · ');
}

export function BrandRegistry() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [search, setSearch] = useState('');
  const [reasonCode, setReasonCode] = useState('BRAND_CHANGE');
  const [mergeTarget, setMergeTarget] = useState('');
  const [preview, setPreview] = useState<MergePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const collected: Brand[] = [];
      let cursor: string | null = null;
      do {
        const params = new URLSearchParams({ limit: '100' });
        if (cursor) params.set('cursor', cursor);
        const response = await fetch(`/api/admin/v1/taxonomy/brands?${params}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(await errorMessage(response));
        const page = await response.json() as BrandPage;
        if (!Array.isArray(page.items) || !page.page) throw new Error('The brand registry response does not match its API contract.');
        collected.push(...page.items); cursor = page.page.next_cursor;
        if (!page.page.has_more) cursor = null;
      } while (cursor);
      setBrands(collected);
      setSelectedId((current) => collected.some((brand) => brand.id === current) ? current : '');
    } catch (caught) {
      setBrands([]); setError(caught instanceof Error ? caught.message : 'Brand registry is unavailable.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const selected = brands.find((brand) => brand.id === selectedId) ?? null;
  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return brands.filter((brand) => !needle || [brand.name, ...brand.aliases, brand.status].some((value) => value.toLocaleLowerCase().includes(needle)));
  }, [brands, search]);

  const submitProposal = async (path: string, body: unknown, method: 'POST' | 'PATCH', version?: number) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(path, {
        method, cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID(), ...(version ? { 'If-Match': `v${version}` } : {}) },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const operation = await response.json() as { operation_id?: string; status?: string };
      setNotice(`Proposal created (${operation.status ?? 'status pending'})${operation.operation_id ? ` · ${operation.operation_id}` : ''}. It takes effect only after independent approval.`);
      setPreview(null); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'The proposal response was not received.'); }
    finally { setBusy(false); }
  };

  const saveBrand = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = { name: draft.name.trim(), aliases: draft.aliases.split('\n').map((item) => item.trim()).filter(Boolean), evidence_ref: draft.evidence_ref.trim() || null };
    const path = selected ? `/api/admin/v1/taxonomy/brands/${encodeURIComponent(selected.id)}` : '/api/admin/v1/taxonomy/brands';
    await submitProposal(path, payload, selected ? 'PATCH' : 'POST', selected?.version);
  };

  const verifyBrand = async () => {
    if (!selected || !draft.evidence_ref.trim() || !reasonCode.trim()) return;
    await submitProposal(`/api/admin/v1/taxonomy/brands/${encodeURIComponent(selected.id)}/verify`, { evidence_ref: draft.evidence_ref.trim(), reason_code: reasonCode.trim().toUpperCase() }, 'POST', selected.version);
  };

  const requestMergePreview = async () => {
    if (!selected || !mergeTarget) return;
    setBusy(true); setError(''); setNotice(''); setPreview(null);
    try {
      const response = await fetch(`/api/admin/v1/taxonomy/brands/${encodeURIComponent(selected.id)}/merge-preview`, {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ target_brand_id: mergeTarget }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const result = await response.json() as MergePreview;
      if (!/^[0-9a-f]{64}$/.test(result.hash) || result.source_brand_id !== selected.id || result.target_brand_id !== mergeTarget) throw new Error('B2B returned an invalid merge preview.');
      setPreview(result);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Merge preview is unavailable.'); }
    finally { setBusy(false); }
  };

  const proposeMerge = async () => {
    if (!selected || !preview || !reasonCode.trim()) return;
    await submitProposal(`/api/admin/v1/taxonomy/brands/${encodeURIComponent(selected.id)}/merge`, {
      target_brand_id: preview.target_brand_id, impact_hash: preview.hash, reason_code: reasonCode.trim().toUpperCase(),
    }, 'POST', selected.version);
  };

  return <AdminShell section="/taxonomy/brands">
    <p className="eyebrow">ADMIN CONSOLE / TAXONOMY / BRANDS</p>
    <div className="admin-heading-row"><div><h1>Brand registry</h1><p className="admin-intro">Canonical names, aliases, evidence review and preview-bound merging from B2B.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading || busy}>Refresh</button></div>
    {error && <div className="admin-alert" role="alert"><strong>Action unavailable</strong><span>{error}</span></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    {loading ? <div className="admin-empty" role="status"><h2>Loading brand registry…</h2></div> : <div className="taxonomy-layout">
      <section className="admin-panel taxonomy-tree" aria-label="Brand registry list">
        <div className="section-heading"><div><p className="eyebrow">B2B AUTHORITY</p><h2>Brands</h2></div><span>{brands.length} records</span></div>
        <label>Search names and aliases<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        {visible.length ? <ul className="taxonomy-list">{visible.map((brand) => <li key={brand.id}><button className="taxonomy-node" aria-current={selectedId === brand.id ? 'true' : undefined} onClick={() => { setSelectedId(brand.id); setDraft({ name: brand.name, aliases: brand.aliases.join('\n'), evidence_ref: brand.evidence_ref ?? '' }); setPreview(null); setError(''); setNotice(''); }}><span className="taxonomy-node-name">{brand.name}<small>{brand.aliases.length ? brand.aliases.join(', ') : 'No aliases'}</small></span><span className={`state-pill state-${brand.status.toLowerCase()}`}>{brand.status} · v{brand.version}</span></button></li>)}</ul> : <div className="admin-empty"><h2>{brands.length ? 'No matches' : 'No brands yet'}</h2><p>Use the draft form to propose a canonical brand record.</p></div>}
        <button className="admin-button admin-button-primary" type="button" onClick={() => { setSelectedId(''); setDraft(emptyDraft); setPreview(null); setError(''); setNotice(''); }}>Create brand draft</button>
      </section>
      <section className="admin-panel taxonomy-inspector" aria-label="Brand review and actions">
        <p className="eyebrow">{selected ? `BRAND REVIEW · V${selected.version}` : 'NEW BRAND PROPOSAL'}</p>
        <h2>{selected?.name ?? 'Create a brand draft'}</h2>
        <form className="taxonomy-form" onSubmit={saveBrand}>
          <label>Canonical name<input required maxLength={255} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} disabled={busy || selected?.status === 'MERGED' || selected?.status === 'RESTRICTED'} /></label>
          <label>Aliases, one per line<textarea rows={4} value={draft.aliases} onChange={(event) => setDraft((current) => ({ ...current, aliases: event.target.value }))} disabled={busy || selected?.status === 'MERGED' || selected?.status === 'RESTRICTED'} /></label>
          <label>Evidence reference<input maxLength={2048} value={draft.evidence_ref} onChange={(event) => setDraft((current) => ({ ...current, evidence_ref: event.target.value }))} disabled={busy || selected?.status === 'MERGED' || selected?.status === 'RESTRICTED'} /></label>
          <button className="admin-button admin-button-primary" type="submit" disabled={busy || !draft.name.trim() || selected?.status === 'MERGED' || selected?.status === 'RESTRICTED'}>{selected ? 'Propose edit' : 'Propose brand'}</button>
        </form>
        {selected?.status === 'DRAFT' && <section className="taxonomy-archive"><h3>Review evidence</h3><label>Review reason code<input value={reasonCode} onChange={(event) => setReasonCode(event.target.value.toUpperCase())} pattern="[A-Z][A-Z0-9_]{0,63}" maxLength={64} /></label><p className="form-hint">Verification requires a different staff member to approve the evidence reference.</p><button className="admin-button" type="button" onClick={() => void verifyBrand()} disabled={busy || !selected.evidence_ref}>Propose verification</button></section>}
        {selected && selected.status !== 'MERGED' && <section className="taxonomy-archive"><h3>Merge duplicate record</h3><label>Verified canonical target<select value={mergeTarget} onChange={(event) => { setMergeTarget(event.target.value); setPreview(null); }} disabled={busy}><option value="">Choose target</option>{brands.filter((brand) => brand.id !== selected.id && brand.status === 'VERIFIED').map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}</select></label><div className="taxonomy-actions"><button className="admin-button" type="button" onClick={() => void requestMergePreview()} disabled={busy || !mergeTarget}>Preview affected products</button>{preview && <button className="admin-button admin-button-primary" type="button" onClick={() => void proposeMerge()} disabled={busy || !reasonCode.trim()}>Submit merge proposal</button>}</div>{preview && <div className="admin-notice taxonomy-impact-note"><strong>Server preview</strong><p>{preview.affected_products} product references will move to the selected verified brand.</p><p>Preview expires {new Date(preview.expires_at).toLocaleString()}</p><code>{preview.hash}</code></div>}</section>}
      </section>
    </div>}
  </AdminShell>;
}
