'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { AdminShell } from './AdminPage';

type Attribute = { id: string; code: string; name: string; data_type: string; unit: string | null; required?: boolean | null; filterable?: boolean | null; searchable?: boolean | null; comparable?: boolean | null; variant_dimension?: boolean | null; pii?: boolean | null; constraints: Record<string, unknown> | null; version: number };
type Category = { id: string; name: string; code: string; status: string; version: number; schema_version?: number };
type Rule = { attribute_id: string; required: boolean; filterable?: boolean | null; variant_dimension?: boolean | null; condition?: Record<string, unknown> | null };
type ImpactPreview = { change_id: string; affected_products: number; affected_sellers: number; affected_categories: number; invalid_products: number; requires_reapproval: number; redirects: Array<{ old_path: string; new_path: string }>; warnings: string[]; hash: string };
type ImpactJob = { job_id: string; status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'; stage: 'CATEGORIES' | 'PRODUCTS' | 'FINALIZE'; processed_categories: number; total_categories: number; processed_products: number; total_products: number; error_code: string | null; result: ImpactPreview | null };
type Draft = { code: string; name: string; data_type: string; unit: string; constraints: string; required: boolean; filterable: boolean; searchable: boolean; comparable: boolean; variant_dimension: boolean; pii: boolean };
type Operation = { key: string; signature: string };
const blank: Draft = { code: '', name: '', data_type: 'string', unit: '', constraints: '{}', required: false, filterable: false, searchable: false, comparable: false, variant_dimension: false, pii: false };
const dataTypes = ['string', 'integer', 'decimal', 'boolean', 'enum', 'multi_enum', 'date', 'reference'];

async function errorText(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; detail?: { code?: unknown; message?: unknown } | string; message?: unknown } | null;
  const code = typeof body?.code === 'string' ? body.code : typeof body?.detail === 'object' && typeof body.detail?.code === 'string' ? body.detail.code : '';
  const message = typeof body?.message === 'string' ? body.message : typeof body?.detail === 'object' && typeof body.detail?.message === 'string' ? body.detail.message : typeof body?.detail === 'string' ? body.detail : '';
  return [code, message, `HTTP ${response.status}`].filter(Boolean).join(' · ');
}

export function AttributeTaxonomy() {
  const [attributes, setAttributes] = useState<Attribute[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryError, setCategoryError] = useState('');
  const [attributeError, setAttributeError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [rules, setRules] = useState<Rule[]>([]);
  const [schemaVersion, setSchemaVersion] = useState<number | null>(null);
  const [rulesError, setRulesError] = useState('');
  const [schemaImpact, setSchemaImpact] = useState<ImpactPreview | null>(null);
  const [schemaImpactJob, setSchemaImpactJob] = useState<ImpactJob | null>(null);
  const [draft, setDraft] = useState<Draft>(blank);
  const [editing, setEditing] = useState<Attribute | null>(null);
  const [testerValues, setTesterValues] = useState('{\n  "values": {}\n}');
  const [testerResult, setTesterResult] = useState('');
  const [testerError, setTesterError] = useState('');
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState<Record<string, Operation>>({});

  const load = useCallback(async () => {
    setLoading(true); setAttributeError(''); setCategoryError('');
    const [attributeResult, categoryResult] = await Promise.allSettled([
      fetch('/api/admin/v1/taxonomy/attributes?limit=100', { cache: 'no-store', headers: { Accept: 'application/json' } }),
      fetch('/api/admin/v1/taxonomy/categories', { cache: 'no-store', headers: { Accept: 'application/json' } }),
    ]);
    if (attributeResult.status === 'fulfilled') {
      try {
        let cursor: string | null = null; const all: Attribute[] = []; const seen = new Set<string>();
        do {
          const query = new URLSearchParams({ limit: '100' }); if (cursor) query.set('cursor', cursor);
          const response = cursor === null ? attributeResult.value : await fetch(`/api/admin/v1/taxonomy/attributes?${query}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
          if (!response.ok) throw new Error(await errorText(response));
          const page = await response.json() as { items: Attribute[]; page: { has_more: boolean; next_cursor: string | null } };
          all.push(...page.items);
          if (!page.page.has_more) { cursor = null; break; }
          if (!page.page.next_cursor || seen.has(page.page.next_cursor)) throw new Error('API вернул некорректный cursor пагинации атрибутов.');
          cursor = page.page.next_cursor; seen.add(cursor);
        } while (cursor !== null);
        setAttributes(all);
      }
      catch (caught) { setAttributes([]); setAttributeError(caught instanceof Error ? caught.message : 'Не удалось загрузить атрибуты.'); }
    } else { setAttributes([]); setAttributeError('Не удалось связаться с API атрибутов.'); }
    if (categoryResult.status === 'fulfilled') {
      try { const response = categoryResult.value; if (!response.ok) throw new Error(await errorText(response)); const tree = await response.json() as { items: Category[] }; setCategories(tree.items); setCategoryId((current) => tree.items.some((item) => item.id === current) ? current : tree.items.find((item) => item.status !== 'ARCHIVED')?.id ?? ''); }
      catch (caught) { setCategories([]); setCategoryError(caught instanceof Error ? caught.message : 'Не удалось загрузить категории.'); }
    } else { setCategories([]); setCategoryError('Не удалось связаться с API категорий.'); }
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const selectedCategory = categories.find((item) => item.id === categoryId) ?? null;
  const filtered = useMemo(() => { const value = query.trim().toLocaleLowerCase('ru'); return attributes.filter((item) => !value || `${item.code} ${item.name} ${item.data_type}`.toLocaleLowerCase('ru').includes(value)); }, [attributes, query]);

  const loadRules = useCallback(async (id: string) => {
    setRulesError(''); setSchemaVersion(null); setRules([]); setSchemaImpact(null); setSchemaImpactJob(null); setTesterResult(''); setTesterError('');
    if (!id) return;
    try { const response = await fetch(`/api/admin/v1/taxonomy/categories/${encodeURIComponent(id)}/attribute-rules`, { cache: 'no-store', headers: { Accept: 'application/json' } }); if (!response.ok) throw new Error(await errorText(response)); const result = await response.json() as { items: Rule[]; schema_version: number }; setRules(result.items); setSchemaVersion(result.schema_version); }
    catch (caught) { setRulesError(caught instanceof Error ? caught.message : 'Правила категории недоступны.'); }
  }, []);
  useEffect(() => { void loadRules(categoryId); }, [categoryId, loadRules]);

  useEffect(() => {
    if (!schemaImpactJob || !['QUEUED', 'RUNNING'].includes(schemaImpactJob.status)) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`/api/admin/v1/taxonomy/impact-preview-jobs/${encodeURIComponent(schemaImpactJob.job_id)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(await errorText(response));
        const job = await response.json() as ImpactJob;
        if (cancelled) return;
        if (job.status === 'FAILED') {
          setSchemaImpactJob(null); setSchemaImpact(null); setRulesError(`Schema impact calculation stopped: ${job.error_code ?? 'unknown failure'}. Request a fresh preview.`);
        } else if (job.status === 'COMPLETED') {
          if (!job.result || !/^[0-9a-f]{64}$/.test(job.result.hash)) throw new Error('B2B completed the schema impact job without a valid result.');
          setSchemaImpact(job.result); setSchemaImpactJob(null); setMessage('Schema impact preview is ready. Review the counts before submitting the proposal.');
        } else {
          setSchemaImpactJob(job);
        }
      } catch (caught) {
        if (!cancelled) setRulesError(caught instanceof Error ? caught.message : 'Unable to refresh the schema impact preview.');
      }
    }, 1200);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [schemaImpactJob]);

  const propose = async (key: string, path: string, method: 'POST' | 'PATCH' | 'PUT', body: unknown, etag?: string) => {
    const signature = JSON.stringify({ path, method, body, etag });
    const existing = pending[key];
    if (existing && existing.signature !== signature) { setMessage('Предыдущий запрос не подтверждён. Для безопасного повтора восстановите те же поля.'); return false; }
    const operation = existing ?? { key: crypto.randomUUID(), signature };
    if (!existing) setPending((current) => ({ ...current, [key]: operation }));
    setBusy(true); setMessage('');
    try {
      const response = await fetch(path, { method, cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': operation.key, ...(etag ? { 'If-Match': etag } : {}) }, body: JSON.stringify(body) });
      if (!response.ok) { if (response.status < 500) setPending((current) => { const next = { ...current }; delete next[key]; return next; }); throw new Error(await errorText(response)); }
      const result = await response.json() as { status?: string; operation_id?: string };
      setPending((current) => { const next = { ...current }; delete next[key]; return next; });
      setMessage(`Предложение ${result.status ?? 'принято'}${result.operation_id ? ` · ${result.operation_id}` : ''}. Требуется согласование.`);
      return true;
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Ответ не получен; повторите тот же запрос с тем же ключом.'); return false; }
    finally { setBusy(false); }
  };

  const saveAttribute = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); let constraints: Record<string, unknown>;
    try { const parsed = JSON.parse(draft.constraints); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(); constraints = parsed; }
    catch { setMessage('Constraints должны быть JSON-объектом.'); return; }
    const body = { code: draft.code.trim(), name: draft.name.trim(), data_type: draft.data_type, unit: draft.unit.trim() || null, constraints, required: draft.required, filterable: draft.filterable, searchable: draft.searchable, comparable: draft.comparable, variant_dimension: draft.variant_dimension, pii: draft.pii };
    const ok = await propose(editing ? `attribute-${editing.id}` : 'attribute-create', editing ? `/api/admin/v1/taxonomy/attributes/${encodeURIComponent(editing.id)}` : '/api/admin/v1/taxonomy/attributes', editing ? 'PATCH' : 'POST', body, editing ? `v${editing.version}` : undefined);
    if (ok) { setDraft(blank); setEditing(null); }
  };

  const startEdit = (attribute: Attribute) => { setEditing(attribute); setDraft({ code: attribute.code, name: attribute.name, data_type: attribute.data_type, unit: attribute.unit ?? '', constraints: JSON.stringify(attribute.constraints ?? {}, null, 2), required: Boolean(attribute.required), filterable: Boolean(attribute.filterable), searchable: Boolean(attribute.searchable), comparable: Boolean(attribute.comparable), variant_dimension: Boolean(attribute.variant_dimension), pii: Boolean(attribute.pii) }); };
  const toggleRule = (attribute: Attribute, checked: boolean) => setRules((current) => {
    const previous = current.find((rule) => rule.attribute_id === attribute.id);
    if (!checked) return current.filter((rule) => rule.attribute_id !== attribute.id);
    return [...current, previous ?? { attribute_id: attribute.id, required: false, filterable: false, variant_dimension: false }];
  });
  const changeRule = (id: string, field: 'required' | 'filterable' | 'variant_dimension', value: boolean) => setRules((current) => current.map((rule) => rule.attribute_id === id ? { ...rule, [field]: value } : rule));
  const saveRules = async () => {
    if (!selectedCategory || schemaVersion === null || schemaImpactJob) return;
    setBusy(true); setRulesError(''); setMessage(''); setSchemaImpact(null);
    try {
      const previewResponse = await fetch(`/api/admin/v1/taxonomy/categories/${encodeURIComponent(selectedCategory.id)}/impact-preview`, {
        method: 'POST', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ change_type: 'SCHEMA_UPDATE', proposed_rules: rules }),
      });
      if (!previewResponse.ok) throw new Error(await errorText(previewResponse));
      const preview = await previewResponse.json() as ImpactPreview | ImpactJob;
      if ('job_id' in preview) {
        if (!['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'].includes(preview.status)) throw new Error('B2B returned an invalid schema impact job.');
        if (preview.status === 'COMPLETED' && preview.result) setSchemaImpact(preview.result);
        else if (preview.status === 'FAILED') throw new Error(`Schema impact calculation stopped: ${preview.error_code ?? 'unknown failure'}.`);
        else { setSchemaImpactJob(preview); setMessage('Large schema impact preview queued. The proposal stays disabled until it completes.'); return; }
      } else {
        if (!/^[0-9a-f]{64}$/.test(preview.hash)) throw new Error('B2B returned an invalid schema impact preview.');
        setSchemaImpact(preview);
      }
      const completedPreview = 'job_id' in preview ? preview.result : preview;
      if (!completedPreview) throw new Error('Schema impact preview did not return a result.');
      if (completedPreview.invalid_products > 0) {
        setRulesError(`${completedPreview.invalid_products} existing product(s) do not satisfy the new schema; migration policy is required before publishing.`);
        return;
      }
      if (completedPreview.warnings.includes('SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED')) {
        setRulesError('Search/filter index rebuild is required before publishing this schema.');
        return;
      }
      const ok = await propose(`rules-${selectedCategory.id}`, `/api/admin/v1/taxonomy/categories/${encodeURIComponent(selectedCategory.id)}/attribute-rules`, 'PUT', { schema_version: schemaVersion + 1, rules, impact_hash: completedPreview.hash }, `v${selectedCategory.version}`);
      if (ok) await loadRules(selectedCategory.id);
    } catch (caught) {
      setRulesError(caught instanceof Error ? caught.message : 'Schema impact preview is unavailable.');
    } finally { setBusy(false); }
  };
  const validate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setTesterError(''); setTesterResult('');
    if (!selectedCategory) { setTesterError('Сначала выберите категорию.'); return; }
    let values: unknown;
    try { values = JSON.parse(testerValues); if (!values || Array.isArray(values) || typeof values !== 'object' || !('values' in values)) throw new Error(); }
    catch { setTesterError('Введите JSON-объект с полем values.'); return; }
    try { const response = await fetch(`/api/admin/v1/taxonomy/categories/${encodeURIComponent(selectedCategory.id)}/schema-validate`, { method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(values) }); if (!response.ok) throw new Error(await errorText(response)); const result = await response.json(); setTesterResult(JSON.stringify(result, null, 2)); }
    catch (caught) { setTesterError(caught instanceof Error ? caught.message : 'Валидатор схемы недоступен.'); }
  };

  return <AdminShell section="/taxonomy/attributes">
    <p className="eyebrow">ADMIN CONSOLE / TAXONOMY / ATTRIBUTES</p>
    <div className="admin-heading-row"><div><h1>Атрибуты</h1><p className="admin-intro">Определения типов данных, правила категории и проверка значений используют только версии из текущего снимка API.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading}>Обновить</button></div>
    {message && <div className="admin-notice" role="status">{message}</div>}
    <div className="taxonomy-workspace attribute-workspace">
      <section className="admin-panel"><div className="section-heading"><div><p className="eyebrow">ATTRIBUTE DEFINITIONS</p><h2>Справочник</h2></div></div>
        {attributeError && <div className="admin-alert" role="alert"><strong>Атрибуты недоступны</strong><span>{attributeError}</span></div>}
        <div className="taxonomy-toolbar"><label>Поиск<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Код, название или тип"/></label><button className="admin-button admin-button-primary" onClick={() => { setEditing(null); setDraft(blank); }}>Добавить</button></div>
        {loading ? <p role="status">Загружаем определения…</p> : filtered.length ? <div className="admin-table-wrap"><table className="admin-table attribute-table"><thead><tr><th>Атрибут</th><th>Тип</th><th>Версия</th><th>Действие</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><th>{item.name}<small>{item.code}</small></th><td>{item.data_type}{item.unit ? ` · ${item.unit}` : ''}</td><td>v{item.version}</td><td><button className="text-button" onClick={() => startEdit(item)}>Изменить</button></td></tr>)}</tbody></table></div> : !attributeError && <div className="admin-empty"><h2>Атрибуты не найдены</h2><p>API вернул пустой справочник.</p></div>}
        <form className="taxonomy-form attribute-form" onSubmit={saveAttribute}><p className="eyebrow taxonomy-wide">{editing ? `UPDATE · ${editing.code}` : 'NEW ATTRIBUTE PROPOSAL'}</p><label>Code<input value={draft.code} onChange={(event) => setDraft((value) => ({ ...value, code: event.target.value }))} required disabled={busy}/></label><label>Название<input value={draft.name} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} required disabled={busy}/></label><label>Тип данных<select value={draft.data_type} onChange={(event) => setDraft((value) => ({ ...value, data_type: event.target.value }))} disabled={busy}>{dataTypes.map((type) => <option key={type}>{type}</option>)}</select></label><label>Единица измерения<input value={draft.unit} onChange={(event) => setDraft((value) => ({ ...value, unit: event.target.value }))} disabled={busy}/></label><label className="taxonomy-wide">Constraints (JSON)<textarea rows={5} value={draft.constraints} onChange={(event) => setDraft((value) => ({ ...value, constraints: event.target.value }))} spellCheck={false} disabled={busy}/></label><div className="taxonomy-wide attribute-flags">{([['required', 'Required by default'], ['filterable', 'Filterable'], ['searchable', 'Searchable'], ['comparable', 'Comparable'], ['variant_dimension', 'Variant dimension'], ['pii', 'Contains personal data']] as const).map(([field, label]) => <label key={field}><input type="checkbox" checked={draft[field]} onChange={(event) => setDraft((value) => ({ ...value, [field]: event.target.checked }))} disabled={busy}/>{label}</label>)}</div><div className="taxonomy-actions"><button className="admin-button admin-button-primary" type="submit" disabled={busy}>Создать предложение</button>{editing && <button className="admin-button" type="button" onClick={() => { setEditing(null); setDraft(blank); }}>Отмена</button>}</div></form>
      </section>
      <section className="admin-panel"><p className="eyebrow">SCHEMA RULE EDITOR</p><h2>Правила категории</h2><label className="attribute-category-select">Категория<select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} disabled={!categories.length}>{categories.filter((item) => item.status !== 'ARCHIVED').map((item) => <option value={item.id} key={item.id}>{item.name} · {item.code}</option>)}</select></label>
        {categoryError && <div className="admin-alert" role="alert"><strong>Категории недоступны</strong><span>{categoryError}</span></div>}{rulesError && <div className="admin-alert" role="alert"><strong>Правила недоступны</strong><span>{rulesError}</span></div>}
        {schemaVersion !== null && <><p className="form-hint">Схема v{schemaVersion}; сохранение создаст предложение v{schemaVersion + 1} с If-Match категории v{selectedCategory?.version}. Перед отправкой выполняется impact preview.</p><div className="admin-table-wrap"><table className="admin-table attribute-table"><thead><tr><th>Definition</th><th>Обязательное</th><th>Фильтр</th><th>Вариант</th></tr></thead><tbody>{attributes.map((attribute) => { const rule = rules.find((item) => item.attribute_id === attribute.id); return <tr key={attribute.id}><th><label className="rule-attribute"><input type="checkbox" checked={Boolean(rule)} onChange={(event) => { setSchemaImpact(null); toggleRule(attribute, event.target.checked); }}/><span>{attribute.name}<small>{attribute.code}</small></span></label></th>{(['required', 'filterable', 'variant_dimension'] as const).map((field) => <td key={field}><input aria-label={`${attribute.code} ${field}`} type="checkbox" checked={rule ? Boolean(rule[field]) : false} disabled={!rule} onChange={(event) => { setSchemaImpact(null); changeRule(attribute.id, field, event.target.checked); }}/></td>)}</tr>; })}</tbody></table></div>{schemaImpactJob && <div className="admin-notice" role="status" aria-live="polite"><strong>Schema impact preview {schemaImpactJob.status.toLowerCase()}</strong><p>{schemaImpactJob.stage.toLowerCase()} batch: {schemaImpactJob.stage === 'CATEGORIES' ? schemaImpactJob.processed_categories : schemaImpactJob.processed_products} / {schemaImpactJob.stage === 'CATEGORIES' ? schemaImpactJob.total_categories : schemaImpactJob.total_products}</p></div>}{schemaImpact && <div className="admin-notice" role="status"><strong>Impact preview</strong><p>{schemaImpact.affected_products} products · {schemaImpact.invalid_products} invalid · {schemaImpact.requires_reapproval} need re-review</p>{schemaImpact.warnings.length > 0 && <p>Warnings: {schemaImpact.warnings.join(', ')}</p>}<code>{schemaImpact.hash}</code></div>}<button className="admin-button admin-button-primary rule-save" onClick={() => void saveRules()} disabled={busy || Boolean(schemaImpactJob) || !attributes.length}>Сохранить правила</button></>}
        <form className="constraint-tester" onSubmit={validate}><p className="eyebrow">CONSTRAINT TESTER</p><label>Значения для проверки (JSON)<textarea rows={7} value={testerValues} onChange={(event) => setTesterValues(event.target.value)} spellCheck={false}/></label><button className="admin-button" type="submit" disabled={!selectedCategory}>Проверить по API</button>{testerError && <div className="admin-alert" role="alert">{testerError}</div>}{testerResult && <pre>{testerResult}</pre>}</form>
      </section>
    </div>
    <p className="form-hint taxonomy-footnote">InheritancePreview и условные правила не эмулируются в браузере: для них нужен подтверждённый B2B evaluator и контракт наследования.</p>
  </AdminShell>;
}
