'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerNumber, sellerObject, sellerOptionalBoolean, sellerOptionalNullableString, sellerOptionalString, sellerString } from './lib/seller-api';
import { useEffect, useMemo, useState } from 'react';

type Product = { id: string; title: string; status: string; updated_at: string; deleted?: boolean };
type Decision = {
  event_id: string; action: string; status: string; reviewed_revision: number;
  ticket_id?: string | null; actor_id?: string | null; reason_code?: string | null;
  comment?: string | null; field_reports: { field_name?: string; field_path?: string | null; reason_code?: string | null; comment?: string; sku_id?: string | null }[];
  occurred_at: string;
};
type History = { status: string; items: Decision[] };

function decodeProduct(value: unknown): Product {
  const row = sellerObject(value, 'product');
  const deleted = sellerOptionalBoolean(row.deleted, 'product.deleted');
  return { id: sellerString(row.id, 'product.id'), title: sellerString(row.title, 'product.title'), status: sellerString(row.status, 'product.status'), updated_at: sellerString(row.updated_at, 'product.updated_at'), ...(deleted !== undefined ? { deleted } : {}) };
}

function decodeDecision(value: unknown): Decision {
  const row = sellerObject(value, 'decision');
  const ticketId = sellerOptionalNullableString(row.ticket_id, 'decision.ticket_id');
  const actorId = sellerOptionalNullableString(row.actor_id, 'decision.actor_id');
  const reasonCode = sellerOptionalNullableString(row.reason_code, 'decision.reason_code');
  const comment = sellerOptionalNullableString(row.comment, 'decision.comment');
  return {
    event_id: sellerString(row.event_id, 'decision.event_id'), action: sellerString(row.action, 'decision.action'), status: sellerString(row.status, 'decision.status'),
    reviewed_revision: sellerNumber(row.reviewed_revision, 'decision.reviewed_revision'),
    ...(ticketId !== undefined ? { ticket_id: ticketId } : {}), ...(actorId !== undefined ? { actor_id: actorId } : {}),
    ...(reasonCode !== undefined ? { reason_code: reasonCode } : {}), ...(comment !== undefined ? { comment } : {}),
    occurred_at: sellerString(row.occurred_at, 'decision.occurred_at'),
    field_reports: sellerArray(row.field_reports, 'decision.field_reports', (value) => {
      const report = sellerObject(value, 'field report');
      const fieldName = sellerOptionalString(report.field_name, 'field_report.field_name');
      const fieldPath = sellerOptionalNullableString(report.field_path, 'field_report.field_path');
      const reasonCode = sellerOptionalNullableString(report.reason_code, 'field_report.reason_code');
      const comment = sellerOptionalString(report.comment, 'field_report.comment');
      const skuId = sellerOptionalNullableString(report.sku_id, 'field_report.sku_id');
      return {
        ...(fieldName !== undefined ? { field_name: fieldName } : {}), ...(fieldPath !== undefined ? { field_path: fieldPath } : {}),
        ...(reasonCode !== undefined ? { reason_code: reasonCode } : {}), ...(comment !== undefined ? { comment } : {}),
        ...(skuId !== undefined ? { sku_id: skuId } : {}),
      };
    }),
  };
}

function decodeHistory(value: unknown): History {
  const row = sellerObject(value, 'moderation history');
  return { status: sellerString(row.status, 'moderation.status'), items: sellerArray(row.items, 'moderation.items', decodeDecision) };
}

function DecisionTimeline({ history }: { history: History }) {
  if (!history.items.length) return <p className="seller-muted">История решений пока пуста.</p>;
  return <ol className="moderation-timeline">{history.items.map((decision) => <li key={decision.event_id}>
    <div className="moderation-card-head"><strong>{decision.action}</strong><span className="status-badge">{decision.status}</span></div>
    <p>Проверенная версия: {decision.reviewed_revision}</p>
    {decision.reason_code && <p>Код причины: {decision.reason_code}</p>}
    {decision.comment && <p className="moderation-comment">{decision.comment}</p>}
    {decision.field_reports.length > 0 && <ul aria-label="Замечания по полям">{decision.field_reports.map((report, index) => <li key={`${decision.event_id}-${index}`}><strong>{report.field_path ?? report.field_name}</strong>{report.reason_code && ` · ${report.reason_code}`}{report.comment && <p>{report.comment}</p>}</li>)}</ul>}
    {decision.ticket_id && <p>Обращение: {decision.ticket_id}</p>}
    <time dateTime={decision.occurred_at}>{new Date(decision.occurred_at).toLocaleString('ru-RU')}</time>
  </li>)}</ol>;
}

export function ModerationPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [filter, setFilter] = useState('ALL');
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, History>>({});
  const [historyError, setHistoryError] = useState<Record<string, string>>({});
  const [loadingHistory, setLoadingHistory] = useState<string | null>(null);

  const loadProducts = () => {
    setPending(true); setError('');
    void sellerApiRequest('/api/seller/products?limit=100', { cache: 'no-store' }, (value) => {
      const payload = sellerObject(value, 'products');
      return { items: sellerArray(payload.items, 'products.items', decodeProduct) };
    })
      .then((payload) => setItems(payload.items.filter((item) => !item.deleted)))
      .catch((cause) => setError(sellerErrorMessage(cause, 'Не удалось загрузить статусы модерации')))
      .finally(() => setPending(false));
  };
  useEffect(loadProducts, []);

  const loadHistory = async (productId: string) => {
    setLoadingHistory(productId); setHistoryError((previous) => ({ ...previous, [productId]: '' }));
    try {
      const payload = await sellerApiRequest(`/api/seller/products/${productId}/moderation`, { cache: 'no-store' }, decodeHistory);
      setHistory((previous) => ({ ...previous, [productId]: payload }));
    } catch (cause) {
      setHistoryError((previous) => ({ ...previous, [productId]: sellerErrorMessage(cause, 'Не удалось загрузить историю решений') }));
    } finally { setLoadingHistory(null); }
  };
  const toggle = (productId: string) => {
    if (expanded === productId) { setExpanded(null); return; }
    setExpanded(productId);
    if (!history[productId]) void loadHistory(productId);
  };
  const statuses = useMemo(() => ['ALL', ...Array.from(new Set(items.map((item) => item.status)))], [items]);
  const visible = filter === 'ALL' ? items : items.filter((item) => item.status === filter);

  return <main className="seller-app" id="main-content">
    <SellerSidebar variant="catalog" activePath="/moderation" badge="READ-ONLY STATUS" />
    <section className="seller-content"><div className="private-bar"><span>SELLER / MODERATION</span><span>SERVER AUTHORITATIVE</span></div><p className="eyebrow">SELLER HUB / SE-10</p><h1>Модерация</h1><p className="seller-intro">Статусы и история решений показаны из B2B API. Решения Admin доступны только для чтения.</p>
      {pending && <p className="seller-state" role="status">Загружаем статусы…</p>}
      {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={loadProducts}>Повторить</button></div>}
      {!pending && !error && <><div className="moderation-filters" role="group" aria-label="Фильтр статуса">{statuses.map((status) => <button key={status} className={filter === status ? 'active' : ''} type="button" onClick={() => setFilter(status)}>{status === 'ALL' ? 'Все' : status}</button>)}</div>
        {visible.length === 0 ? <div className="seller-state"><h2>Совпадений нет</h2><p>По выбранному статусу товары не найдены.</p></div> : <div className="moderation-list">{visible.map((item) => <article className="moderation-card" key={item.id}>
          <div className="moderation-card-head"><div><p className="eyebrow">{item.id}</p><h2>{item.title}</h2></div><span className="status-badge">{item.status}</span></div>
          <p><time dateTime={item.updated_at}>Обновлено: {new Date(item.updated_at).toLocaleString('ru-RU')}</time></p>
          <button className="seller-submit" type="button" aria-expanded={expanded === item.id} aria-controls={`moderation-history-${item.id}`} onClick={() => toggle(item.id)}>{expanded === item.id ? 'Скрыть историю решений' : 'Показать историю решений'}</button>
          {expanded === item.id && <section id={`moderation-history-${item.id}`} aria-label={`История модерации: ${item.title}`}>
            {loadingHistory === item.id && <p className="seller-state" role="status">Загружаем историю…</p>}
            {historyError[item.id] && <div className="seller-state seller-error" role="alert"><strong>{historyError[item.id]}</strong><button type="button" className="seller-submit" onClick={() => void loadHistory(item.id)}>Повторить</button></div>}
            {history[item.id] && <DecisionTimeline history={history[item.id]!} />}
          </section>}
        </article>)}</div>}</>}
    </section>
  </main>;
}

