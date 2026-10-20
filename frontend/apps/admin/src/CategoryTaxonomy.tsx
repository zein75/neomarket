'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AdminShell } from './AdminPage';

type Category = {
  id: string; parent_id: string | null; code: string; slug: string; name: string;
  labels: Record<string, string>;
  description: string | null; status: 'DRAFT' | 'REVIEW_PENDING' | 'ACTIVE' | 'HIDDEN' | 'ARCHIVED';
  sort_order: number | null; version: number; path: string | null; seo_title: string | null;
  image_media_id: string | null; updated_at: string | null;
};
type CategoryResponse = { items: Category[]; taxonomy_version: number };
type Draft = { parent_id: string; code: string; slug: string; name: string; labels: Array<{ locale: string; name: string }>; description: string; sort_order: string; seo_title: string; image_media_id: string };
type Retry = { key: string; signature: string };
type ImpactPreview = { change_id: string; affected_products: number; affected_sellers: number; affected_categories: number; invalid_products: number; requires_reapproval: number; redirects: Array<{ old_path: string; new_path: string }>; warnings: string[]; hash: string };
type ImpactJob = { job_id: string; status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'; stage: 'CATEGORIES' | 'PRODUCTS' | 'FINALIZE'; processed_categories: number; total_categories: number; processed_products: number; total_products: number; error_code: string | null; result: ImpactPreview | null };
const emptyDraft: Draft = { parent_id: '', code: '', slug: '', name: '', labels: [], description: '', sort_order: '', seo_title: '', image_media_id: '' };
const statuses: Record<Category['status'], string> = { DRAFT: 'Черновик', REVIEW_PENDING: 'На проверке', ACTIVE: 'Активна', HIDDEN: 'Скрыта', ARCHIVED: 'Архив' };

async function responseError(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; detail?: { code?: unknown; message?: unknown } | string; message?: unknown } | null;
  const code = typeof body?.code === 'string' ? body.code : typeof body?.detail === 'object' && typeof body.detail?.code === 'string' ? body.detail.code : '';
  const message = typeof body?.message === 'string' ? body.message : typeof body?.detail === 'object' && typeof body.detail?.message === 'string' ? body.detail.message : typeof body?.detail === 'string' ? body.detail : '';
  return [code, message, `HTTP ${response.status}`].filter(Boolean).join(' · ');
}

export function CategoryTaxonomy() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [taxonomyVersion, setTaxonomyVersion] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [moveMode, setMoveMode] = useState(false);
  const [moveParentId, setMoveParentId] = useState('');
  const [impactPreview, setImpactPreview] = useState<ImpactPreview | null>(null);
  const [impactJob, setImpactJob] = useState<ImpactJob | null>(null);
  const retry = useRef(new Map<string, Retry>());

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/admin/v1/taxonomy/categories', { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json() as CategoryResponse;
      if (!Array.isArray(data.items) || !Number.isInteger(data.taxonomy_version)) throw new Error('Ответ API не соответствует контракту CategoryTreeResponse.');
      setCategories(data.items); setTaxonomyVersion(data.taxonomy_version);
      setSelectedId((current) => data.items.some((item) => item.id === current) ? current : data.items[0]?.id ?? '');
    } catch (caught) {
      setCategories([]); setTaxonomyVersion(null);
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить категории.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!impactJob || !['QUEUED', 'RUNNING'].includes(impactJob.status)) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`/api/admin/v1/taxonomy/impact-preview-jobs/${encodeURIComponent(impactJob.job_id)}`, { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(await responseError(response));
        const job = await response.json() as ImpactJob;
        if (cancelled) return;
        if (job.job_id !== impactJob.job_id || !['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'].includes(job.status)) throw new Error('B2B returned an invalid impact job update.');
        if (job.status === 'FAILED') {
          setImpactJob(null);
          setImpactPreview(null);
          setError(`Impact calculation stopped: ${job.error_code ?? 'unknown failure'}. Request a fresh preview.`);
        } else if (job.status === 'COMPLETED') {
          if (!job.result || !/^[0-9a-f]{64}$/.test(job.result.hash)) throw new Error('B2B completed the impact job without a valid result.');
          setImpactPreview(job.result);
          setImpactJob(null);
          setNotice('Impact preview is ready. Review the counts and warnings before submitting the proposal.');
        } else {
          setImpactJob(job);
        }
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : 'Unable to refresh impact job status.');
        setImpactJob((current) => current ? { ...current } : null);
      }
    }, 1200);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [impactJob]);

  const selected = categories.find((category) => category.id === selectedId) ?? null;
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('ru');
    const matches = categories.filter((item) => !needle || [item.name, item.code, item.slug, item.path ?? ''].some((value) => value.toLocaleLowerCase('ru').includes(needle)));
    const byId = new Map(categories.map((item) => [item.id, item]));
    const compare = (a: Category, b: Category) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name, 'ru');
    const children = new Map<string, Category[]>();
    for (const item of categories) if (item.parent_id) children.set(item.parent_id, [...(children.get(item.parent_id) ?? []), item]);
    for (const items of children.values()) items.sort(compare);
    const included = new Set(matches.map((item) => item.id));
    const visited = new Set<string>();
    const ordered: Array<{ item: Category; depth: number }> = [];
    const visit = (item: Category, depth: number) => {
      if (visited.has(item.id)) return;
      visited.add(item.id);
      if (included.has(item.id)) ordered.push({ item, depth });
      for (const child of children.get(item.id) ?? []) visit(child, depth + 1);
    };
    categories.filter((item) => !item.parent_id || !byId.has(item.parent_id)).sort(compare).forEach((item) => visit(item, 0));
    categories.slice().sort(compare).forEach((item) => visit(item, 0));
    return ordered;
  }, [categories, query]);

  const resetEditor = () => { setEditing(false); setDraft(emptyDraft); };
  const beginCreate = () => { setSelectedId(''); setEditing(true); setDraft(emptyDraft); setError(''); setNotice(''); };
  const beginEdit = () => {
    if (!selected) return;
    setEditing(true); setError(''); setNotice('');
    setDraft({ parent_id: selected.parent_id ?? '', code: selected.code, slug: selected.slug, name: selected.name, labels: Object.entries(selected.labels ?? {}).map(([locale, name]) => ({ locale, name })), description: selected.description ?? '', sort_order: selected.sort_order === null ? '' : String(selected.sort_order), seo_title: selected.seo_title ?? '', image_media_id: selected.image_media_id ?? '' });
  };

  const submitProposal = async (operation: string, path: string, method: 'POST' | 'PATCH', body: unknown, etag?: string): Promise<boolean> => {
    const signature = JSON.stringify({ path, method, body, etag });
    let pending = retry.current.get(operation);
    if (pending && pending.signature !== signature) { setError('Предыдущий запрос не подтверждён. Повторите его с теми же данными после проверки статуса операции.'); return false; }
    if (!pending) { pending = { key: crypto.randomUUID(), signature }; retry.current.set(operation, pending); }
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(path, { method, cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': pending.key, ...(etag ? { 'If-Match': etag } : {}) }, body: JSON.stringify(body) });
      if (!response.ok) { if (response.status < 500) retry.current.delete(operation); throw new Error(await responseError(response)); }
      const result = await response.json() as { operation_id?: string; status?: string };
      retry.current.delete(operation);
      setNotice(`Предложение создано: ${result.status ?? 'статус не указан'}${result.operation_id ? ` · операция ${result.operation_id}` : ''}. Изменение вступит в силу после одобрения.`);
      resetEditor();
      return true;
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Ответ не получен. Повтор безопасен с тем же ключом идемпотентности.'); return false; }
    finally { setBusy(false); }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const labels: Record<string, string> = {};
    for (const row of draft.labels) {
      const locale = row.locale.trim(); const name = row.name.trim();
      if (!locale && !name) continue;
      if (!locale || !name) { setError('Для каждого перевода укажите язык и название.'); return; }
      if (Object.keys(labels).some((existing) => existing.toLocaleLowerCase() === locale.toLocaleLowerCase())) { setError(`Язык ${locale} указан несколько раз.`); return; }
      labels[locale] = name;
    }
    const payload = {
      parent_id: draft.parent_id || null, code: draft.code.trim(), slug: draft.slug.trim(), name: draft.name.trim(), labels,
      description: draft.description.trim() || null,
      ...(draft.sort_order.trim() ? { sort_order: Number(draft.sort_order) } : {}),
      ...(draft.seo_title.trim() ? { seo_title: draft.seo_title.trim() } : {}),
      ...(draft.image_media_id.trim() ? { image_media_id: draft.image_media_id.trim() } : {}),
    };
    if (!Number.isSafeInteger(payload.sort_order) && draft.sort_order.trim()) { setError('Порядок должен быть целым числом.'); return; }
    await submitProposal(editing && selected ? 'update' : 'create', editing && selected ? `/api/admin/v1/taxonomy/categories/${encodeURIComponent(selected.id)}` : '/api/admin/v1/taxonomy/categories', editing && selected ? 'PATCH' : 'POST', payload, editing && selected ? `v${selected.version}` : undefined);
  };

  const previewImpact = async (changeType: 'MOVE' | 'ARCHIVE', newParentId?: string) => {
    if (!selected) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(`/api/admin/v1/taxonomy/categories/${encodeURIComponent(selected.id)}/impact-preview`, {
        method: 'POST', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ change_type: changeType, ...(newParentId ? { new_parent_id: newParentId } : {}) }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json() as ImpactPreview | ImpactJob;
      if ('job_id' in result) {
        if (result.job_id.length < 1 || !['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'].includes(result.status)) throw new Error('B2B returned an invalid impact job.');
        if (result.status === 'COMPLETED' && result.result) {
          setImpactPreview(result.result);
          setImpactJob(null);
          setNotice('Impact preview is ready. Review the counts and warnings before submitting the proposal.');
          return;
        }
        if (result.status === 'FAILED') throw new Error(`Impact calculation stopped: ${result.error_code ?? 'unknown failure'}. Request a fresh preview.`);
        setImpactPreview(null);
        setImpactJob(result);
        setNotice('Large impact preview queued. Progress is saved after each batch and will resume after worker restart.');
        return;
      }
      if (!/^[0-9a-f]{64}$/.test(result.hash) || result.change_id === undefined) throw new Error('B2B returned an invalid impact preview.');
      setImpactPreview(result);
      setImpactJob(null);
      setNotice('Impact preview is ready. Review the counts and warnings before submitting the proposal.');
    } catch (caught) { setImpactPreview(null); setImpactJob(null); setError(caught instanceof Error ? caught.message : 'Impact preview is unavailable.'); }
    finally { setBusy(false); }
  };

  const move = async () => {
    if (!selected || !moveParentId || !impactPreview) return;
    if (await submitProposal('move', `/api/admin/v1/taxonomy/categories/${encodeURIComponent(selected.id)}/move`, 'POST', { new_parent_id: moveParentId, impact_hash: impactPreview.hash }, `v${selected.version}`)) {
      setMoveMode(false); setMoveParentId(''); setImpactPreview(null); setImpactJob(null);
    }
  };

  const archive = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected || !/^[A-Z][A-Z0-9_]{0,63}$/.test(reason.trim())) { setError('Reason code is required.'); return; }
    if (!impactPreview) { await previewImpact('ARCHIVE'); return; }
    if (await submitProposal('archive', `/api/admin/v1/taxonomy/categories/${encodeURIComponent(selected.id)}/archive`, 'POST', { reason_code: reason.trim().toUpperCase(), comment: comment.trim() || null, impact_hash: impactPreview.hash }, `v${selected.version}`)) { setReason(''); setComment(''); setImpactPreview(null); }
  };

  return <AdminShell section="/taxonomy/categories">
    <p className="eyebrow">ADMIN CONSOLE / TAXONOMY / CATEGORIES</p>
    <div className="admin-heading-row"><div><h1>Категории</h1><p className="admin-intro">Дерево каталога и карточка категории. Любое изменение создаёт предложение для согласования; опубликованные данные меняются только после maker-checker.</p></div><button className="admin-button" onClick={() => void load()} disabled={loading}>Обновить</button></div>
    {error && <div className="admin-alert" role="alert"><strong>Операция не выполнена</strong><span>{error}</span><p>Список не содержит демонстрационных данных. Проверьте доступ taxonomy.category и доступность текущего контракта снимка B2B.</p></div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    <div className="taxonomy-toolbar"><label>Поиск по названию, коду, slug или пути<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Например, ELECTRONICS" disabled={!categories.length}/></label><span>{taxonomyVersion === null ? 'Версия снимка недоступна' : `Версия таксономии ${taxonomyVersion} · ${categories.length} категорий`}</span><button className="admin-button admin-button-primary" onClick={beginCreate} disabled={loading}>Добавить категорию</button></div>
    <div className="taxonomy-workspace">
      <section className="admin-panel taxonomy-tree" aria-label="Дерево категорий"><div className="section-heading"><div><p className="eyebrow">CATEGORY TREE</p><h2>Структура</h2></div></div>
        {loading ? <p role="status">Загружаем актуальный снимок…</p> : error ? <p className="form-hint">Дерево недоступно, пока API не вернёт подтверждённые данные.</p> : filtered.length === 0 ? <div className="admin-empty"><h2>{categories.length ? 'Совпадений нет' : 'Категории не найдены'}</h2><p>{categories.length ? 'Измените поисковый запрос.' : 'API вернул пустой список.'}</p></div> : <ul className="taxonomy-list">{filtered.map(({ item, depth }) => <li key={item.id}><button className="taxonomy-node" style={{ paddingInlineStart: `${12 + Math.min(depth, 8) * 18}px` }} aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => { setSelectedId(item.id); resetEditor(); setError(''); setNotice(''); setImpactPreview(null); setImpactJob(null); }}><span className="taxonomy-node-name">{item.name}<small>{item.code} · {item.slug}</small></span><span className={`state-pill state-${item.status.toLowerCase()}`}>{statuses[item.status]}</span></button></li>)}</ul>}
      </section>
      <section className="admin-panel taxonomy-inspector" aria-label="Карточка категории">
        {editing ? <><p className="eyebrow">{selected ? 'UPDATE PROPOSAL' : 'NEW PROPOSAL'}</p><h2>{selected ? `Изменить: ${selected.name}` : 'Новая категория'}</h2><p className="form-hint">Смена родителя выполняется отдельной операцией перемещения и здесь недоступна.</p><form className="taxonomy-form" onSubmit={save}>
          <label>Родитель<select value={draft.parent_id} onChange={(event) => setDraft((current) => ({ ...current, parent_id: event.target.value }))} disabled={busy || Boolean(selected)}><option value="">Корневая категория</option>{categories.filter((item) => item.id !== selected?.id && item.status !== 'ARCHIVED').map((item) => <option value={item.id} key={item.id}>{item.name} · {item.code}</option>)}</select></label>
          <label>Код<input value={draft.code} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value }))} maxLength={80} required disabled={busy}/></label>
          <label>Slug<input value={draft.slug} onChange={(event) => setDraft((current) => ({ ...current, slug: event.target.value }))} maxLength={160} required disabled={busy}/></label>
          <label>Название по умолчанию<input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} maxLength={255} required disabled={busy}/></label>
          <fieldset className="taxonomy-wide category-label-editor"><legend>Переводы названия</legend><p className="form-hint">Язык указывается тегом BCP 47, например ru-RU или en-US.</p>{draft.labels.map((label, index) => <div className="category-label-row" key={`${index}-${label.locale}`}><label>Язык<input value={label.locale} onChange={(event) => setDraft((current) => ({ ...current, labels: current.labels.map((item, row) => row === index ? { ...item, locale: event.target.value } : item) }))} maxLength={35} autoComplete="off" disabled={busy}/></label><label>Название<input value={label.name} onChange={(event) => setDraft((current) => ({ ...current, labels: current.labels.map((item, row) => row === index ? { ...item, name: event.target.value } : item) }))} maxLength={255} disabled={busy}/></label><button className="admin-button" type="button" aria-label={`Удалить перевод ${label.locale || index + 1}`} onClick={() => setDraft((current) => ({ ...current, labels: current.labels.filter((_, row) => row !== index) }))} disabled={busy}>Удалить</button></div>)}<button className="admin-button category-label-add" type="button" onClick={() => setDraft((current) => ({ ...current, labels: [...current.labels, { locale: '', name: '' }] }))} disabled={busy}>Добавить язык</button></fieldset>
          <label>Порядок сортировки<input type="number" step="1" value={draft.sort_order} onChange={(event) => setDraft((current) => ({ ...current, sort_order: event.target.value }))} disabled={busy}/></label>
          <label>SEO title<input value={draft.seo_title} onChange={(event) => setDraft((current) => ({ ...current, seo_title: event.target.value }))} maxLength={255} disabled={busy}/></label>
          <label className="taxonomy-wide">Описание<textarea rows={4} value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} maxLength={5000} disabled={busy}/></label>
          <label className="taxonomy-wide">ID изображения (media)<input value={draft.image_media_id} onChange={(event) => setDraft((current) => ({ ...current, image_media_id: event.target.value }))} placeholder="UUID или пусто" disabled={busy}/></label>
          <div className="taxonomy-actions"><button className="admin-button admin-button-primary" type="submit" disabled={busy}>{busy ? 'Отправляем…' : 'Создать предложение'}</button><button className="admin-button" type="button" onClick={resetEditor} disabled={busy}>Отмена</button></div>
        </form></> : selected ? <><p className="eyebrow">CATEGORY INSPECTOR · V{selected.version}</p><h2>{selected.name}</h2><div className="taxonomy-detail-actions"><button className="admin-button" onClick={beginEdit} disabled={busy || selected.status === 'ARCHIVED'}>Редактировать</button><button className="admin-button" onClick={() => { setMoveMode(true); setMoveParentId(''); setImpactPreview(null); setImpactJob(null); setError(''); setNotice(''); }} disabled={busy || selected.status === 'ARCHIVED'}>Переместить</button></div>{moveMode && <div className="taxonomy-archive"><label>New parent<select value={moveParentId} onChange={(event) => { setMoveParentId(event.target.value); setImpactPreview(null); setImpactJob(null); }} disabled={busy}><option value="">Select a category</option>{categories.filter((item) => item.id !== selected.id && item.status !== 'ARCHIVED').map((item) => <option key={item.id} value={item.id}>{item.name} &middot; {item.code}</option>)}</select></label><div className="taxonomy-actions"><button className="admin-button" type="button" disabled={busy || !moveParentId} onClick={() => void previewImpact('MOVE', moveParentId)}>Preview impact</button><button className="admin-button admin-button-primary" type="button" disabled={busy || !impactPreview || !moveParentId} onClick={() => void move()}>Submit move proposal</button><button className="admin-button" type="button" disabled={busy} onClick={() => { setMoveMode(false); setImpactPreview(null); setImpactJob(null); }}>Cancel</button></div></div>}<dl className="taxonomy-details"><div><dt>Статус</dt><dd>{statuses[selected.status]}</dd></div><div><dt>Код</dt><dd><code>{selected.code}</code></dd></div><div><dt>Slug</dt><dd><code>{selected.slug}</code></dd></div><div><dt>Путь</dt><dd>{selected.path ?? 'Не указан в API'}</dd></div><div><dt>Родитель</dt><dd>{categories.find((item) => item.id === selected.parent_id)?.name ?? (selected.parent_id ? 'Родитель отсутствует в снимке' : 'Корень')}</dd></div><div><dt>Версия</dt><dd>{selected.version}</dd></div><div><dt>Обновлено</dt><dd>{selected.updated_at ? new Date(selected.updated_at).toLocaleString('ru-RU') : 'Не указано в API'}</dd></div><div className="taxonomy-wide"><dt>Описание</dt><dd>{selected.description || 'Описание отсутствует'}</dd></div><div className="taxonomy-wide"><dt>Переводы названия</dt><dd>{Object.entries(selected.labels ?? {}).length ? <ul className="category-label-list">{Object.entries(selected.labels ?? {}).map(([locale, name]) => <li key={locale}><code>{locale}</code><span>{name}</span></li>)}</ul> : "Переводы пока не добавлены"}</dd></div><div className="taxonomy-wide"><dt>SEO title</dt><dd>{selected.seo_title || 'Не задан'}</dd></div><div><dt>Image media ID</dt><dd>{selected.image_media_id ? <code>{selected.image_media_id}</code> : 'Не задан'}</dd></div></dl>
          {impactJob && <div className="admin-notice taxonomy-impact-note" role="status" aria-live="polite"><strong>Impact preview {impactJob.status.toLowerCase()}</strong><p>{impactJob.stage.toLowerCase()} batch: {impactJob.stage === 'CATEGORIES' ? impactJob.processed_categories : impactJob.processed_products} / {impactJob.stage === 'CATEGORIES' ? impactJob.total_categories : impactJob.total_products}</p><p>Progress is checkpointed; the worker can resume after restart. The move proposal stays disabled until the preview completes.</p></div>}
          {impactPreview && <div className="admin-notice taxonomy-impact-note"><strong>Impact preview</strong><p>{impactPreview.affected_products} products &middot; {impactPreview.affected_sellers} sellers &middot; {impactPreview.affected_categories} categories &middot; {impactPreview.invalid_products} invalid &middot; {impactPreview.requires_reapproval} need reapproval</p>{impactPreview.warnings.length > 0 && <p>Warnings: {impactPreview.warnings.join(', ')}</p>}{impactPreview.redirects.length > 0 && <ul>{impactPreview.redirects.slice(0, 20).map((redirect) => <li key={redirect.old_path}>{redirect.old_path} &rarr; {redirect.new_path}</li>)}</ul>}<code>{impactPreview.hash}</code></div>}
          {selected.status !== 'ARCHIVED' && <form className="taxonomy-archive" onSubmit={archive}><h3>Предложить архивирование</h3><label>Reason code<input value={reason} onChange={(event) => setReason(event.target.value.toUpperCase())} pattern="[A-Z][A-Z0-9_]{0,63}" required maxLength={64} disabled={busy}/></label><label>Комментарий<textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={3000} disabled={busy}/></label><button className="admin-button" type="submit" disabled={busy}>Создать предложение на архивирование</button><p className="form-hint">Архивирование использует версию v{selected.version}; дочерние категории и товарные последствия должны быть проверены до одобрения.</p></form>}
        </> : <div className="admin-empty"><h2>Выберите категорию</h2><p>Карточка покажет только поля, пришедшие из API.</p></div>}
      </section>
    </div>
    <p className="form-hint taxonomy-footnote">Category moves and archives require a fresh, version-bound B2B impact preview before an approval proposal can be submitted.</p>
  </AdminShell>;
}
