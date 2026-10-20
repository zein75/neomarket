'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import {
  SellerApiError,
  sellerApiRequest,
  sellerArray,
  sellerBoolean,
  sellerInteger,
  sellerObject,
  sellerOptionalNullableString,
  sellerString,
} from './lib/seller-api';

import { type FormEvent, useEffect, useRef, useState } from 'react';

type FieldReport = { field_name: string; field_path?: string | null; reason_code?: string | null; comment: string };
type Characteristic = { name: string; value: string };
type Product = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  slug: string;
  category_id?: string | null;
  revision: number;
  blocked?: boolean;
  blocking_reason?: { title: string; comment: string } | null;
  field_reports?: FieldReport[];
  characteristics: Characteristic[];
  skus?: Array<{ id: string; name: string; price: number; stock_quantity: number; active_quantity: number; reserved_quantity: number; is_active: boolean }>;
  updated_at: string;
};
type SavedDraft = { title: string; description: string; attributesJson: string; revision: number };

function decodeProduct(value: unknown, detail: boolean): Product {
  const item = sellerObject(value, 'product');
  const status = sellerString(item.status, 'product.status');
  const characteristics = sellerArray(item.characteristics, 'product.characteristics', (value) => {
    const characteristic = sellerObject(value, 'product characteristic');
    return { name: sellerString(characteristic.name, 'characteristic.name'), value: sellerString(characteristic.value, 'characteristic.value') };
  });
  const skus = sellerArray(item.skus, 'product.skus', (value) => {
    const sku = sellerObject(value, 'product SKU');
    return {
      id: sellerString(sku.id, 'SKU.id'),
      name: sellerString(sku.name, 'SKU.name'),
      price: sellerInteger(sku.price, 'SKU.price'),
      stock_quantity: sellerInteger(sku.stock_quantity, 'SKU.stock_quantity'),
      active_quantity: sellerInteger(sku.active_quantity, 'SKU.active_quantity'),
      reserved_quantity: sellerInteger(sku.reserved_quantity, 'SKU.reserved_quantity'),
      is_active: sellerBoolean(sku.is_active, 'SKU.is_active'),
    };
  });
  const description = item.description === null ? null : sellerString(item.description, 'product.description');
  const categoryId = item.category_id === null ? null : sellerString(item.category_id, 'product.category_id');
  const product: Product = {
    id: sellerString(item.id, 'product.id'),
    title: sellerString(item.title, 'product.title'),
    description,
    status,
    slug: sellerString(item.slug, 'product.slug'),
    category_id: categoryId,
    revision: sellerInteger(item.revision, 'product.revision'),
    characteristics,
    skus,
    updated_at: sellerString(item.updated_at, 'product.updated_at'),
  };
  if (detail) {
    product.blocked = sellerBoolean(item.blocked, 'product.blocked');
    const blockingReason = item.blocking_reason === null ? null : sellerObject(item.blocking_reason, 'product.blocking_reason');
    product.blocking_reason = blockingReason === null ? null : {
      title: sellerString(blockingReason.title, 'product.blocking_reason.title'),
      comment: sellerString(blockingReason.comment, 'product.blocking_reason.comment'),
    };
    product.field_reports = sellerArray(item.field_reports, 'product.field_reports', (value) => {
      const report = sellerObject(value, 'product field report');
      const fieldPath = sellerOptionalNullableString(report.field_path, 'field report.field_path');
      const reasonCode = sellerOptionalNullableString(report.reason_code, 'field report.reason_code');
      return {
        field_name: sellerString(report.field_name, 'field report.field_name'),
        ...(fieldPath === undefined ? {} : { field_path: fieldPath }),
        ...(reasonCode === undefined ? {} : { reason_code: reasonCode }),
        comment: sellerString(report.comment, 'field report.comment'),
      };
    });
  }
  return product;
}

const decodeProductDetail = (value: unknown) => decodeProduct(value, true);
const decodeProductMutation = (value: unknown) => decodeProduct(value, false);

export function ProductDetailPage({ productId }: { productId: string }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [pending, setPending] = useState(true);
  const [saving, setSaving] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [attributesJson, setAttributesJson] = useState('{}');
  const [savedDraft, setSavedDraft] = useState<SavedDraft | null>(null);
  const [draftSaveState, setDraftSaveState] = useState<'saved' | 'unsaved' | 'saving' | 'conflict'>('saved');
  const [conflict, setConflict] = useState<Product | null>(null);
  const [draftError, setDraftError] = useState('');
  const [draftRetry, setDraftRetry] = useState(0);
  const autosaveInFlight = useRef(false);
  const currentDraft = useRef({ title, description, attributesJson });
  currentDraft.current = { title, description, attributesJson };

  async function loadProduct() {
    setPending(true);
    setError('');
    try {
      const value = await sellerApiRequest(`/api/seller/products/${productId}`, { cache: 'no-store' }, decodeProductDetail);
      setProduct(value);
      setTitle(value.title);
      setDescription(value.description ?? '');
      setAttributesJson(JSON.stringify(Object.fromEntries((value.characteristics ?? []).map((item) => [item.name, item.value])), null, 2));
      const baseline = { title: value.title, description: value.description ?? '', attributesJson: JSON.stringify(Object.fromEntries((value.characteristics ?? []).map((item) => [item.name, item.value])), null, 2), revision: value.revision };
      setSavedDraft(baseline);
      setDraftSaveState('saved');
      setConflict(null);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Unable to load product'));
    } finally {
      setPending(false);
    }
  }

  useEffect(() => { void loadProduct(); }, [productId]);

  async function fetchLatestForConflict() {
    const latest = await sellerApiRequest(`/api/seller/products/${productId}`, { cache: 'no-store' }, decodeProductDetail);
    setProduct(latest);
    setConflict(latest);
    setDraftSaveState('conflict');
  }

  useEffect(() => {
    if (!product || product.status !== 'BLOCKED' || !savedDraft || conflict) return;
    if (title === savedDraft.title && description === savedDraft.description && attributesJson === savedDraft.attributesJson) {
      setDraftSaveState((state) => state === 'saving' ? state : 'saved');
      return;
    }
    setDraftSaveState('unsaved');
    setDraftError('');
    const snapshot = { title, description, attributesJson };
    const timer = window.setTimeout(() => {
      void (async function saveDraft(value: { title: string; description: string; attributesJson: string }) {
        if (autosaveInFlight.current) return;
        const baseline = savedDraft;
        if (!baseline) return;
        autosaveInFlight.current = true;
        setDraftSaveState('saving');
        try {
          const parsedAttributes = JSON.parse(value.attributesJson) as unknown;
          if (!parsedAttributes || Array.isArray(parsedAttributes) || typeof parsedAttributes !== 'object' || Object.values(parsedAttributes).some((item) => typeof item !== 'string')) {
            throw new Error('Product attributes must be a JSON object with string values.');
          }
          const csrfToken = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) =>
            sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
          );
          const updated = await sellerApiRequest(`/api/seller/products/${product.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'If-Match': `"${baseline.revision}"` },
            body: JSON.stringify({ title: value.title.trim(), description: value.description, characteristics: Object.entries(parsedAttributes as Record<string, string>).map(([name, item]) => ({ name, value: item })) }),
          }, decodeProductMutation);
          const nextBaseline = { title: value.title.trim(), description: value.description, attributesJson: value.attributesJson, revision: updated.revision };
          setProduct((current) => current ? { ...current, ...updated, field_reports: current.field_reports ?? [], blocking_reason: current.blocking_reason ?? null } : updated);
          setSavedDraft(nextBaseline);
          setDraftSaveState(currentDraft.current.title === nextBaseline.title && currentDraft.current.description === nextBaseline.description && currentDraft.current.attributesJson === nextBaseline.attributesJson ? 'saved' : 'unsaved');
        } catch (cause) {
          if (cause instanceof SellerApiError && cause.status === 412) {
            setDraftError('');
            try { await fetchLatestForConflict(); }
            catch (latestError) {
              setDraftError(sellerErrorMessage(latestError, 'The latest server revision could not be loaded. Your local corrections are still here.'));
              setDraftSaveState('unsaved');
            }
            return;
          }
          setDraftError(sellerErrorMessage(cause, 'Draft save was not confirmed'));
          setDraftSaveState('unsaved');
        } finally {
          autosaveInFlight.current = false;
        }
      })(snapshot);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [title, description, attributesJson, product?.id, product?.status, savedDraft, conflict, draftRetry]);

  useEffect(() => {
    if (!product || product.status !== 'BLOCKED' || draftSaveState === 'saved') return;
    const warnBeforeLeave = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warnBeforeLeave);
    return () => window.removeEventListener('beforeunload', warnBeforeLeave);
  }, [product, draftSaveState]);

  function useServerDraft() {
    if (!conflict) return;
    setTitle(conflict.title);
    setDescription(conflict.description ?? '');
    const attributes = JSON.stringify(Object.fromEntries((conflict.characteristics ?? []).map((item) => [item.name, item.value])), null, 2);
    setAttributesJson(attributes);
    setSavedDraft({ title: conflict.title, description: conflict.description ?? '', attributesJson: attributes, revision: conflict.revision });
    setConflict(null);
    setError('');
    setDraftSaveState('saved');
  }

  function rebaseLocalDraft() {
    if (!conflict || conflict.status !== 'BLOCKED') return;
    setSavedDraft({ title: conflict.title, description: conflict.description ?? '', attributesJson: JSON.stringify(Object.fromEntries((conflict.characteristics ?? []).map((item) => [item.name, item.value])), null, 2), revision: conflict.revision });
    setConflict(null);
    setError('');
    setDraftSaveState('unsaved');
  }

  useEffect(() => {
    if (!conflict) return;
    const firstAction = document.querySelector<HTMLElement>('.seller-dialog-actions button');
    firstAction?.focus();
  }, [conflict]);

  async function resubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!product) return;
    let attributes: unknown;
    try {
      attributes = JSON.parse(attributesJson);
      if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes) || Object.values(attributes).some((value) => typeof value !== 'string')) {
        throw new Error('Attributes must be a JSON object with string values');
      }
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Check the attributes JSON'));
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const csrfToken = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) =>
        sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
      );
      const updated = await sellerApiRequest(`/api/seller/products/${product.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'If-Match': `"${product.revision}"` },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim(),
          characteristics: Object.entries(attributes as Record<string, string>).map(([name, value]) => ({ name, value })),
        }),
      }, decodeProductMutation);
      setProduct((current) => current ? { ...current, ...updated, field_reports: current.field_reports ?? [], blocking_reason: current.blocking_reason ?? null } : updated);
      setNotice('Corrections saved. The new revision was sent for moderation.');
    } catch (cause) {
      if (cause instanceof SellerApiError && cause.status === 412) {
        try { await fetchLatestForConflict(); }
        catch (latestError) { setError(sellerErrorMessage(latestError, 'The latest server revision could not be loaded.')); }
        return;
      }
      setError(sellerErrorMessage(cause, 'Product update was not confirmed'));
    } finally {
      setSaving(false);
    }
  }

  async function archiveProduct() {
    if (!product || archiving) return;
    if (!window.confirm('Archive this product? It will leave the catalog. Existing seller orders will keep their product and SKU details.')) return;
    setArchiving(true);
    setError('');
    setNotice('');
    try {
      const csrfToken = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'include', cache: 'no-store' }, (value) =>
        sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
      );
      await sellerApiRequest(`/api/seller/products/${product.id}`, {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': csrfToken },
      }, (value) => {
        if (value !== null && value !== undefined) throw new TypeError('product archive response must be empty');
        return true;
      });
      window.location.assign('/products?archived=1');
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Product archive was not confirmed'));
    } finally {
      setArchiving(false);
    }
  }

  return (
    <main className="seller-app" id="main-content">
      <SellerSidebar variant="catalog" activePath="/products" badge="OWNER-SCOPED API" />
      <section className="seller-content">
        <div className="private-bar"><span>SELLER / PRODUCT DETAIL</span><span>SERVER DATA ONLY</span></div>
        {pending && <p className="seller-state" role="status">Загружаем карточку…</p>}
        {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => void loadProduct()}>Reload</button><a className="seller-submit" href="/products">К списку товаров</a></div>}
        {!pending && !error && product && <>
          <p className="eyebrow">SELLER HUB / SE-06 / {product.slug} / REV {product.revision}</p>
          <div className="detail-heading"><div><h1>{product.title}</h1><p className="seller-intro">{product.description || 'Описание не заполнено.'}</p></div><span className="status-badge">{product.status}</span></div>
          {notice && <p className="seller-notice" role="status">{notice}</p>}
          {product.status !== 'HARD_BLOCKED' && <section className="seller-section" aria-label="Product archive">
            <h2>Archive product</h2>
            <p className="seller-muted">The product leaves the catalog. Existing seller orders keep their saved product and SKU details.</p>
            <button className="seller-submit" type="button" onClick={() => void archiveProduct()} disabled={archiving}>{archiving ? 'Archiving…' : 'Archive product'}</button>
          </section>}
          {product.blocking_reason && <div className="moderation-comment"><strong>{product.blocking_reason.title}</strong><p>{product.blocking_reason.comment}</p></div>}
          {!!product.field_reports?.length && <section className="seller-section"><h2>Замечания по полям</h2><ul className="field-reports">{product.field_reports.map((report) => <li key={`${report.field_path || report.field_name}-${report.comment}`}><strong>{report.field_path || report.field_name}{report.reason_code ? ` · ${report.reason_code}` : ''}</strong><span>{report.comment}</span></li>)}</ul></section>}
          {product.status === 'BLOCKED' && <section className="seller-section">
            <h2>Correct rejected fields</h2>
            <p className="seller-muted">Corrections save automatically as a draft. Submit them for review when you are ready.</p>
            <p className="seller-muted" role="status" aria-live="polite">{draftSaveState === 'saving' ? 'Saving draft…' : draftSaveState === 'saved' ? 'All changes saved.' : draftSaveState === 'conflict' ? 'Resolve the revision conflict to continue.' : 'Unsaved changes.'}</p>
            {draftError && <div className="seller-state seller-error" role="alert"><span>{draftError}</span><button className="seller-secondary" type="button" onClick={() => { setDraftError(''); setDraftRetry((value) => value + 1); }}>Retry draft save</button></div>}
            <form className="seller-form" onSubmit={(event) => void resubmit(event)}>
              <label>Product title<input name="title" value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={255} /></label>
              <label>Description<textarea name="description" value={description} onChange={(event) => setDescription(event.target.value)} required maxLength={20000} rows={4} /></label>
              <label>Product attributes (JSON)<textarea name="attributes" value={attributesJson} onChange={(event) => setAttributesJson(event.target.value)} rows={5} /></label>
              <button className="seller-submit" type="submit" disabled={saving || draftSaveState !== 'saved'}>{saving ? 'Submitting revision…' : 'Submit corrections for review'}</button>
            </form>
          </section>}
          {conflict && <div className="seller-dialog-backdrop"><section className="seller-dialog" role="alertdialog" aria-modal="true" aria-labelledby="product-revision-conflict-title" onKeyDown={(event) => { if (event.key !== 'Tab') return; const actions = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')); const first = actions[0]; const last = actions.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } }}><h2 id="product-revision-conflict-title">This draft changed elsewhere</h2><p>The server has revision {conflict.revision}. Your title, description and attributes are still available in this form.</p><p>Load the server version, or keep your local corrections and save them over revision {conflict.revision}.</p><div className="seller-dialog-actions"><button className="seller-secondary" type="button" onClick={useServerDraft}>Load server version</button>{conflict.status === 'BLOCKED' && <button className="seller-submit" type="button" onClick={rebaseLocalDraft}>Keep my corrections</button>}</div></section></div>}
          <section className="seller-section"><div className="section-head"><h2>SKU и остатки</h2><a className="seller-product-link" href={`/products/${product.id}/skus`}>Открыть все SKU</a></div>{product.skus?.length ? <div className="seller-table-wrap" tabIndex={0}><table className="seller-table"><thead><tr><th>SKU</th><th>Цена</th><th>На складе</th><th>Доступно</th><th>Резерв</th></tr></thead><tbody>{product.skus.map((sku) => <tr key={sku.id}><th scope="row">{sku.name}</th><td>{sku.price}</td><td>{sku.stock_quantity}</td><td>{sku.active_quantity}</td><td>{sku.reserved_quantity}</td></tr>)}</tbody></table></div> : <p className="seller-state">SKU ещё не добавлены.</p>}</section>
          {product.status !== 'BLOCKED' && <p className="seller-disclaimer">Редактирование отключено: текущая карточка не предоставляет подтверждённый revision/upload workflow.</p>}
        </>}
      </section>
    </main>
  );
}
